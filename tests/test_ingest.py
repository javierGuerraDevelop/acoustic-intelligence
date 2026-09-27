from datetime import datetime, timedelta, timezone
from threading import Event
import time
import uuid

from fastapi.testclient import TestClient

from api import create_app
from ingest import (
    CHUNK_BYTES,
    CaptureRegistry,
    Chunk,
    ChunkQueue,
    IngestError,
    parse_chunk,
)
from storage import SettingsStore

DEVICE_ID = "70c4af1d-9b7c-4c28-a66c-a87489376e42"
STREAM_ID = "fa986755-08b7-4bb2-b324-f5d17243539c"
NEW_STREAM_ID = "11111111-2222-4333-8444-555555555555"
TOKEN = "edge-one-token"


class FakeClassifier:
    def warm_up(self):
        pass

    def classify(self, audio):
        return {"label": "knock", "score": 0.9}


def wait_ready(client):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get("/health/ready")
        if response.status_code == 200:
            return
        if response.json()["status"] == "error":
            raise AssertionError(response.text)
        time.sleep(.01)
    raise AssertionError("Model did not become ready")


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def chunk_headers(seq=0, *, stream_id=STREAM_ID, device_id=DEVICE_ID, captured_at=None, **overrides):
    if captured_at is None:
        captured_at = datetime.now(timezone.utc)
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Schema-Version": "1",
        "X-Device-Id": device_id,
        "X-Stream-Id": stream_id,
        "X-Chunk-Seq": str(seq),
        "X-Start-Sample": str(seq * 16000),
        "X-Captured-At": captured_at.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{captured_at.microsecond // 1000:03d}Z",
        "X-Sample-Rate": "16000",
        "X-Channels": "1",
        "X-Encoding": "pcm_s16le",
        "X-Rms-Dbfs": "-20.0",
        "X-Dropped-Frames-Total": "0",
    }
    headers.update(overrides)
    return headers


def heartbeat_body(stream_id=STREAM_ID, state="running", **overrides):
    body = {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "stream_id": stream_id,
        "state": state,
        "native_rate_hz": 48000 if state == "running" else None,
        "dropped_frames_total": 0,
        "error_code": None,
    }
    body.update(overrides)
    return body


def make_chunk(seq, *, stream_id=STREAM_ID, device_id=DEVICE_ID, monotonic=0.0):
    return Chunk(
        device_id=device_id,
        stream_id=stream_id,
        chunk_seq=seq,
        start_sample=seq * 16000,
        captured_at=datetime.now(timezone.utc),
        pcm=b"\x00" * CHUNK_BYTES,
        rms_dbfs=-20.0,
        dropped_frames_total=0,
        received_monotonic=monotonic,
    )


def open_app(tmp_path, classifier=FakeClassifier):
    return create_app(classifier, tmp_path / "events.sqlite3", capture_token=TOKEN)


def test_capture_token_required_when_configured(tmp_path):
    app = open_app(tmp_path)
    with TestClient(app) as client:
        wait_ready(client)
        stopped = heartbeat_body(stream_id=None, state="stopped")
        assert client.post("/v1/capture/heartbeat", json=stopped).status_code == 401
        assert client.post("/v1/audio/chunks", content=b"\x00" * CHUNK_BYTES,
                           headers=chunk_headers(0)).status_code == 401


def test_capture_token_disabled_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPTURE_TOKEN", raising=False)
    app = create_app(FakeClassifier, tmp_path / "events.sqlite3")
    with TestClient(app) as client:
        wait_ready(client)
        response = client.post("/v1/capture/heartbeat",
                               json=heartbeat_body(stream_id=None, state="stopped"))
        assert response.status_code == 200


def test_heartbeat_authorizes_capture_from_settings(tmp_path):
    app = open_app(tmp_path)
    with TestClient(app) as client:
        wait_ready(client)
        stopped = heartbeat_body(stream_id=None, state="stopped")
        response = client.post("/v1/capture/heartbeat", json=stopped, headers=auth())
        assert response.status_code == 200
        assert response.json() == {
            "schema_version": 1,
            "desired_capture": False,
            "lease_ms": 2000,
            "settings_revision": 1,
        }

        app.state.settings_store.set_capture_enabled(True)
        response = client.post("/v1/capture/heartbeat", json=heartbeat_body(), headers=auth())
        assert response.json()["desired_capture"] is True
        assert response.json()["settings_revision"] == 2


def test_heartbeat_rejects_unknown_fields_and_bad_values(tmp_path):
    app = open_app(tmp_path)
    with TestClient(app) as client:
        wait_ready(client)
        body = heartbeat_body(stream_id=None, state="stopped")
        body["unexpected"] = 1
        response = client.post("/v1/capture/heartbeat", json=body, headers=auth())
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "SCHEMA_INVALID"
        assert response.json()["schema_version"] == 1
        assert response.json()["request_id"]

        bad_state = heartbeat_body(stream_id=None, state="dancing")
        assert client.post("/v1/capture/heartbeat", json=bad_state, headers=auth()).status_code == 422

        bad_device = heartbeat_body(stream_id=None, state="stopped", device_id="not-a-uuid")
        assert client.post("/v1/capture/heartbeat", json=bad_device, headers=auth()).status_code == 422


def test_chunks_require_registered_stream_then_enforce_sequence_rules(tmp_path):
    app = open_app(tmp_path)
    with TestClient(app) as client:
        wait_ready(client)
        chunk = b"\x00" * CHUNK_BYTES
        response = client.post("/v1/audio/chunks", content=chunk,
                               headers=auth() | chunk_headers(0))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STREAM_CONFLICT"

        assert client.post("/v1/capture/heartbeat", json=heartbeat_body(),
                           headers=auth()).status_code == 200

        response = client.post("/v1/audio/chunks", content=chunk,
                               headers=auth() | chunk_headers(0))
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        assert response.json()["stream_id"] == STREAM_ID

        response = client.post("/v1/audio/chunks", content=chunk,
                               headers=auth() | chunk_headers(0))
        assert response.status_code == 200
        assert response.json()["status"] == "duplicate"

        response = client.post("/v1/audio/chunks", content=chunk,
                               headers=auth() | chunk_headers(2))
        assert response.status_code == 202
        deadline = time.monotonic() + 5
        while app.state.pipeline.audio_gaps == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        assert app.state.pipeline.audio_gaps == 1

        response = client.post("/v1/audio/chunks", content=chunk,
                               headers=auth() | chunk_headers(1))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "OUT_OF_ORDER"


def test_chunk_device_must_match_the_registered_device(tmp_path):
    app = open_app(tmp_path)
    with TestClient(app) as client:
        wait_ready(client)
        assert client.post("/v1/capture/heartbeat", json=heartbeat_body(),
                           headers=auth()).status_code == 200
        other = str(uuid.uuid4())
        response = client.post("/v1/audio/chunks", content=b"\x00" * CHUNK_BYTES,
                               headers=auth() | chunk_headers(0, device_id=other))
        assert response.status_code == 409


def test_chunk_body_and_header_validation(tmp_path):
    app = open_app(tmp_path)
    with TestClient(app) as client:
        wait_ready(client)
        assert client.post("/v1/capture/heartbeat", json=heartbeat_body(),
                           headers=auth()).status_code == 200
        chunk = b"\x00" * CHUNK_BYTES

        wrong_type = auth() | chunk_headers(0)
        wrong_type["Content-Type"] = "application/json"
        assert client.post("/v1/audio/chunks", content=chunk, headers=wrong_type).status_code == 415

        assert client.post("/v1/audio/chunks", content=b"\x00" * 10,
                           headers=auth() | chunk_headers(0)).status_code == 413
        assert client.post("/v1/audio/chunks", content=chunk + b"\x00",
                           headers=auth() | chunk_headers(0)).status_code == 413

        cases = [
            {"X-Start-Sample": "16000"},
            {"X-Rms-Dbfs": "0.5"},
            {"X-Schema-Version": "2"},
            {"X-Sample-Rate": "48000"},
            {"X-Channels": "2"},
            {"X-Encoding": "pcm_f32le"},
            {"X-Chunk-Seq": "-1"},
            {"X-Stream-Id": "not-a-uuid"},
            {"X-Captured-At": "yesterday"},
        ]
        for override in cases:
            response = client.post("/v1/audio/chunks", content=chunk,
                                   headers=auth() | chunk_headers(0, **override))
            assert response.status_code == 422, override
            assert response.json()["error"]["code"] == "SCHEMA_INVALID"

        # Failed validation must not consume the sequence number.
        assert client.post("/v1/audio/chunks", content=chunk,
                           headers=auth() | chunk_headers(0)).status_code == 202


def test_stale_chunk_is_accepted_but_not_queued(tmp_path):
    app = open_app(tmp_path)
    with TestClient(app) as client:
        wait_ready(client)
        assert client.post("/v1/capture/heartbeat", json=heartbeat_body(),
                           headers=auth()).status_code == 200
        stale = datetime.now(timezone.utc) - timedelta(seconds=10)
        response = client.post("/v1/audio/chunks", content=b"\x00" * CHUNK_BYTES,
                               headers=auth() | chunk_headers(0, captured_at=stale))
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        state = app.state.registry.device_state(DEVICE_ID)
        assert state.gap_pending is True
        assert state.chunks_dropped == 1
        assert app.state.audio_queue.qsize() == 0


def test_chunks_reject_while_model_loads(tmp_path):
    release = Event()

    class SlowClassifier(FakeClassifier):
        def warm_up(self):
            assert release.wait(5)

    app = open_app(tmp_path, SlowClassifier)
    with TestClient(app) as client:
        try:
            response = client.post("/v1/audio/chunks", content=b"\x00" * CHUNK_BYTES,
                                   headers=auth() | chunk_headers(0))
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "MODEL_NOT_READY"
            assert response.json()["error"]["retryable"] is True
        finally:
            release.set()


def test_queue_is_bounded_at_two_chunks():
    queue = ChunkQueue(capacity=2)
    assert queue.submit(make_chunk(0))
    assert queue.submit(make_chunk(1))
    assert queue.submit(make_chunk(2)) is False


def test_worker_consumes_without_a_sink():
    queue = ChunkQueue(capacity=2)
    queue.start()
    try:
        assert queue.submit(make_chunk(0))
        deadline = time.monotonic() + 5
        while queue.consumed == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        assert queue.consumed == 1
    finally:
        queue.stop()


def test_duplicate_cache_honors_ttl_and_stream_retirement():
    clock = [1000.0]
    registry = CaptureRegistry(monotonic=lambda: clock[0])
    registry.record_heartbeat(device_id=DEVICE_ID, stream_id=STREAM_ID, state="running",
                              native_rate_hz=48000, dropped_frames_total=0, error_code=None)
    assert registry.admit(make_chunk(0, monotonic=clock[0])) == "accepted"
    assert registry.admit(make_chunk(0, monotonic=clock[0] + 1)) == "duplicate"

    # A new stream retires the old one; unseen old-stream chunks are rejected.
    registry.record_heartbeat(device_id=DEVICE_ID, stream_id=NEW_STREAM_ID, state="running",
                              native_rate_hz=48000, dropped_frames_total=0, error_code=None)
    try:
        registry.admit(make_chunk(1, stream_id=STREAM_ID, monotonic=clock[0] + 2))
        raise AssertionError("retired stream was accepted")
    except IngestError as error:
        assert error.code == "STREAM_CONFLICT"

    clock[0] += 61
    assert registry.admit(make_chunk(0, stream_id=NEW_STREAM_ID, monotonic=clock[0])) == "accepted"


def test_parse_chunk_rejects_malformed_headers():
    chunk = b"\x00" * CHUNK_BYTES
    with_errors = [
        (chunk_headers(1, **{"X-Start-Sample": "0"}), 422),
        (chunk_headers(0, **{"X-Rms-Dbfs": "nan"}), 422),
        (chunk_headers(0), 413),
    ]
    for headers, status in with_errors:
        body = chunk if status == 422 else chunk[:-1]
        try:
            parse_chunk(headers, body)
            raise AssertionError(f"accepted invalid chunk {headers}")
        except IngestError as error:
            assert error.status_code == status


def test_registry_state_is_stale_after_heartbeat_silence():
    clock = [100.0]
    registry = CaptureRegistry(monotonic=lambda: clock[0])
    registry.record_heartbeat(device_id=DEVICE_ID, stream_id=STREAM_ID, state="running",
                              native_rate_hz=48000, dropped_frames_total=0, error_code=None)
    assert registry.aggregate_state() == "running"
    clock[0] += 10
    assert registry.aggregate_state() == "stopped"


def test_settings_capture_resets_on_launch(tmp_path):
    path = tmp_path / "settings.sqlite3"
    store = SettingsStore(path)
    initial = store.get()
    assert initial.capture_enabled is False
    assert initial.retention_days == 1
    assert initial.cooldown_seconds == 10

    store.set_capture_enabled(True)
    assert store.get().capture_enabled is True
    revision = store.get().revision

    reopened = SettingsStore(path)
    assert reopened.get().capture_enabled is False
    assert reopened.get().revision == revision
