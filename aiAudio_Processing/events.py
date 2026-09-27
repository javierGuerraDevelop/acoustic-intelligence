from datetime import datetime, timezone
from uuid import uuid4
import math


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
