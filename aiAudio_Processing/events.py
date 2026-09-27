from datetime import datetime, timezone
from uuid import uuid4
import math

MODEL_ID = "yamnet/1"
RULE_VERSION = "demo-1"
WINDOW_MS = 2000
HOP_MS = 1000
SAMPLE_RATE_HZ = 16000


def create_event(
    prediction,
    device_id="local-demo",
    captured_at=None,
):
    # Read the classifier's result.
    label = prediction["label"]
    model_score = float(prediction["score"])

    # Check that the prediction contains valid values.
    if not isinstance(label, str) or not label.strip():
        raise ValueError("The sound label must be non-empty text.")

    if not math.isfinite(model_score) or not 0 <= model_score <= 1:
        raise ValueError("The model score must be between 0 and 1.")

    # Record when the backend created this event.
    processed_at = datetime.now(timezone.utc).isoformat()

    # Build an event that the API can return as JSON.
    return {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "device_id": device_id,
        "captured_at": captured_at,
        "processed_at": processed_at,
        "label": label,
        "model_score": model_score,
        "severity": "attention" if label == "doorbell" else "info",
        "model": "YAMNet",
    }


def create_canonical_event(
    *,
    device_id,
    stream_id,
    event_seq,
    window_start_at,
    occurred_at,
    detected_at,
    prediction,
    last_chunk_seq,
    inference_ms,
    rms_dbfs,
    dropped_frames_total,
    source="microphone",
):
    """Build the canonical detection event from architecture plan 5.3."""
    label = prediction["label"]
    model_score = float(prediction["score"])
    if label not in ("knock", "doorbell"):
        raise ValueError("The label must be knock or doorbell.")
    if not math.isfinite(model_score) or not 0 <= model_score <= 1:
        raise ValueError("The model score must be between 0 and 1.")

    detected = detected_at.astimezone(timezone.utc)
    occurred = occurred_at.astimezone(timezone.utc)
    return {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "device_id": device_id,
        "stream_id": stream_id,
        "event_seq": event_seq,
        "window_start_at": format_utc(window_start_at),
        "occurred_at": format_utc(occurred),
        "detected_at": format_utc(detected),
        "label": label,
        "model_score": model_score,
        "severity": "attention" if label == "doorbell" else "info",
        "action_id": "check_door",
        "source": source,
        "processing": {
            "model_id": MODEL_ID,
            "rule_version": RULE_VERSION,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "window_ms": WINDOW_MS,
            "hop_ms": HOP_MS,
            "last_chunk_seq": last_chunk_seq,
            "inference_ms": inference_ms,
            "capture_to_detection_ms": max(0, int(round((detected - occurred).total_seconds() * 1000))),
            "rms_dbfs": float(rms_dbfs),
            "dropped_frames_total": dropped_frames_total,
        },
    }


def format_utc(value):
    moment = value.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
