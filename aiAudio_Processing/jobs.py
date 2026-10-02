"""In-process background jobs backing /v1/summary and /v1/privacy/delete.

Jobs are intentionally process-local: the change feed already resets on
restart, and pending remote work cannot survive one either. Terminal jobs stay
in memory for the lifetime of the service so the dashboard can poll
``GET /v1/jobs/{job_id}``; delete jobs are never evicted by capacity limits.
"""
from __future__ import annotations

import copy
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from events import format_utc

logger = logging.getLogger(__name__)

SUMMARY_KIND = "summary"
DELETE_KIND = "delete"
TERMINAL_STATES = frozenset({"complete", "failed"})
SUMMARY_MIN_INTERVAL_SECONDS = 60


class JobConflict(Exception):
    """The request cannot create a new job; maps to a canonical API error."""

    def __init__(self, status_code, code, message, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


class JobFailure(Exception):
    """Sanitized job failure; may carry a partial result (e.g. local complete)."""

    def __init__(self, code, retryable, message, result=None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.message = message
        self.result = result


class JobRegistry:
    """Creates, tracks and publishes ``job.changed`` changes."""

    def __init__(self, changes, monotonic=time.monotonic, now=None):
        self._changes = changes
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._jobs = {}
        self._by_request = {}
        self._last_summary_started = None

    def create(self, kind, request_id):
        """Return (job, created); a repeated request_id returns the same job."""
        request_id = str(request_id)
        with self._lock:
            existing_id = self._by_request.get(request_id)
            if existing_id is not None:
                job = self._jobs[existing_id]
                if job["kind"] != kind:
                    raise JobConflict(409, "CONFLICT", "request_id is already used by a different job.")
                return copy.deepcopy(job), False

            if kind == SUMMARY_KIND:
                self._check_summary_capacity()

            job = {
                "schema_version": 1,
                "job_id": str(uuid.uuid4()),
                "kind": kind,
                "state": "pending",
                "updated_at": format_utc(self._now()),
                "result": None,
                "error": None,
            }
            self._jobs[job["job_id"]] = job
            self._by_request[request_id] = job["job_id"]
            self._publish(job)
            return copy.deepcopy(job), True

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job is not None else None

    def start(self, job_id, work):
        """Run blocking work on a daemon thread and record its outcome."""
        thread = threading.Thread(
            target=self._run, args=(job_id, work), name=f"job-{job_id}", daemon=True
        )
        thread.start()
        return thread

    def _check_summary_capacity(self):
        busy = any(
            job["kind"] == SUMMARY_KIND and job["state"] not in TERMINAL_STATES
            for job in self._jobs.values()
        )
        if busy:
            raise JobConflict(429, "CAPACITY", "A summary is already running.", retryable=True)
        if (
            self._last_summary_started is not None
            and self._monotonic() - self._last_summary_started < SUMMARY_MIN_INTERVAL_SECONDS
        ):
            raise JobConflict(429, "CAPACITY", "Only one summary can be generated per minute.", retryable=True)
        self._last_summary_started = self._monotonic()

    def _run(self, job_id, work):
        self._transition(job_id, "running")
        try:
            result = work()
        except JobFailure as failure:
            self._transition(
                job_id,
                "failed",
                result=failure.result,
                error={
                    "code": failure.code,
                    "retryable": failure.retryable,
                    "message": failure.message,
                },
            )
        except Exception:
            logger.exception("Job %s failed unexpectedly", job_id)
            self._transition(
                job_id,
                "failed",
                error={
                    "code": "INTERNAL",
                    "retryable": True,
                    "message": "The job failed unexpectedly.",
                },
            )
        else:
            self._transition(job_id, "complete", result=result)

    def _transition(self, job_id, state, result=None, error=None):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["state"] = state
            job["updated_at"] = format_utc(self._now())
            if result is not None:
                job["result"] = result
            if error is not None:
                job["error"] = error
            self._publish(job)

    def _publish(self, job):
        self._changes.append("job.changed", {"job": copy.deepcopy(job)})
