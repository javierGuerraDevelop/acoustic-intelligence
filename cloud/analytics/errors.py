"""Adapter error type shared with the cloud host.

The architecture plan assigns M2 the canonical ``contracts/`` definition. Until
that module exists, this local definition matches the agreed signature
``AdapterError(code: str, retryable: bool)`` and the two terminal codes
(``AUTH_FAILED``, ``BAD_INPUT``) and three retryable codes (``TIMEOUT``,
``RATE_LIMITED``, ``UNAVAILABLE``).
"""

from __future__ import annotations

TERMINAL_CODES = frozenset({"AUTH_FAILED", "BAD_INPUT"})
RETRYABLE_CODES = frozenset({"TIMEOUT", "RATE_LIMITED", "UNAVAILABLE"})
ALL_CODES = TERMINAL_CODES | RETRYABLE_CODES


class AdapterError(Exception):
    """Sanitized failure surfaced to the cloud host.

    ``code`` is one of the documented codes; ``retryable`` tells the scheduler
    whether to retry with backoff. Messages never contain credentials, SQL
    parameters or raw provider responses.
    """

    def __init__(self, code: str, retryable: bool) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown adapter error code: {code}")
        if (code in RETRYABLE_CODES) != retryable:
            raise ValueError(f"code {code} does not match retryable={retryable}")
        super().__init__(code)
        self.code = code
        self.retryable = retryable

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}(retryable={self.retryable})"
