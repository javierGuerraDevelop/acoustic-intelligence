import csv
import os
from pathlib import Path

import numpy as np

from detector import DetectionRules


class SoundClassifier:
    """Local YAMNet inference; model download is a separate setup operation."""

    def __init__(self, model_dir=None):
        configured_dir = model_dir or os.environ.get("MODEL_DIR")
        if not configured_dir:
            raise ValueError("Set MODEL_DIR to a downloaded YAMNet SavedModel directory.")
        model_path = Path(configured_dir).expanduser().resolve()
        if not (model_path / "saved_model.pb").is_file():
            raise ValueError("MODEL_DIR must contain saved_model.pb. Run scripts/download_model.py first.")

        # Importing TensorFlow is also slow: keep it off the HTTP startup path.
        import tensorflow_hub as hub

        self.model = hub.load(str(model_path))
        labels_path = self.model.class_map_path().numpy().decode("utf-8")
        with open(labels_path, newline="", encoding="utf-8") as file:
            self.labels = [row["display_name"] for row in csv.DictReader(file)]
        self.indices = {
            "knock": [self.labels.index("Knock")],
            "doorbell": [self.labels.index("Doorbell"), self.labels.index("Ding-dong")],
        }
        self.rules = DetectionRules()

    def score(self, audio):
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
            raise ValueError("Audio must be a non-empty finite mono waveform.")
        if np.max(np.abs(audio)) > 1:
            raise ValueError("Audio must be normalized to [-1, 1].")
        scores, _, _ = self.model(audio)
        scores = scores.numpy()
        if scores.ndim != 2 or not scores.shape[0] or scores.shape[1] != len(self.labels):
            raise ValueError("Unexpected YAMNet score shape.")
        if not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
            raise ValueError("Invalid YAMNet scores.")
        # A brief knock must not be averaged away by surrounding background noise.
        return {label: float(scores[:, indices].max()) for label, indices in self.indices.items()}

    def warm_up(self):
        # Warm the real inference path without changing detector/cooldown state.
        self.score(np.zeros(32000, dtype=np.float32))

    def classify(self, audio, *, continuous=False):
        """Return an eligible prediction or None.

        Separate WAV uploads are independent observations. Only a caller supplying
        consecutive live windows may use continuous=True. Gaps must reset the
        rules; cooldown timestamps survive that reset.
        """
        if not continuous:
            self.rules.reset_continuity()
        return self.rules.evaluate(self.score(audio))


# Preserve the original import for existing callers.
soundClassifier = SoundClassifier
