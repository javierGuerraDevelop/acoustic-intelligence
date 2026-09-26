"""Snowflake analytics adapter package (M1).

The cloud host imports :class:`SnowflakeAnalyticsAdapter` and the value types
from here; it owns scheduling, authentication context and the single-writer
serialization guard described in the architecture plan.
"""

from .config import SnowflakeConfig
from .errors import AdapterError
from .models import AnalyticsRow, ExportResult, SummaryResult
from .snowflake_adapter import SnowflakeAnalyticsAdapter

__all__ = [
    "AdapterError",
    "AnalyticsRow",
    "ExportResult",
    "SnowflakeAnalyticsAdapter",
    "SnowflakeConfig",
    "SummaryResult",
]
