from io import BytesIO
from math import gcd
import wave

import numpy as np
from scipy.signal import resample_poly


MAX_DURATION_SECONDS = 10
SUPPORTED_SAMPLE_RATES = frozenset({8000, 16000, 22050, 24000, 32000, 44100, 48000, 96000})


def prepare_wav(file_bytes):
    """Decode a 16-bit PCM WAV into mono, 16 kHz float32 audio."""
    try:
        with wave.open(BytesIO(file_bytes), "rb") as recording:
            sample_rate = recording.getframerate()
            channels = recording.getnchannels()
            frame_count = recording.getnframes()

            if recording.getsampwidth() != 2 or recording.getcomptype() != "NONE":
                raise ValueError("Use an uncompressed 16-bit PCM WAV file.")
            if channels not in (1, 2):
                raise ValueError("Use a mono or stereo recording.")
            if sample_rate <= 0 or frame_count <= 0:
                raise ValueError("The recording is empty or invalid.")
            if sample_rate not in SUPPORTED_SAMPLE_RATES:
                raise ValueError("Unsupported sample rate. Use 8, 16, 22.05, 24, 32, 44.1, 48, or 96 kHz.")
            if frame_count / sample_rate > MAX_DURATION_SECONDS:
                raise ValueError("Use a recording no longer than 10 seconds.")

            raw_audio = recording.readframes(frame_count)
            if len(raw_audio) != frame_count * channels * 2:
                raise ValueError("The WAV file is incomplete.")
    except (wave.Error, EOFError) as error:
        raise ValueError("Use a valid uncompressed 16-bit PCM WAV file.") from error

    audio = np.frombuffer(raw_audio, dtype="<i2").astype(np.float32) / 32768.0
    if channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1)

    if sample_rate != 16000:
        divisor = gcd(sample_rate, 16000)
        audio = resample_poly(
            audio,
            up=16000 // divisor,
            down=sample_rate // divisor,
        )

    return np.clip(audio, -1.0, 1.0).astype(np.float32)
