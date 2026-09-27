"""ElevenLabs speech synthesis for the local service (plan section 5.8).

Fixed template catalog and the vendor call live here. The API layer validates
the event and the speech consent before asking this module for MP3 bytes.
Generated templates are cached in process RAM for the session.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

import httpx

TEMPLATES = {
    "knock_v1": "Possible knocking detected. Check the door.",
    "doorbell_v1": "Possible doorbell detected. Check the door.",
}
LABEL_TEMPLATES = {"knock": "knock_v1", "doorbell": "doorbell_v1"}

MAX_AUDIO_BYTES = 2 * 1024 * 1024
VENDOR_TIMEOUT_SECONDS = 8.0
MAX_GENERATIONS_PER_MINUTE = 6
VENDOR_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class SpeechError(Exception):
    """Sanitized speech failure; the API maps it to the canonical envelope."""

    def __init__(self, status_code, code, message, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


class SpeechService:
    def __init__(
        self,
        api_key="",
        voice_id="",
        model_id="eleven_multilingual_v2",
        *,
        transport=None,
        monotonic=time.monotonic,
    ):
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._transport = transport
        self._monotonic = monotonic
        self._cache: dict[str, bytes] = {}
        self._recent: deque[float] = deque()
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls):
        return cls(
            api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
            voice_id=os.environ.get("ELEVENLABS_VOICE_ID", ""),
            model_id=os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        )

    @property
    def available(self):
        return bool(self._api_key and self._voice_id)

    @property
    def cached_templates(self):
        with self._lock:
            return frozenset(self._cache)

    def synthesize(self, template_id):
        """Return (mp3_bytes, cached) for one fixed template."""
        try:
            text = TEMPLATES[template_id]
        except KeyError:
            raise SpeechError(422, "SCHEMA_INVALID", "Unknown speech template.") from None
        if not self.available:
            raise SpeechError(
                503, "SPEECH_UNAVAILABLE",
                "ElevenLabs speech is not configured.", retryable=True,
            )

        with self._lock:
            cached = self._cache.get(template_id)
        if cached is not None:
            return cached, True

        self._reserve_generation()
        url = VENDOR_URL.format(voice_id=self._voice_id) + "?output_format=mp3_44100_128"
        try:
            with httpx.Client(transport=self._transport, timeout=VENDOR_TIMEOUT_SECONDS) as client:
                response = client.post(
                    url,
                    headers={"xi-api-key": self._api_key},
                    json={"text": text, "model_id": self._model_id},
                )
        except httpx.HTTPError:
            raise SpeechError(
                503, "SPEECH_UNAVAILABLE",
                "The speech provider could not be reached.", retryable=True,
            ) from None

        if response.status_code == 429:
            raise SpeechError(429, "CAPACITY", "The speech provider rate limit was reached.", retryable=True)
        if response.status_code >= 500:
            raise SpeechError(
                503, "SPEECH_UNAVAILABLE",
                "The speech provider is unavailable.", retryable=True,
            )
        if response.status_code != 200:
            raise SpeechError(
                503, "SPEECH_UNAVAILABLE",
                "The speech provider rejected the request.", retryable=False,
            )

        audio = response.content
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise SpeechError(
                503, "SPEECH_UNAVAILABLE",
                "The speech provider returned an invalid audio response.", retryable=False,
            )

        with self._lock:
            self._cache[template_id] = audio
        return audio, False

    def _reserve_generation(self):
        now = self._monotonic()
        with self._lock:
            while self._recent and now - self._recent[0] > 60.0:
                self._recent.popleft()
            if len(self._recent) >= MAX_GENERATIONS_PER_MINUTE:
                raise SpeechError(
                    429, "CAPACITY",
                    "Speech generation limit reached. Try again shortly.", retryable=True,
                )
            self._recent.append(now)
