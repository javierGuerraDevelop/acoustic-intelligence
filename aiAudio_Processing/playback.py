"""Playback leases for speech feedback suppression (architecture plan 5.8).

The dashboard registers playback before audio starts, renews the lease once a
second and releases it when playback ends. The detection pipeline drops audio
while a lease is active and for a short grace period afterward so the spoken
alert does not retrigger the detector.
"""

from __future__ import annotations

import threading
import time

PLAYBACK_LEASE_SECONDS = 3.0
PLAYBACK_MAX_SECONDS = 15.0
SUPPRESSION_GRACE_SECONDS = 2.0


class PlaybackConflict(Exception):
    """Another playback already holds the single device lease."""


class PlaybackRegistry:
    def __init__(self, *, monotonic=time.monotonic):
        self._lock = threading.Lock()
        self._monotonic = monotonic
        self._playback_id = None
        self._lease_deadline = 0.0
        self._max_deadline = 0.0
        self._suppress_until = 0.0

    def start(self, playback_id):
        now = self._monotonic()
        with self._lock:
            active = (
                self._playback_id is not None
                and now < self._lease_deadline
                and now < self._max_deadline
            )
            if active and self._playback_id != playback_id:
                raise PlaybackConflict()
            if self._playback_id != playback_id:
                self._max_deadline = now + PLAYBACK_MAX_SECONDS
            self._playback_id = playback_id
            self._lease_deadline = now + PLAYBACK_LEASE_SECONDS

    def end(self, playback_id):
        now = self._monotonic()
        with self._lock:
            if self._playback_id == playback_id:
                self._playback_id = None
                self._lease_deadline = 0.0
                self._max_deadline = 0.0
            self._suppress_until = now + SUPPRESSION_GRACE_SECONDS

    def suppressing(self):
        now = self._monotonic()
        with self._lock:
            if (
                self._playback_id is not None
                and now < self._lease_deadline
                and now < self._max_deadline
            ):
                return True
            return now < self._suppress_until
