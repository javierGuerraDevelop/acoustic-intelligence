"""Continuous two-second window detection over the Edge 1 chunk queue.

The queue worker hands every accepted chunk here. Windows are contiguous by
construction: sequence gaps, stale chunks and stream changes clear the rolling
window and reset detector smoothing (architecture plan 5.2 and 6).
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import numpy as np

from events import create_canonical_event

logger = logging.getLogger(__name__)

WINDOW_CHUNKS = 2
CHUNK_SECONDS = 1.0
RMS_FLOOR_DBFS = -120.0


class DetectionPipeline:
    """Consume chunks, classify each completed window, persist canonical events."""

    def __init__(self, classifier_provider, store, changes, registry, playback=None, *, clock=None):
        self._classifier_provider = classifier_provider
        self._store = store
        self._changes = changes
        self._registry = registry
        self._playback = playback
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._window = deque(maxlen=WINDOW_CHUNKS)
        self._stream_id = None
        self._device_id = None
        self._event_seq = 0
        self._suppressed = False
        self.audio_gaps = 0
        self.inference_failures = 0

    def handle_chunk(self, chunk):
        classifier = self._classifier_provider()
        if classifier is None:
            return

        if self._playback is not None and self._playback.suppressing():
            if not self._suppressed:
                self._suppressed = True
                self._window.clear()
                self._reset_smoothing(classifier)
            return
        if self._suppressed:
            self._suppressed = False
            self._window.clear()
            self._reset_smoothing(classifier)

        reset_rules = False
        if self._registry.take_gap(chunk.device_id, chunk.stream_id):
            self.audio_gaps += 1
            reset_rules = True
        if chunk.stream_id != self._stream_id or chunk.device_id != self._device_id:
            self._stream_id = chunk.stream_id
            self._device_id = chunk.device_id
            self._event_seq = 0
            reset_rules = True
        if reset_rules:
            self._window.clear()
            self._reset_smoothing(classifier)

        self._window.append(chunk)
        if len(self._window) == WINDOW_CHUNKS:
            self._infer(classifier)

    def _reset_smoothing(self, classifier):
        reset = getattr(classifier, "reset_continuity", None)
        if callable(reset):
            reset()

    def _infer(self, classifier):
        first, last = self._window[0], self._window[-1]
        pcm = b"".join(chunk.pcm for chunk in self._window)
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0

        started = time.perf_counter()
        try:
            prediction = classifier.classify(samples, continuous=True)
        except Exception:
            self.inference_failures += 1
            logger.exception("Live window inference failed")
            return
        inference_ms = int(round((time.perf_counter() - started) * 1000))
        if prediction is None:
            return

        detected_at = self._clock()
        occurred_at = last.captured_at + timedelta(seconds=CHUNK_SECONDS)
        self._event_seq += 1
        event = create_canonical_event(
            device_id=last.device_id,
            stream_id=last.stream_id,
            event_seq=self._event_seq,
            window_start_at=first.captured_at,
            occurred_at=occurred_at,
            detected_at=detected_at,
            prediction=prediction,
            last_chunk_seq=last.chunk_seq,
            inference_ms=inference_ms,
            rms_dbfs=_window_rms_dbfs(samples),
            dropped_frames_total=last.dropped_frames_total,
        )
        try:
            self._store.save_event(event, kind="live")
        except sqlite3.Error:
            logger.exception("Failed to persist a live detection event")
            return
        self._changes.append("event.created", {"event": event}, event_id=event["event_id"])


def _window_rms_dbfs(samples):
    if samples.size == 0:
        return RMS_FLOOR_DBFS
    mean_square = float(np.mean(np.square(samples)))
    if mean_square <= 0.0:
        return RMS_FLOOR_DBFS
    return max(RMS_FLOOR_DBFS, 20.0 * math.log10(math.sqrt(mean_square)))
