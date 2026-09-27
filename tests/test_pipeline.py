from datetime import datetime, timedelta, timezone

import pytest

from changes import ChangeBuffer
from ingest import CaptureRegistry, Chunk
from pipeline import DetectionPipeline
from playback import PlaybackRegistry
from storage import EventStore

DEVICE_ID = "70c4af1d-9b7c-4c28-a66c-a87489376e42"
STREAM_ID = "fa986755-08b7-4bb2-b324-f5d17243539c"
NEW_STREAM_ID = "11111111-2222-4333-8444-555555555555"
START = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


class ScriptedClassifier:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.resets = 0

    def reset_continuity(self):
        self.resets += 1

    def classify(self, audio, *, continuous=False):
        self.calls.append({"samples": int(audio.size), "continuous": continuous})
        if not self.results:
            return None
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_chunk(seq, *, stream_id=STREAM_ID, device_id=DEVICE_ID):
    return Chunk(
        device_id=device_id,
        stream_id=stream_id,
        chunk_seq=seq,
        start_sample=seq * 16000,
        captured_at=START + timedelta(seconds=seq),
        pcm=b"\x00\x10" * 16000,
        rms_dbfs=-20.0,
        dropped_frames_total=0,
        received_monotonic=0.0,
    )


def build(tmp_path, classifier, playback=None):
    store = EventStore(tmp_path / "events.sqlite3")
    changes = ChangeBuffer()
    registry = CaptureRegistry()
    registry.record_heartbeat(device_id=DEVICE_ID, stream_id=STREAM_ID, state="running",
                              native_rate_hz=48000, dropped_frames_total=0, error_code=None)
    pipeline = DetectionPipeline(lambda: classifier, store, changes, registry, playback)
    return pipeline, store, changes, registry


def changes_from(buffer):
    payload, _, _ = buffer.poll(0, buffer.instance_id)
    return payload


def test_pipeline_emits_one_canonical_event_per_detection(tmp_path):
    classifier = ScriptedClassifier([{"label": "knock", "score": 0.8}])
    pipeline, store, changes, _ = build(tmp_path, classifier)

    pipeline.handle_chunk(make_chunk(0))
    assert classifier.calls == []
    pipeline.handle_chunk(make_chunk(1))

    assert classifier.calls == [{"samples": 32000, "continuous": True}]
    payload = changes_from(changes)
    assert len(payload) == 1
    change = payload[0]
    assert change["type"] == "event.created"

    event = change["data"]["event"]
    assert change["event_id"] == event["event_id"]
    assert event["schema_version"] == 1
    assert event["device_id"] == DEVICE_ID
    assert event["stream_id"] == STREAM_ID
    assert event["event_seq"] == 1
    assert event["label"] == "knock"
    assert event["severity"] == "info"
    assert event["action_id"] == "check_door"
    assert event["source"] == "microphone"
    assert event["window_start_at"] == "2026-09-27T12:00:00.000Z"
    assert event["occurred_at"] == "2026-09-27T12:00:02.000Z"
    assert event["model_score"] == 0.8

    processing = event["processing"]
    assert processing["model_id"] == "yamnet/1"
    assert processing["rule_version"] == "demo-1"
    assert processing["sample_rate_hz"] == 16000
    assert processing["window_ms"] == 2000
    assert processing["hop_ms"] == 1000
    assert processing["last_chunk_seq"] == 1
    assert processing["inference_ms"] >= 0
    assert processing["capture_to_detection_ms"] >= 0
    assert processing["rms_dbfs"] > -120
    assert processing["dropped_frames_total"] == 0

    stored, next_cursor = store.get_live_events()
    assert next_cursor is None
    assert stored[0]["event"]["event_id"] == event["event_id"]
    assert stored[0]["acknowledged_at"] is None


def test_doorbell_events_are_attention_and_numbered_per_stream(tmp_path):
    classifier = ScriptedClassifier([
        {"label": "doorbell", "score": 0.7},
        {"label": "doorbell", "score": 0.7},
    ])
    pipeline, _, changes, _ = build(tmp_path, classifier)

    pipeline.handle_chunk(make_chunk(0))
    pipeline.handle_chunk(make_chunk(1))
    pipeline.handle_chunk(make_chunk(2))

    events = [change["data"]["event"] for change in changes_from(changes)]
    assert [event["event_seq"] for event in events] == [1, 2]
    assert all(event["severity"] == "attention" for event in events)


def test_pipeline_gap_clears_window_and_counts(tmp_path):
    classifier = ScriptedClassifier([
        {"label": "knock", "score": 0.9},
        {"label": "knock", "score": 0.9},
    ])
    pipeline, _, changes, registry = build(tmp_path, classifier)

    pipeline.handle_chunk(make_chunk(0))
    pipeline.handle_chunk(make_chunk(1))
    assert len(changes_from(changes)) == 1

    resets_before = classifier.resets
    gap = make_chunk(5)
    registry.mark_gap(gap)
    pipeline.handle_chunk(gap)
    assert pipeline.audio_gaps == 1
    assert classifier.resets == resets_before + 1

    pipeline.handle_chunk(make_chunk(6))
    assert len(changes_from(changes)) == 2
    assert pipeline.inference_failures == 0


def test_pipeline_new_stream_resets_event_sequence_and_smoothing(tmp_path):
    classifier = ScriptedClassifier([
        {"label": "knock", "score": 0.9},
        {"label": "knock", "score": 0.9},
    ])
    pipeline, _, changes, registry = build(tmp_path, classifier)

    pipeline.handle_chunk(make_chunk(0))
    pipeline.handle_chunk(make_chunk(1))
    registry.record_heartbeat(device_id=DEVICE_ID, stream_id=NEW_STREAM_ID, state="running",
                              native_rate_hz=48000, dropped_frames_total=0, error_code=None)
    pipeline.handle_chunk(make_chunk(0, stream_id=NEW_STREAM_ID))
    pipeline.handle_chunk(make_chunk(1, stream_id=NEW_STREAM_ID))

    events = [change["data"]["event"] for change in changes_from(changes)]
    assert [event["event_seq"] for event in events] == [1, 1]
    assert [event["stream_id"] for event in events] == [STREAM_ID, NEW_STREAM_ID]
    assert classifier.resets >= 2


def test_pipeline_suppresses_detection_during_playback(tmp_path):
    clock = [100.0]
    playback = PlaybackRegistry(monotonic=lambda: clock[0])
    playback.start("playback-1")
    classifier = ScriptedClassifier([
        {"label": "knock", "score": 0.9},
        {"label": "knock", "score": 0.9},
    ])
    pipeline, _, changes, _ = build(tmp_path, classifier, playback)

    pipeline.handle_chunk(make_chunk(0))
    pipeline.handle_chunk(make_chunk(1))
    assert classifier.calls == []
    assert changes_from(changes) == []

    playback.end("playback-1")
    pipeline.handle_chunk(make_chunk(2))  # still inside the two-second grace
    assert classifier.calls == []
    assert changes_from(changes) == []

    clock[0] += 3.0
    pipeline.handle_chunk(make_chunk(3))
    pipeline.handle_chunk(make_chunk(4))
    assert len(changes_from(changes)) == 1


def test_pipeline_inference_errors_are_isolated(tmp_path):
    classifier = ScriptedClassifier([
        RuntimeError("boom"),
        {"label": "knock", "score": 0.9},
    ])
    pipeline, _, changes, _ = build(tmp_path, classifier)

    pipeline.handle_chunk(make_chunk(0))
    pipeline.handle_chunk(make_chunk(1))
    assert pipeline.inference_failures == 1
    assert changes_from(changes) == []

    pipeline.handle_chunk(make_chunk(2))
    assert len(changes_from(changes)) == 1


def test_change_buffer_polling_semantics():
    buffer = ChangeBuffer()
    buffer.append("event.created", {"event": {"event_id": "a"}}, event_id="a")
    buffer.append("settings.changed", {"settings": {}})

    changes, cursor, reset = buffer.poll(0, buffer.instance_id)
    assert [change["cursor"] for change in changes] == [1, 2]
    assert cursor == 2
    assert reset is False

    changes, cursor, reset = buffer.poll(2, buffer.instance_id)
    assert changes == []
    assert cursor == 2
    assert reset is False

    changes, cursor, reset = buffer.poll(2, "a-different-instance")
    assert changes == []
    assert reset is True

    changes, cursor, reset = buffer.poll(None, buffer.instance_id)
    assert reset is True

    _, current, _ = buffer.poll(0, buffer.instance_id)
    changes, cursor, reset = buffer.poll(current + 5, buffer.instance_id)
    assert reset is True


def test_change_buffer_expires_old_cursors():
    buffer = ChangeBuffer()
    for _ in range(510):
        buffer.append("job.changed", {"job": {}})

    changes, cursor, reset = buffer.poll(0, buffer.instance_id)
    assert reset is True
    assert changes == []

    changes, cursor, reset = buffer.poll(505, buffer.instance_id)
    assert reset is False
    assert [change["cursor"] for change in changes] == [506, 507, 508, 509, 510]


def test_live_event_paging_and_acknowledgement(tmp_path):
    now = datetime(2026, 9, 27, 12, 0, 10, tzinfo=timezone.utc).timestamp()
    store = EventStore(tmp_path / "events.sqlite3", clock=lambda: now)
    for index in range(3):
        store.save_event({
            "schema_version": 1,
            "event_id": f"live-{index}",
            "occurred_at": f"2026-09-27T12:00:0{index}.000Z",
            "stream_id": "s",
        }, kind="live")
    store.save_event({"event_id": "legacy", "processed_at": "2026-09-27T12:00:00+00:00"})

    items, next_cursor = store.get_live_events(limit=2)
    assert [item["event"]["event_id"] for item in items] == ["live-2", "live-1"]
    assert next_cursor is not None

    items, next_cursor = store.get_live_events(limit=2, before=next_cursor)
    assert [item["event"]["event_id"] for item in items] == ["live-0"]
    assert next_cursor is None

    items, _ = store.get_live_events()
    assert items[0]["acknowledged_at"] is None

    first, created = store.acknowledge("live-2")
    assert first is not None
    assert created is True
    repeat, created_again = store.acknowledge("live-2")
    assert repeat == first
    assert created_again is False
    assert store.acknowledge("missing") is None

    with pytest.raises(ValueError):
        store.get_live_events(before="not-a-cursor")
