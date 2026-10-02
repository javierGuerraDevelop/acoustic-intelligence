from datetime import datetime, timezone
from threading import Event
import time
import uuid

from fastapi.testclient import TestClient

from analytics import AnalyticsError
from api import create_app


class FakeClassifier:
    def warm_up(self):
        pass

    def classify(self, audio, *, continuous=False):
        return None

    def reset_continuity(self):
        pass


class FakeAnalytics:
    def __init__(self, *, release=None):
        self.summary_calls = []
        self.delete_calls = 0
        self.summary_error = None
        self.delete_error = None
        self.release = release
        self.entered = Event()

    def summarize(self, lookback_minutes):
        self.summary_calls.append(lookback_minutes)
        self.entered.set()
        if self.release is not None:
            assert self.release.wait(5)
        if self.summary_error is not None:
            raise self.summary_error
        return {
            "text": "Two possible knocking detections in the window.",
            "event_count": 2,
            "counts": {"knock": 2},
            "since": "2026-09-27T11:30:00.000Z",
            "through": "2026-09-27T11:45:00.000Z",
            "generated_at": "2026-09-27T12:00:00.000Z",
            "model": "llama3.3-70b",
            "query_id": "query-1",
        }

    def delete_events(self):
        self.delete_calls += 1
        if self.delete_error is not None:
            raise self.delete_error


def summary_body(**overrides):
    body = {
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "lookback_minutes": 30,
    }
    body.update(overrides)
    return body


def delete_body(**overrides):
    body = {
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "scope": "all_history",
    }
    body.update(overrides)
    return body


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


def enable_analytics(client):
    response = client.patch("/v1/settings", json={
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "expected_revision": 1,
        "changes": {"cloud_storage_enabled": True, "analytics_enabled": True},
    })
    assert response.status_code == 200


def poll_job(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/v1/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["state"] in ("complete", "failed"):
            return job
        time.sleep(.01)
    raise AssertionError("job did not finish")


def make_app(tmp_path, analytics):
    return create_app(FakeClassifier, tmp_path / "events.sqlite3", analytics_service=analytics)


def seed_live_event(app, event_id="evt-1"):
    app.state.store.save_event({
        "schema_version": 1,
        "event_id": event_id,
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stream_id": "stream",
    }, kind="live")


def test_summary_requires_analytics_consent(tmp_path):
    analytics = FakeAnalytics()
    with TestClient(make_app(tmp_path, analytics)) as client:
        wait_ready(client)
        response = client.post("/v1/summary", json=summary_body())
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
        assert analytics.summary_calls == []


def test_summary_job_completes_and_publishes_changes(tmp_path):
    analytics = FakeAnalytics()
    with TestClient(make_app(tmp_path, analytics)) as client:
        wait_ready(client)
        instance = client.get("/v1/state").json()["instance_id"]
        enable_analytics(client)

        response = client.post("/v1/summary", json=summary_body())
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert response.json()["kind"] == "summary"
        assert response.json()["state"] in ("pending", "running")

        job = poll_job(client, job_id)
        assert job["state"] == "complete"
        assert job["error"] is None
        assert job["result"]["model"] == "llama3.3-70b"
        assert job["result"]["counts"] == {"knock": 2}
        assert job["result"]["event_count"] == 2
        assert analytics.summary_calls == [30]

        state = client.get(f"/v1/state?after=0&instance_id={instance}").json()
        job_changes = [change for change in state["changes"] if change["type"] == "job.changed"]
        assert job_changes
        assert job_changes[0]["data"]["job"]["job_id"] == job_id
        assert state["changes"][-1]["type"] == "job.changed"
        assert state["changes"][-1]["data"]["job"]["state"] == "complete"


def test_summary_duplicate_request_returns_same_job(tmp_path):
    analytics = FakeAnalytics()
    with TestClient(make_app(tmp_path, analytics)) as client:
        wait_ready(client)
        enable_analytics(client)
        body = summary_body()

        first = client.post("/v1/summary", json=body)
        second = client.post("/v1/summary", json=body)
        assert first.status_code == second.status_code == 202
        assert first.json()["job_id"] == second.json()["job_id"]

        assert poll_job(client, first.json()["job_id"])["state"] == "complete"
        assert len(analytics.summary_calls) == 1


def test_summary_is_single_flight_and_rate_limited(tmp_path):
    release = Event()
    analytics = FakeAnalytics(release=release)
    with TestClient(make_app(tmp_path, analytics)) as client:
        wait_ready(client)
        enable_analytics(client)

        first = client.post("/v1/summary", json=summary_body())
        assert first.status_code == 202
        try:
            assert analytics.entered.wait(5)
            in_flight = client.post("/v1/summary", json=summary_body())
            assert in_flight.status_code == 429
            assert in_flight.json()["error"]["code"] == "CAPACITY"
            assert in_flight.json()["error"]["retryable"] is True
        finally:
            release.set()

        assert poll_job(client, first.json()["job_id"])["state"] == "complete"
        limited = client.post("/v1/summary", json=summary_body())
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "CAPACITY"


def test_summary_reports_adapter_failure_without_provider_text(tmp_path):
    analytics = FakeAnalytics()
    analytics.summary_error = AnalyticsError("TIMEOUT", True, "Snowflake analytics request failed.")
    with TestClient(make_app(tmp_path, analytics)) as client:
        wait_ready(client)
        enable_analytics(client)

        response = client.post("/v1/summary", json=summary_body())
        assert response.status_code == 202
        job = poll_job(client, response.json()["job_id"])
        assert job["state"] == "failed"
        assert job["result"] is None
        assert job["error"] == {
            "code": "TIMEOUT",
            "retryable": True,
            "message": "Snowflake analytics request failed.",
        }


def test_summary_without_snowflake_configuration_fails_cleanly(tmp_path):
    app = create_app(FakeClassifier, tmp_path / "events.sqlite3", analytics_service=False)
    with TestClient(app) as client:
        wait_ready(client)
        enable_analytics(client)

        response = client.post("/v1/summary", json=summary_body())
        assert response.status_code == 202
        job = poll_job(client, response.json()["job_id"])
        assert job["state"] == "failed"
        assert job["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert job["error"]["retryable"] is True


def test_summary_and_delete_validate_payloads(tmp_path):
    with TestClient(make_app(tmp_path, FakeAnalytics())) as client:
        wait_ready(client)
        for lookback in (0, 4, 61, -5):
            response = client.post("/v1/summary", json=summary_body(lookback_minutes=lookback))
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "SCHEMA_INVALID"
        assert client.post("/v1/summary", json=summary_body(lookback_minutes=[30])).status_code == 422
        assert client.post("/v1/summary", json=summary_body(extra=True)).status_code == 422
        assert client.post("/v1/privacy/delete", json=delete_body(scope="event")).status_code == 422
        assert client.post("/v1/privacy/delete", json=delete_body(request_id="not-a-uuid")).status_code == 422


def test_delete_clears_history_and_disables_external_permissions(tmp_path):
    analytics = FakeAnalytics()
    app = make_app(tmp_path, analytics)
    with TestClient(app) as client:
        wait_ready(client)
        seed_live_event(app)
        enable_analytics(client)
        settings = client.get("/v1/settings").json()
        speech = client.patch("/v1/settings", json={
            "schema_version": 1,
            "request_id": str(uuid.uuid4()),
            "expected_revision": settings["revision"],
            "changes": {"speech_enabled": True},
        })
        assert speech.status_code == 200
        assert client.get("/v1/events").json()["items"]

        instance = client.get("/v1/state").json()["instance_id"]
        policy_before = app.state.device.policy_epoch()

        response = client.post("/v1/privacy/delete", json=delete_body())
        assert response.status_code == 202
        assert response.json()["kind"] == "delete"

        job = poll_job(client, response.json()["job_id"])
        assert job["state"] == "complete"
        assert job["result"] == {"local": "complete", "atlas": "complete", "snowflake": "complete"}
        assert job["error"] is None
        assert analytics.delete_calls == 1

        assert client.get("/v1/events").json()["items"] == []
        assert app.state.store.get_events() == []
        settings = client.get("/v1/settings").json()
        assert settings["cloud_storage_enabled"] is False
        assert settings["analytics_enabled"] is False
        assert settings["speech_enabled"] is False
        assert app.state.device.policy_epoch() == policy_before + 1

        state = client.get(f"/v1/state?after=0&instance_id={instance}").json()
        types = [change["type"] for change in state["changes"]]
        assert "settings.changed" in types
        assert "history.cleared" in types


def test_delete_duplicate_request_returns_same_job(tmp_path):
    analytics = FakeAnalytics()
    app = make_app(tmp_path, analytics)
    with TestClient(app) as client:
        wait_ready(client)
        seed_live_event(app)
        body = delete_body()

        first = client.post("/v1/privacy/delete", json=body)
        second = client.post("/v1/privacy/delete", json=body)
        assert first.status_code == second.status_code == 202
        assert first.json()["job_id"] == second.json()["job_id"]

        assert poll_job(client, first.json()["job_id"])["state"] == "complete"
        assert analytics.delete_calls == 1
        assert app.state.store.get_events() == []


def test_delete_keeps_local_complete_when_remote_deletion_fails(tmp_path):
    analytics = FakeAnalytics()
    analytics.delete_error = AnalyticsError("UNAVAILABLE", True, "Snowflake analytics is unavailable.")
    app = make_app(tmp_path, analytics)
    with TestClient(app) as client:
        wait_ready(client)
        seed_live_event(app)

        response = client.post("/v1/privacy/delete", json=delete_body())
        job = poll_job(client, response.json()["job_id"])
        assert job["state"] == "failed"
        assert job["error"]["code"] == "UNAVAILABLE"
        assert job["result"] == {"local": "complete", "atlas": "complete", "snowflake": "pending"}
        assert app.state.store.get_events() == []


def test_request_id_cannot_be_reused_for_another_job_kind(tmp_path):
    with TestClient(make_app(tmp_path, FakeAnalytics())) as client:
        wait_ready(client)
        enable_analytics(client)
        body = summary_body()
        assert client.post("/v1/summary", json=body).status_code == 202
        conflict = client.post("/v1/privacy/delete", json=delete_body(request_id=body["request_id"]))
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "CONFLICT"


def test_unknown_and_invalid_job_ids(tmp_path):
    with TestClient(make_app(tmp_path, FakeAnalytics())) as client:
        wait_ready(client)
        assert client.get(f"/v1/jobs/{uuid.uuid4()}").status_code == 404
        assert client.get("/v1/jobs/not-a-uuid").status_code == 422
