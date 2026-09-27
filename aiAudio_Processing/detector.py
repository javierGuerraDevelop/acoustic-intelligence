import math
import time


class DetectionRules:
    """Thresholds and per-class latches for contiguous classification windows."""

    def __init__(self, cooldown_seconds=10, clock=time.monotonic):
        if not 5 <= cooldown_seconds <= 60:
            raise ValueError("Cooldown must be between 5 and 60 seconds.")
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.last_emitted = {label: -math.inf for label in ("knock", "doorbell")}
        self.reset_continuity()

    def reset_continuity(self):
        self.active = {label: False for label in self.last_emitted}
        self.high_count = {label: 0 for label in self.last_emitted}
        self.low_count = {label: 0 for label in self.last_emitted}

    def evaluate(self, scores):
        if set(scores) != set(self.last_emitted) or any(
            not math.isfinite(score) or not 0 <= score <= 1 for score in scores.values()
        ):
            raise ValueError("Expected finite knock and doorbell scores in [0, 1].")
        now = self.clock()
        eligible = []
        for label, score in scores.items():
            self.high_count[label] = min(2, self.high_count[label] + 1) if score >= 0.35 else 0
            self.low_count[label] = min(2, self.low_count[label] + 1) if score < 0.20 else 0
            cooled_down = now - self.last_emitted[label] >= self.cooldown_seconds
            if self.active[label] and cooled_down and self.low_count[label] >= 2:
                self.active[label] = False
            if not self.active[label] and cooled_down and (score >= 0.65 or self.high_count[label] >= 2):
                eligible.append(label)
        if not eligible:
            return None
        label = max(eligible, key=lambda name: (scores[name], name == "doorbell"))
        self.active[label] = True
        self.last_emitted[label] = now
        return {"label": label, "score": scores[label]}
