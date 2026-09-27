"""Snowflake analytics adapter for Live Sound Radar (architecture section 5.7).

Blocking functions, owned by M1, invoked by M2's cloud scheduler inside a
dedicated executor. The cloud host supplies authentication context, scheduling
and the single-writer serialization guard; this module never starts a server,
thread or background daemon. Every statement is parameterized. The event MERGE
is idempotent on ``EVENT_ID`` so a retried export is counted once.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator, Sequence

from .config import SnowflakeConfig
from .errors import AdapterError
from .models import (
    ALLOWED_LABELS,
    ALLOWED_SEVERITIES,
    MAX_SUMMARY_CHARS,
    AnalyticsRow,
    ExportResult,
    SummaryResult,
)

TARGET_TABLE = "ACOUSTIC_EVENTS"
MAX_ROWS_PER_MERGE = 50

_MERGE_TEMPLATE = """
MERGE INTO {table} AS t
USING (
{source}
) AS s
ON t.EVENT_ID = s.EVENT_ID
WHEN NOT MATCHED THEN INSERT (
    SCHEMA_VERSION, EVENT_ID, ANALYTICS_DEVICE_ID, OCCURRED_AT, LABEL,
    MODEL_SCORE, SEVERITY, MODEL_ID, RULE_VERSION, EXPIRES_AT
) VALUES (
    s.SCHEMA_VERSION, s.EVENT_ID, s.ANALYTICS_DEVICE_ID, s.OCCURRED_AT, s.LABEL,
    s.MODEL_SCORE, s.SEVERITY, s.MODEL_ID, s.RULE_VERSION, s.EXPIRES_AT
)
"""

_ROW_SELECT = (
    "SELECT %s AS SCHEMA_VERSION, %s AS EVENT_ID, %s AS ANALYTICS_DEVICE_ID, "
    "TO_TIMESTAMP_TZ(%s) AS OCCURRED_AT, %s AS LABEL, %s AS MODEL_SCORE, "
    "%s AS SEVERITY, %s AS MODEL_ID, %s AS RULE_VERSION, TO_TIMESTAMP_TZ(%s) AS EXPIRES_AT"
)

_COUNTS_SQL = f"""
SELECT LABEL, COUNT(*) AS EVENT_COUNT
FROM {TARGET_TABLE}
WHERE ANALYTICS_DEVICE_ID = %s
  AND OCCURRED_AT >= TO_TIMESTAMP_TZ(%s)
  AND EXPIRES_AT > CURRENT_TIMESTAMP()
GROUP BY LABEL
"""

_LATEST_SQL = f"""
SELECT MAX(OCCURRED_AT) AS THROUGH_AT
FROM {TARGET_TABLE}
WHERE ANALYTICS_DEVICE_ID = %s
  AND OCCURRED_AT >= TO_TIMESTAMP_TZ(%s)
  AND EXPIRES_AT > CURRENT_TIMESTAMP()
"""

_AI_COMPLETE_SQL = "SELECT AI_COMPLETE(%s, %s) AS SUMMARY_TEXT"

_DELETE_SQL = f"DELETE FROM {TARGET_TABLE} WHERE ANALYTICS_DEVICE_ID = %s"

_PURGE_SQL = f"DELETE FROM {TARGET_TABLE} WHERE EXPIRES_AT <= TO_TIMESTAMP_TZ(%s)"

_PROMPT_TEMPLATE = (
    "Summarize these detector-event counts in two short sentences. "
    "They are possible detections, not confirmed visits. "
    "Mention the most frequent class and suggest reviewing its timestamps. "
    "Do not infer emergencies, locations, causes, or absence of missed events. "
    "Counts: {counts}. Window: last {minutes} minutes."
)

_EMPTY_SUMMARY_TEXT = (
    "No permitted detector events were found in the requested window. "
    "There is nothing to summarize."
)


class SnowflakeAnalyticsAdapter:
    """Parameterized, idempotent analytics access.

    ``connect_factory`` exists for tests and local fakes; production passes
    ``None`` so the configured key-pair connection is opened per call.
    """

    def __init__(
        self,
        config: SnowflakeConfig,
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._connect_factory = connect_factory

    # -- public interface -------------------------------------------------

    def upsert_events(self, rows: list[AnalyticsRow]) -> ExportResult:
        ordered = _validate_and_dedupe(rows)
        if not ordered:
            raise AdapterError("BAD_INPUT", False)

        query_id = ""
        with self._cursor() as cursor:
            for batch in _chunked(ordered, MAX_ROWS_PER_MERGE):
                sql, params = _build_merge(batch)
                self._execute(cursor, sql, params)
                query_id = _query_id(cursor) or query_id
        return ExportResult(event_ids=[row.event_id for row in ordered], query_id=query_id)

    def summarize(self, device_key: str, since_utc: str) -> SummaryResult:
        if not device_key:
            raise AdapterError("BAD_INPUT", False)
        since = _normalize_utc(since_utc)
        now = _utc_now()
        if _parse_utc(since) > now:
            raise AdapterError("BAD_INPUT", False)

        with self._cursor() as cursor:
            self._execute(cursor, _COUNTS_SQL, (device_key, since))
            counts: dict[str, int] = {}
            for label, count in cursor.fetchall():
                if label in ALLOWED_LABELS:
                    counts[str(label)] = int(count)
            event_count = sum(counts.values())

            if event_count == 0:
                return SummaryResult(
                    text=_EMPTY_SUMMARY_TEXT,
                    event_count=0,
                    counts={},
                    since=since,
                    through=since,
                    generated_at=_format_utc(now),
                    model=None,
                    query_id=None,
                )

            self._execute(cursor, _LATEST_SQL, (device_key, since))
            latest = cursor.fetchone()
            through = _format_utc(_coerce_datetime(latest[0])) if latest and latest[0] else since

            model = self._config.ai_model
            prompt = _build_prompt(counts, since, now)
            self._execute(cursor, _AI_COMPLETE_SQL, (model, prompt))
            ai_row = cursor.fetchone()
            text = str(ai_row[0]) if ai_row and ai_row[0] is not None else ""
            text = text[:MAX_SUMMARY_CHARS]
            query_id = _query_id(cursor)

        return SummaryResult(
            text=text,
            event_count=event_count,
            counts=counts,
            since=since,
            through=through,
            generated_at=_format_utc(now),
            model=model,
            query_id=query_id or None,
        )

    def delete_events(self, device_key: str) -> None:
        if not device_key:
            raise AdapterError("BAD_INPUT", False)
        with self._cursor() as cursor:
            self._execute(cursor, _DELETE_SQL, (device_key,))

    def purge_expired(self, now_utc: str) -> int:
        now = _normalize_utc(now_utc)
        with self._cursor() as cursor:
            self._execute(cursor, _PURGE_SQL, (now,))
            return int(cursor.rowcount if cursor.rowcount is not None else 0)

    # -- internals --------------------------------------------------------

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            try:
                yield cursor
            finally:
                cursor.close()
        finally:
            try:
                connection.close()
            except Exception:  # pragma: no cover - close best effort
                pass

    def _connect(self) -> Any:
        if self._connect_factory is not None:
            factory = self._connect_factory
        else:
            from snowflake.connector import connect as factory  # type: ignore[no-redef]

        try:
            return factory(**self._config.connect_kwargs())
        except Exception as exc:
            raise _map_exception(exc) from None

    def _execute(self, cursor: Any, sql: str, params: Sequence[Any] | None = None) -> None:
        try:
            cursor.execute(sql, params, timeout=self._config.query_timeout_seconds)
        except Exception as exc:
            raise _map_exception(exc) from None


# -- validation helpers ---------------------------------------------------


def _validate_and_dedupe(rows: Iterable[AnalyticsRow]) -> list[AnalyticsRow]:
    seen: set[str] = set()
    ordered: list[AnalyticsRow] = []
    for row in rows:
        _validate_row(row)
        if row.event_id in seen:
            continue
        seen.add(row.event_id)
        ordered.append(row)
    return ordered


def _validate_row(row: AnalyticsRow) -> None:
    if row.schema_version != 1:
        raise AdapterError("BAD_INPUT", False)
    if not row.event_id or not row.analytics_device_id:
        raise AdapterError("BAD_INPUT", False)
    if row.label not in ALLOWED_LABELS:
        raise AdapterError("BAD_INPUT", False)
    if row.severity not in ALLOWED_SEVERITIES:
        raise AdapterError("BAD_INPUT", False)
    if not row.model_id or not row.rule_version:
        raise AdapterError("BAD_INPUT", False)
    if not isinstance(row.model_score, (int, float)) or not math.isfinite(row.model_score):
        raise AdapterError("BAD_INPUT", False)
    if not 0.0 <= float(row.model_score) <= 1.0:
        raise AdapterError("BAD_INPUT", False)
    occurred = _parse_utc(_normalize_utc(row.occurred_at))
    expires = _parse_utc(_normalize_utc(row.expires_at))
    if expires < occurred:
        raise AdapterError("BAD_INPUT", False)


def _build_merge(rows: Sequence[AnalyticsRow]) -> tuple[str, list[Any]]:
    selects = []
    params: list[Any] = []
    for row in rows:
        selects.append(_ROW_SELECT)
        params.extend(
            [
                row.schema_version,
                row.event_id,
                row.analytics_device_id,
                _normalize_utc(row.occurred_at),
                row.label,
                float(row.model_score),
                row.severity,
                row.model_id,
                row.rule_version,
                _normalize_utc(row.expires_at),
            ]
        )
    source = "\n    UNION ALL\n".join(selects)
    return _MERGE_TEMPLATE.format(table=TARGET_TABLE, source=source), params


def _build_prompt(counts: dict[str, int], since: str, now: _dt.datetime) -> str:
    minutes = max(1, int(round((now - _parse_utc(since)).total_seconds() / 60.0)))
    counts_json = json.dumps(counts, sort_keys=True, separators=(",", ":"))
    return _PROMPT_TEMPLATE.format(counts=counts_json, minutes=minutes)


def _chunked(items: Sequence[AnalyticsRow], size: int) -> Iterator[Sequence[AnalyticsRow]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _query_id(cursor: Any) -> str:
    value = getattr(cursor, "sfqid", None)
    return str(value) if value else ""


# -- time helpers ---------------------------------------------------------


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse_utc(value: str) -> _dt.datetime:
    try:
        parsed = _dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise AdapterError("BAD_INPUT", False) from exc
    if parsed.tzinfo is None:
        raise AdapterError("BAD_INPUT", False)
    return parsed.astimezone(_dt.timezone.utc)


def _normalize_utc(value: str) -> str:
    parsed = _parse_utc(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def _format_utc(value: _dt.datetime) -> str:
    normalized = value.astimezone(_dt.timezone.utc)
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.") + f"{normalized.microsecond // 1000:03d}Z"


def _coerce_datetime(value: Any) -> _dt.datetime:
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_dt.timezone.utc)
        return value
    return _parse_utc(str(value))


# -- error mapping --------------------------------------------------------


def _map_exception(exc: Exception) -> AdapterError:
    """Map provider exceptions to sanitized adapter codes.

    Authentication problems are terminal; timeouts/rate limits/outages retry.
    Unknown exceptions map to retryable ``UNAVAILABLE`` so the host never
    surfaces raw provider text.
    """

    message = str(exc).lower()
    status = getattr(exc, "errno", None)

    if "authentication" in message or "incorrect username or password" in message:
        return AdapterError("AUTH_FAILED", False)
    if "rate" in message and "limit" in message:
        return AdapterError("RATE_LIMITED", True)
    if "timeout" in message or "timed out" in message:
        return AdapterError("TIMEOUT", True)

    try:
        from snowflake.connector import errors as sf_errors

        if isinstance(exc, sf_errors.InterfaceError):
            return AdapterError("UNAVAILABLE", True)
        if isinstance(exc, sf_errors.OperationalError):
            if isinstance(status, int) and status in (601, 602, 604):
                return AdapterError("TIMEOUT", True)
            return AdapterError("UNAVAILABLE", True)
        if isinstance(exc, sf_errors.ProgrammingError):
            return AdapterError("BAD_INPUT", False)
        if isinstance(exc, sf_errors.DatabaseError):
            return AdapterError("BAD_INPUT", False)
    except ImportError:  # pragma: no cover - connector absent in some tests
        pass

    return AdapterError("UNAVAILABLE", True)
