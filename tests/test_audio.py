import struct

import numpy as np
import pytest

from audio_processing import prepare_wav


def test_48k_tone_preserves_duration_frequency_and_scale(make_wav):
    samples = (10000 * np.sin(2 * np.pi * 440 * np.arange(48000) / 48000)).astype("<i2")
    audio = prepare_wav(make_wav(rate=48000, samples=samples))
    assert audio.shape == (16000,)
    assert audio.dtype == np.float32
    assert abs(np.argmax(abs(np.fft.rfft(audio))) - 440) <= 1
    assert np.max(abs(audio)) < .32


def test_stereo_pcm_endianness_and_scaling(make_wav):
    samples = np.array([[-32768, 0], [32767, 32767]], dtype="<i2")
    audio = prepare_wav(make_wav(channels=2, samples=samples))
    np.testing.assert_allclose(audio, [-.5, 32767 / 32768])


@pytest.mark.parametrize("rate", [1, 1000000007])
def test_extreme_sample_rates_rejected_before_resampling(make_wav, monkeypatch, rate):
    data = bytearray(make_wav(samples=np.zeros(1, dtype="<i2")))
    struct.pack_into("<I", data, 24, rate)
    def forbidden(*args, **kwargs):
        pytest.fail("Resampler must not run for unsupported rates")
    monkeypatch.setattr("audio_processing.resample_poly", forbidden)
    with pytest.raises(ValueError, match="sample rate"):
        prepare_wav(data)


@pytest.mark.parametrize("kind", ["empty", "truncated", "long", "8bit", "invalid"])
def test_invalid_wav_rejected(make_wav, kind):
    data = {
        "empty": lambda: make_wav(seconds=0),
        "truncated": lambda: make_wav()[:-2],
        "long": lambda: make_wav(seconds=10.1),
        "8bit": lambda: make_wav(width=1),
        "invalid": lambda: b"bad wav",
    }[kind]()
    with pytest.raises(ValueError):
        prepare_wav(data)
