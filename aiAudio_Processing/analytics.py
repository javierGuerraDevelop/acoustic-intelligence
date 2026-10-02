"""Optional Snowflake analytics integration for the local service.

Only this module imports the M1 adapter in ``cloud/analytics``, and the import
is optional: without Snowflake credentials the local service still starts and
summary jobs fail with a visible, retryable error instead of crashing. The
adapter dependencies are not part of ``requirements-local.lock``; install
``cloud/analytics/requirements-analytics.lock`` to enable live calls.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from events import format_utc

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from cloud.analytics.errors import AdapterError
except ImportError:  # pragma: no cover - aiAudio_Processing without the repo
    AdapterError = None


class AnalyticsError(Exception):
    """Sanitized analytics failure safe to surface to the dashboard."""

    def __init__(self, code, retryable, message):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.message = message


class AnalyticsService:
    """Thin wrapper around the M1 Snowflake adapter."""

    def __init__(self, adapter, device_key, now=None):
        self._adapter = adapter
        self._device_key = device_key
        self._now = now or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_env(cls, device_key):
        """Build from SNOWFLAKE_* variables; None when unconfigured."""
        try:
            from cloud.analytics.config import SnowflakeConfig
            from cloud.analytics.snowflake_adapter import SnowflakeAnalyticsAdapter
        except ImportError:
            return None
        try:
            config = SnowflakeConfig.from_env()
        except Exception:
            # Missing or invalid configuration disables the integration.
            return None
        return cls(SnowflakeAnalyticsAdapter(config), device_key)

    def summarize(self, lookback_minutes):
        since = self._now() - timedelta(minutes=lookback_minutes)
        try:
            result = self._adapter.summarize(self._device_key, format_utc(since))
        except Exception as error:
            raise self._translate(error) from None
        return asdict(result)

    def delete_events(self):
        try:
            self._adapter.delete_events(self._device_key)
        except Exception as error:
            raise self._translate(error) from None

    @staticmethod
    def _translate(error):
        if AdapterError is not None and isinstance(error, AdapterError):
            return AnalyticsError(error.code, error.retryable, "Snowflake analytics request failed.")
        return AnalyticsError("UNAVAILABLE", True, "Snowflake analytics is unavailable.")
