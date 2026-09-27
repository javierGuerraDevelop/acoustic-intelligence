from datetime import datetime, timezone
import json
import subprocess
import sys

import pytest

from storage import EventStore


def event(event_id="one", timestamp=1000000):
    return {"event_id": event_id, "processed_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), "label": "knock"}


def test_history_survives_new_process(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = EventStore(path, clock=lambda: 1000000)
    store.save_event(event())
    code = "from storage import EventStore; import json,sys; print(json.dumps(EventStore(sys.argv[1], clock=lambda: 1000000).get_events()))"
    output = subprocess.check_output([sys.executable, "-B", "-c", code, str(path)], text=True)
    assert json.loads(output) == [event()]


def test_expired_events_hidden_and_removed(tmp_path):
    now = [1000000]
    store = EventStore(tmp_path / "events.sqlite3", clock=lambda: now[0])
    store.save_event(event())
    now[0] += 86400
    assert store.get_events() == []
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_bounded_history_orders_by_event_time_and_deduplicates(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3", max_events=3, clock=lambda: 1000010)
    for i in [3, 1, 2, 0]:
        store.save_event(event(str(i), 1000000 + i))
    store.save_event(event("3", 1000003))
    assert [e["event_id"] for e in store.get_events()] == ["3", "2", "1"]
    with pytest.raises(ValueError, match="different content"):
        store.save_event({**event("3", 1000003), "label": "doorbell"})
    assert store.get_events()[0]["label"] == "knock"


def test_extending_retention_does_not_extend_existing_events(tmp_path):
    path = tmp_path / "events.sqlite3"
    EventStore(path, clock=lambda: 1000000).save_event(event())
    assert EventStore(path, retention_days=7, clock=lambda: 1000000 + 86400).get_events() == []


def test_shortening_retention_applies_to_existing_events(tmp_path):
    path = tmp_path / "events.sqlite3"
    EventStore(path, retention_days=7, clock=lambda: 1000000).save_event(event())
    assert EventStore(path, retention_days=1, clock=lambda: 1000000 + 86400).get_events() == []
