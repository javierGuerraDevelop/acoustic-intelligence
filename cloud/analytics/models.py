"""Value types for the Snowflake analytics adapter (plan section 5.7)."""

from __future__ import annotations

from dataclasses import dataclass, field

ALLOWED_LABELS = frozenset({"knock", "doorbell"})
ALLOWED_SEVERITIES = frozenset({"info", "attention"})
MAX_SUMMARY_CHARS = 1000


@dataclass(frozen=True)
class AnalyticsRow:
    """One consented event projection. No profile or user identifiers."""

    schema_version: int
    event_id: str
    analytics_device_id: str
    occurred_at: str
    label: str
    model_score: float
    severity: str
    model_id: str
    rule_version: str
    expires_at: str


@dataclass(frozen=True)
class ExportResult:
    event_ids: list[str]
    query_id: str


@dataclass(frozen=True)
class SummaryResult:
    text: str
    event_count: int
    counts: dict[str, int] = field(default_factory=dict)
    since: str = ""
    through: str = ""
    generated_at: str = ""
    model: str | None = None
    query_id: str | None = None
