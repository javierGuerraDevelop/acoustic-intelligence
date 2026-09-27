from types import SimpleNamespace

import numpy as np
import pytest

from classifier import SoundClassifier
from detector import DetectionRules


def fake_classifier(scores):
    classifier = object.__new__(SoundClassifier)
    classifier.labels = ["Knock", "Doorbell", "Ding-dong", "Speech", "Silence"]
    classifier.indices = {"knock": [0], "doorbell": [1, 2]}
    classifier.model = lambda audio: (SimpleNamespace(numpy=lambda: np.array(scores)), None, None)
    classifier.rules = DetectionRules()
    return classifier


def test_short_knock_survives_background_and_unrelated_class_scores():
    classifier = fake_classifier([[.9, 0, 0, .99, 0]] + [[0, 0, 0, .99, 0]] * 8)
    assert classifier.classify(np.zeros(32000)) == {"label": "knock", "score": .9}


def test_ding_dong_maps_to_doorbell_and_tie_favors_doorbell():
    classifier = fake_classifier([[.8, .1, .8, .99, 0]])
    assert classifier.classify(np.zeros(32000)) == {"label": "doorbell", "score": .8}


def test_low_scores_and_background_produce_no_event():
    classifier = fake_classifier([[.03, .02, .01, .99, .99]])
    assert classifier.classify(np.zeros(32000)) is None


def test_candidate_needs_two_contiguous_windows():
    classifier = fake_classifier([[.4, 0, 0, 0, 0]])
    assert classifier.classify(np.zeros(32000)) is None
    assert classifier.classify(np.zeros(32000)) is None  # unrelated upload
    classifier.rules.reset_continuity()
    assert classifier.classify(np.zeros(32000), continuous=True) is None
    assert classifier.classify(np.zeros(32000), continuous=True)["label"] == "knock"


def test_continuous_ringing_latches_until_release_and_cooldown():
    now = [0.0]
    rules = DetectionRules(clock=lambda: now[0])
    high = {"knock": 0, "doorbell": .9}
    low = {"knock": 0, "doorbell": 0}
    assert rules.evaluate(high)["label"] == "doorbell"
    now[0] = 20
    assert rules.evaluate(high) is None  # time alone cannot rearm
    assert rules.evaluate(low) is None
    assert rules.evaluate(high) is None  # one low window isn't enough
    rules.evaluate(low)
    rules.evaluate(low)
    assert rules.evaluate(high)["label"] == "doorbell"


def test_gap_retains_cooldown_and_clears_candidate_state():
    now = [0.0]
    rules = DetectionRules(clock=lambda: now[0])
    assert rules.evaluate({"knock": .9, "doorbell": 0})
    rules.reset_continuity()
    assert rules.evaluate({"knock": .9, "doorbell": 0}) is None
    now[0] = 10
    assert rules.evaluate({"knock": .9, "doorbell": 0})


def test_warmup_does_not_emit_or_latch():
    classifier = fake_classifier([[.9, 0, 0, 0, 0]])
    classifier.warm_up()
    assert classifier.classify(np.zeros(32000))["label"] == "knock"


@pytest.mark.parametrize("scores", [[[float("nan"), 0, 0, 0, 0]], [[2, 0, 0, 0, 0]], []])
def test_invalid_model_scores_rejected(scores):
    with pytest.raises(ValueError):
        fake_classifier(scores).score(np.zeros(32000))


def test_missing_local_model_fails_without_importing_hub(tmp_path):
    with pytest.raises(ValueError, match="saved_model.pb"):
        SoundClassifier(tmp_path)
