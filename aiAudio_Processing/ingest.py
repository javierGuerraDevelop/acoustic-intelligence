"""Edge 1 ingest state for the local service (architecture plan 5.2).

This module owns header/body validation, the one-active-stream registry,
recent-duplicate retention and the bounded two-chunk audio queue. The API
layer maps ``IngestError`` onto the canonical error envelope. The detection
worker attaches its sink to the queue in the next integration step; until
then the queue worker drains accepted chunks without inference so the
producer is never stalled.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Mapping

logger = logging.getLogger(__name__)

CHUNK_BYTES = 32000
CHUNK_FRAMES = 16000
WIRE_SAMPLE_RATE_HZ = 16000
WIRE_CHANNELS = 1
WIRE_ENCODING = "pcm_s16le"
WIRE_SCHEMA_VERSION = 1
QUEUE_CAPACITY = 2
DUPLICATE_TTL_SECONDS = 60.0
STALE_CHUNK_SECONDS = 3.0
HEARTBEAT_LEASE_MS = 2000
HEARTBEAT_STALE_SECONDS = 5.0


class IngestError(Exception):
    """Contract violation detected before enqueue; the API maps it to JSON."""

    def __init__(self, status_code, code, message, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class Chunk:
    device_id: str
    stream_id: str
    chunk_seq: int
    start_sample: int
    captured_at: datetime
    pcm: bytes
    rms_dbfs: float
    dropped_frames_total: int
    received_monotonic: float


@dataclass
class DeviceCaptureState:
    device_id: str
    state: str = "stopped"
    active_stream_id: str | None = None
    last_stream_id: str | None = None
    native_rate_hz: int | None = None
    dropped_frames_total: int = 0
    error_code: str | None = None
    last_seq: int = -1
    gap_pending: bool = False
    last_heartbeat_monotonic: float | None = None
    last_chunk_monotonic: float | None = None
    chunks_accepted: int = 0
    chunks_dropped: int = 0


def _required(headers, name):
    value = headers.get(name)
    if value is None or value == "":
        raise IngestError(422, "SCHEMA_INVALID", f"Missing header {name}.")
    return value


def _parse_int(headers, name, minimum=None):
    raw = _required(headers, name)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise IngestError(422, "SCHEMA_INVALID", f"Header {name} must be an integer.") from None
    if minimum is not None and value < minimum:
        raise IngestError(422, "SCHEMA_INVALID", f"Header {name} must be >= {minimum}.")
    return value


def _parse_uuid(headers, name):
    raw = _required(headers, name)
    try:
        return str(uuid.UUID(raw))
    except (TypeError, ValueError):
        raise IngestError(422, "SCHEMA_INVALID", f"Header {name} must be a UUID.") from None


def _parse_captured_at(headers):
    raw = _required(headers, "X-Captured-At")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise IngestError(422, "SCHEMA_INVALID", "X-Captured-At must be RFC 3339.") from None
    if parsed.tzinfo is None:
        raise IngestError(422, "SCHEMA_INVALID", "X-Captured-At must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _parse_rms(headers):
    raw = _required(headers, "X-Rms-Dbfs")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise IngestError(422, "SCHEMA_INVALID", "X-Rms-Dbfs must be a number.") from None
    if not math.isfinite(value) or not -120.0 <= value <= 0.0:
        raise IngestError(422, "SCHEMA_INVALID", "X-Rms-Dbfs must be within [-120, 0].")
    return value


def parse_chunk(headers: Mapping[str, str], body: bytes, *, monotonic=None) -> Chunk:
    """Validate one wire chunk, raising IngestError on any contract violation."""
    if len(body) != CHUNK_BYTES:
        raise IngestError(413, "TOO_LARGE", f"Chunk body must be exactly {CHUNK_BYTES} bytes.")
    if _parse_int(headers, "X-Schema-Version") != WIRE_SCHEMA_VERSION:
        raise IngestError(422, "SCHEMA_INVALID", "Unsupported schema version.")
    device_id = _parse_uuid(headers, "X-Device-Id")
    stream_id = _parse_uuid(headers, "X-Stream-Id")
    chunk_seq = _parse_int(headers, "X-Chunk-Seq", minimum=0)
    start_sample = _parse_int(headers, "X-Start-Sample", minimum=0)
    if start_sample != chunk_seq * CHUNK_FRAMES:
        raise IngestError(422, "SCHEMA_INVALID", "X-Start-Sample must equal chunk_seq * 16000.")
    captured_at = _parse_captured_at(headers)
    if _parse_int(headers, "X-Sample-Rate") != WIRE_SAMPLE_RATE_HZ:
        raise IngestError(422, "SCHEMA_INVALID", f"X-Sample-Rate must be {WIRE_SAMPLE_RATE_HZ}.")
    if _parse_int(headers, "X-Channels") != WIRE_CHANNELS:
        raise IngestError(422, "SCHEMA_INVALID", f"X-Channels must be {WIRE_CHANNELS}.")
    if _required(headers, "X-Encoding") != WIRE_ENCODING:
        raise IngestError(422, "SCHEMA_INVALID", f"X-Encoding must be {WIRE_ENCODING}.")
    return Chunk(
        device_id=device_id,
        stream_id=stream_id,
        chunk_seq=chunk_seq,
        start_sample=start_sample,
        captured_at=captured_at,
        pcm=bytes(body),
        rms_dbfs=_parse_rms(headers),
        dropped_frames_total=_parse_int(headers, "X-Dropped-Frames-Total", minimum=0),
        received_monotonic=time.monotonic() if monotonic is None else monotonic,
    )


def chunk_age_seconds(chunk: Chunk, now=None) -> float:
    now = now or datetime.now(timezone.utc)
    return (now - chunk.captured_at).total_seconds()


class CaptureRegistry:
    """Track the single active stream per device and recent duplicate IDs."""

    def __init__(self, *, duplicate_ttl=DUPLICATE_TTL_SECONDS, monotonic=time.monotonic):
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceCaptureState] = {}
        self._recent: dict[tuple[str, int], float] = {}
        self._duplicate_ttl = duplicate_ttl
        self._monotonic = monotonic

    def record_heartbeat(self, *, device_id, stream_id, state, native_rate_hz,
                         dropped_frames_total, error_code):
        with self._lock:
            device = self._devices.setdefault(device_id, DeviceCaptureState(device_id))
            device.state = state
            device.native_rate_hz = native_rate_hz
            device.dropped_frames_total = dropped_frames_total
            device.error_code = error_code
            device.last_heartbeat_monotonic = self._monotonic()
            if state == "running" and stream_id:
                if device.active_stream_id != stream_id:
                    # A pause, overflow or device change retires the old stream.
                    device.active_stream_id = stream_id
                    device.last_seq = -1
                    device.gap_pending = False
                device.last_stream_id = stream_id
            else:
                if stream_id:
                    device.last_stream_id = stream_id
                device.active_stream_id = None
            return replace(device)

    def admit(self, chunk: Chunk) -> str:
        """Return "accepted" or "duplicate"; raise IngestError for 409 cases."""
        now = chunk.received_monotonic
        with self._lock:
            self._prune_recent(now)
            key = (chunk.stream_id, chunk.chunk_seq)
            if key in self._recent:
                return "duplicate"
            device = self._devices.get(chunk.device_id)
            if device is None or device.active_stream_id != chunk.stream_id:
                raise IngestError(409, "STREAM_CONFLICT", "Unknown or retired stream.")
            if device.last_seq >= 0 and chunk.chunk_seq <= device.last_seq:
                raise IngestError(409, "OUT_OF_ORDER", "Chunk sequence overlaps an earlier chunk.")
            if device.last_seq >= 0 and chunk.chunk_seq > device.last_seq + 1:
                device.gap_pending = True
            self._recent[key] = now
            device.last_seq = chunk.chunk_seq
            device.last_chunk_monotonic = now
            device.chunks_accepted += 1
            return "accepted"

    def mark_gap(self, chunk: Chunk) -> None:
        """Record that an admitted chunk was discarded (stale or queue full)."""
        with self._lock:
            device = self._devices.get(chunk.device_id)
            if device is not None and device.active_stream_id == chunk.stream_id:
                device.gap_pending = True
                device.chunks_dropped += 1

    def take_gap(self, device_id, stream_id) -> bool:
        """Consume the discontinuity flag; the detection worker resets on True."""
        with self._lock:
            device = self._devices.get(device_id)
            if device is None or device.active_stream_id != stream_id:
                return False
            gapped = device.gap_pending
            device.gap_pending = False
            return gapped

    def device_state(self, device_id):
        with self._lock:
            device = self._devices.get(device_id)
            return None if device is None else replace(device)

    def aggregate_state(self, *, stale_after=HEARTBEAT_STALE_SECONDS):
        """Highest-priority capture state across devices; stale heartbeats stop."""
        priority = {"running": 3, "starting": 2, "error": 1, "stopped": 0}
        now = self._monotonic()
        with self._lock:
            if not self._devices:
                return "stopped"
            states = []
            for device in self._devices.values():
                heartbeat = device.last_heartbeat_monotonic
                fresh = heartbeat is not None and now - heartbeat <= stale_after
                states.append(device.state if fresh else "stopped")
            return max(states, key=lambda name: priority.get(name, 0))

    def _prune_recent(self, now):
        expiry = now - self._duplicate_ttl
        for key in [key for key, seen in self._recent.items() if seen < expiry]:
            del self._recent[key]


class ChunkQueue:
    """Bounded audio queue; the API rejects with 429 when full (plan 5.2)."""

    def __init__(self, capacity=QUEUE_CAPACITY, sink: Callable[[Chunk], None] | None = None):
        if capacity < 1:
            raise ValueError("capacity must be positive.")
        self._queue: queue.Queue[Chunk] = queue.Queue(maxsize=capacity)
        self._sink = sink
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.consumed = 0
        self.sink_errors = 0

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="audio-ingest", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def set_sink(self, sink: Callable[[Chunk], None] | None):
        self._sink = sink

    def qsize(self) -> int:
        return self._queue.qsize()

    def submit(self, chunk: Chunk) -> bool:
        try:
            self._queue.put_nowait(chunk)
            return True
        except queue.Full:
            return False

    def _run(self):
        while not self._stop.is_set():
            try:
                chunk = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                sink = self._sink
                if sink is not None:
                    sink(chunk)
            except Exception:
                self.sink_errors += 1
                logger.exception("Audio ingest sink failed")
            finally:
                self.consumed += 1
                self._queue.task_done()
