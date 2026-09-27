from io import BytesIO
import wave

import numpy as np
import pytest


@pytest.fixture
def make_wav():
    def make(rate=16000, seconds=1, channels=1, width=2, samples=None):
        if samples is None:
            samples = np.zeros((int(rate * seconds), channels), dtype="<i2")
        buffer = BytesIO()
        with wave.open(buffer, "wb") as recording:
            recording.setnchannels(channels)
            recording.setsampwidth(width)
            recording.setframerate(rate)
            recording.writeframes(samples.tobytes())
        return buffer.getvalue()
    return make
