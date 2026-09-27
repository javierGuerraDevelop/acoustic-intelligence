from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from api import create_app

DEVICE_ID = "70c4af1d-9b7c-4c28-a66c-a87489376e42"
STREAM_ID = "fa986755-08b7-4bb2-b324-f5d17243539c"
TOKEN = "state-token"


class AlwaysKnockClassifier:
    def warm_up(self):
        pass

    def classify(self, audio, *, continuous=False):
        return {"label": "knock", "score": 0.8}

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


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def chunk_headers(seq):
    captured_at = datetime.now(timezone.utc)
    return {
        "Content-Type": "application/octet-stream",
        "Authorization": f"Bearer {TOKEN}",
        "X-Schema-Version": "1",
        "X-Device-Id": DEVICE_ID,
        "X-Stream-Id": STREAM_ID,
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


def heartbeat_body():
    return {
        "schema_version": 1,
        "device_id": DEVICE_ID,
        "stream_id": STREAM_ID,
        "state": "running",
        "native_rate_hz": 48000,
        "dropped_frames_total": 0,
        "error_code": None,
    }


def request_body(**changes):
    return {
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "expected_revision": changes.pop("expected_revision"),
        "changes": changes,
    }


def test_live_state_history_acknowledgement_and_settings(tmp_path):
    app = create_app(AlwaysKnockClassifier, tmp_path / "events.sqlite3", capture_token=TOKEN)
    with TestClient(app) as client:
        wait_ready(client)

        initial = client.get("/v1/state").json()
        assert initial["schema_version"] == 1
        assert initial["reset_required"] is True
        assert initial["changes"] == []
        assert initial["status"] == {
            "capture": "stopped",
            "model": "ready",
            "cloud": "disabled",
            "export_pending": 0,
            "export_dropped": 0,
            "audio_gaps": 0,
        }
        instance = initial["instance_id"]
        cursor = initial["cursor"]

        assert client.post("/v1/capture/heartbeat", json=heartbeat_body(),
                           headers=auth()).status_code == 200
        for seq in (0, 1):
            response = client.post("/v1/audio/chunks", content=b"\x00" * 32000,
                                   headers=chunk_headers(seq))
            assert response.status_code == 202

        deadline = time.monotonic() + 5
        payload = None
        while time.monotonic() < deadline:
            payload = client.get(f"/v1/state?after={cursor}&instance_id={instance}").json()
            if any(change["type"] == "event.created" for change in payload["changes"]):
                break
            time.sleep(.02)

        created = [change for change in payload["changes"] if change["type"] == "event.created"]
        assert created, "no event.created change observed"
        assert payload["reset_required"] is False
        assert payload["status"]["capture"] == "running"
        event = created[0]["data"]["event"]
        event_id = event["event_id"]
        assert created[0]["event_id"] == event_id
        assert event["processing"]["window_ms"] == 2000

        history = client.get("/v1/events?limit=50").json()
        assert history["schema_version"] == 1
        assert history["items"][0]["event"]["event_id"] == event_id
        assert history["items"][0]["acknowledged_at"] is None
        assert client.get("/v1/events?limit=0").status_code == 422
        assert client.get("/v1/events?before=not-a-cursor").status_code == 422

        ack = client.post(f"/v1/events/{event_id}/ack",
                          json={"schema_version": 1, "request_id": str(uuid.uuid4())})
        assert ack.status_code == 200
        acknowledged_at = ack.json()["acknowledged_at"]
        repeat = client.post(f"/v1/events/{event_id}/ack",
                             json={"schema_version": 1, "request_id": str(uuid.uuid4())})
        assert repeat.status_code == 200
        assert repeat.json()["acknowledged_at"] == acknowledged_at
        missing = client.post(f"/v1/events/{uuid.uuid4()}/ack",
                              json={"schema_version": 1, "request_id": str(uuid.uuid4())})
        assert missing.status_code == 404

        acked_state = client.get(
            f"/v1/state?after={created[0]['cursor']}&instance_id={instance}"
        ).json()
        assert [change["type"] for change in acked_state["changes"]] == ["event.acknowledged"]

        settings = client.get("/v1/settings").json()
        assert settings == {
            "schema_version": 1,
            "revision": 1,
            "capture_enabled": False,
            "cloud_storage_enabled": False,
            "analytics_enabled": False,
            "speech_enabled": False,
            "retention_days": 1,
            "cooldown_seconds": 10,
            "muted_until": None,
        }

        patched = client.patch("/v1/settings", json=request_body(
            expected_revision=1, capture_enabled=True))
        assert patched.status_code == 200
        assert patched.json()["revision"] == 2
        assert patched.json()["capture_enabled"] is True
        assert patched.json()["cloud_sync"] == "not_needed"

        stale = client.patch("/v1/settings", json=request_body(
            expected_revision=1, speech_enabled=True))
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "CONFLICT"

        illegal = client.patch("/v1/settings", json=request_body(
            expected_revision=2, analytics_enabled=True))
        assert illegal.status_code == 422
        assert illegal.json()["error"]["code"] == "SCHEMA_INVALID"

        consent = client.patch("/v1/settings", json=request_body(
            expected_revision=2, cloud_storage_enabled=True))
        assert consent.status_code == 200
        assert consent.json()["cloud_sync"] == "pending"

        consent = client.patch("/v1/settings", json=request_body(
            expected_revision=3, analytics_enabled=True))
        assert consent.status_code == 200

        unknown = client.patch("/v1/settings", json=request_body(
            expected_revision=4, bogus=True))
        assert unknown.status_code == 422

        too_far = client.patch("/v1/settings", json=request_body(
            expected_revision=4,
            muted_until=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()))
        assert too_far.status_code == 422

        allowed = client.patch("/v1/settings", json=request_body(
            expected_revision=4,
            muted_until=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()))
        assert allowed.status_code == 200
        assert allowed.json()["muted_until"] is not None

        cloud_state = client.get(
            f"/v1/state?after={acked_state['cursor']}&instance_id={instance}"
        ).json()
        assert cloud_state["status"]["cloud"] == "offline"
        assert any(change["type"] == "settings.changed" for change in cloud_state["changes"])


def test_built_dashboard_is_served_at_the_root(tmp_path):
    dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    if not dist.is_dir():
        pytest.skip("web/dist is not built")
    app = create_app(AlwaysKnockClassifier, tmp_path / "events.sqlite3")
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
