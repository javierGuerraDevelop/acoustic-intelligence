from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from analytics import AnalyticsError, AnalyticsService


@dataclass(frozen=True)
class FakeSummary:
    text: str = "Two possible knocking detections in the window."
    event_count: int = 2
    counts: dict = None
    since: str = ""
    through: str = ""
    generated_at: str = ""
    model: str | None = "llama3.3-70b"
    query_id: str | None = "query-1"

    def __post_init__(self):
        object.__setattr__(self, "counts", {"knock": 2})


class FakeAdapter:
    def __init__(self):
        self.summarize_args = None
        self.deleted = []

    def summarize(self, device_key, since_utc):
        self.summarize_args = (device_key, since_utc)
        return FakeSummary()

    def delete_events(self, device_key):
        self.deleted.append(device_key)


def test_summarize_uses_device_key_and_lookback_window():
    fixed = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    adapter = FakeAdapter()
    service = AnalyticsService(adapter, "device-1", now=lambda: fixed)
    result = service.summarize(30)
    assert adapter.summarize_args == ("device-1", "2026-09-27T11:30:00.000Z")
    assert result["event_count"] == 2
    assert result["counts"] == {"knock": 2}
    assert result["model"] == "llama3.3-70b"


def test_adapter_errors_are_sanitized():
    class BrokenAdapter:
        def summarize(self, device_key, since_utc):
            from cloud.analytics.errors import AdapterError
            raise AdapterError("RATE_LIMITED", True)

    service = AnalyticsService(BrokenAdapter(), "device-1")
    with pytest.raises(AnalyticsError) as error:
        service.summarize(30)
    assert error.value.code == "RATE_LIMITED"
    assert error.value.retryable is True
    assert str(error.value) == "Snowflake analytics request failed."


def test_unexpected_errors_map_to_unavailable():
    class BrokenAdapter:
        def delete_events(self, device_key):
            raise RuntimeError("provider detail that must not leak")

    service = AnalyticsService(BrokenAdapter(), "device-1")
    with pytest.raises(AnalyticsError) as error:
        service.delete_events()
    assert error.value.code == "UNAVAILABLE"
    assert error.value.retryable is True
    assert "provider" not in str(error.value)


def test_delete_events_targets_the_device_key():
    adapter = FakeAdapter()
    AnalyticsService(adapter, "device-1").delete_events()
    assert adapter.deleted == ["device-1"]


def test_from_env_without_credentials_returns_none(monkeypatch):
    for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_B64", "SNOWFLAKE_PRIVATE_KEY_PATH"):
        monkeypatch.delenv(name, raising=False)
    assert AnalyticsService.from_env("device-1") is None
