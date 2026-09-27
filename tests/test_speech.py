from datetime import datetime, timedelta, timezone
import time
import uuid

import httpx
from fastapi.testclient import TestClient

from api import create_app
from playback import PlaybackRegistry
from speech import SpeechService

MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
DEVICE_ID = "70c4af1d-9b7c-4c28-a66c-a87489376e42"
STREAM_ID = "fa986755-08b7-4bb2-b324-f5d17243539c"


class FakeClassifier:
    def warm_up(self):
        pass

    def classify(self, audio, *, continuous=False):
        return None

    def reset_continuity(self):
        pass


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


def request_body(event_id, **extra):
    body = {
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "event_id": event_id,
    }
    body.update(extra)
    return body


def live_event(label="knock", *, occurred_at=None, event_id=None):
    occurred = (occurred_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "schema_version": 1,
        "event_id": event_id or str(uuid.uuid4()),
        "device_id": DEVICE_ID,
        "stream_id": STREAM_ID,
        "event_seq": 1,
        "window_start_at": (occurred - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        "occurred_at": occurred.isoformat().replace("+00:00", "Z"),
        "detected_at": (occurred + timedelta(milliseconds=150)).isoformat().replace("+00:00", "Z"),
        "label": label,
        "model_score": 0.8,
        "severity": "info" if label == "knock" else "attention",
        "action_id": "check_door",
        "source": "microphone",
        "processing": {
            "model_id": "yamnet/1",
            "rule_version": "demo-1",
            "sample_rate_hz": 16000,
            "window_ms": 2000,
            "hop_ms": 1000,
            "last_chunk_seq": 1,
            "inference_ms": 20,
            "capture_to_detection_ms": 150,
            "rms_dbfs": -22.0,
            "dropped_frames_total": 0,
        },
    }


def make_app(tmp_path, *, speech=None, playback=None):
    return create_app(
        FakeClassifier,
        tmp_path / "events.sqlite3",
        capture_token="speech-token",
        speech_service=speech,
        playback_registry=playback,
    )


def enable_speech(client):
    response = client.patch("/v1/settings", json={
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "expected_revision": 1,
        "changes": {"speech_enabled": True},
    })
    assert response.status_code == 200


def test_speech_requires_consent_and_recent_known_event(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=MP3_BYTES)

    service = SpeechService(api_key="key", voice_id="voice", transport=httpx.MockTransport(handler))
    app = make_app(tmp_path, speech=service)
    with TestClient(app) as client:
        wait_ready(client)
        event = live_event()
        app.state.store.save_event(event, kind="live")

        assert client.post("/v1/speech", json=request_body(event["event_id"])).status_code == 403

        enable_speech(client)
        unknown = client.post("/v1/speech", json=request_body(str(uuid.uuid4())))
        assert unknown.status_code == 404

        stale = live_event(occurred_at=datetime.now(timezone.utc) - timedelta(minutes=10))
        app.state.store.save_event(stale, kind="live")
        assert client.post("/v1/speech", json=request_body(stale["event_id"])).status_code == 409

        response = client.post("/v1/speech", json=request_body(event["event_id"]))
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/mpeg")
        assert response.headers["cache-control"] == "no-store"
        assert response.content == MP3_BYTES
        assert len(calls) == 1


def test_speech_caches_generated_templates_in_memory(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=MP3_BYTES)

    service = SpeechService(api_key="key", voice_id="voice", transport=httpx.MockTransport(handler))
    app = make_app(tmp_path, speech=service)
    with TestClient(app) as client:
        wait_ready(client)
        enable_speech(client)
        event = live_event()
        app.state.store.save_event(event, kind="live")

        first = client.post("/v1/speech", json=request_body(event["event_id"]))
        assert first.status_code == 200
        assert "x-speech-cached" not in first.headers

        second = client.post("/v1/speech", json=request_body(event["event_id"]))
        assert second.status_code == 200
        assert second.headers["x-speech-cached"] == "true"
        assert second.content == MP3_BYTES
        assert len(calls) == 1


def test_speech_reports_unavailable_without_credentials(tmp_path):
    app = make_app(tmp_path, speech=SpeechService())
    with TestClient(app) as client:
        wait_ready(client)
        enable_speech(client)
        event = live_event()
        app.state.store.save_event(event, kind="live")

        response = client.post("/v1/speech", json=request_body(event["event_id"]))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SPEECH_UNAVAILABLE"
        assert response.json()["error"]["retryable"] is True


def test_speech_maps_provider_failures_to_unavailable(tmp_path):
    def handler(request):
        return httpx.Response(500, content=b"provider error")

    service = SpeechService(api_key="key", voice_id="voice", transport=httpx.MockTransport(handler))
    app = make_app(tmp_path, speech=service)
    with TestClient(app) as client:
        wait_ready(client)
        enable_speech(client)
        event = live_event()
        app.state.store.save_event(event, kind="live")

        response = client.post("/v1/speech", json=request_body(event["event_id"]))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SPEECH_UNAVAILABLE"


def test_playback_lease_conflict_and_grace(tmp_path):
    clock = [100.0]
    playback = PlaybackRegistry(monotonic=lambda: clock[0])
    app = make_app(tmp_path, playback=playback)
    with TestClient(app) as client:
        wait_ready(client)
        first_id = str(uuid.uuid4())

        started = client.post("/v1/playback", json={
            "schema_version": 1, "request_id": str(uuid.uuid4()),
            "state": "started", "playback_id": first_id,
        })
        assert started.status_code == 200
        assert playback.suppressing() is True

        conflict = client.post("/v1/playback", json={
            "schema_version": 1, "request_id": str(uuid.uuid4()),
            "state": "started", "playback_id": str(uuid.uuid4()),
        })
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "CONFLICT"

        ended = client.post("/v1/playback", json={
            "schema_version": 1, "request_id": str(uuid.uuid4()),
            "state": "ended", "playback_id": first_id,
        })
        assert ended.status_code == 200
        assert playback.suppressing() is True  # two-second grace window

        clock[0] += 3.0
        assert playback.suppressing() is False
