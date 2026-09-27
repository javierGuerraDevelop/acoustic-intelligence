"""Live Snowflake smoke test for M1 (connector auth + real AI_COMPLETE).

Run from the repository root with the venv that has the analytics lockfile
installed and the ``SNOWFLAKE_*`` variables exported:

    python -m cloud.analytics.selftest

The test is self-cleaning: it uses a random ``selftest-<uuid>`` analytics
device key and deletes only that device's rows at the end. It prints sanitized
evidence (query IDs, row counts, AI text) and never prints the key.
"""

from __future__ import annotations

import datetime as dt
import sys
import uuid
from pathlib import Path

from cloud.analytics.config import SnowflakeConfig
from cloud.analytics.errors import AdapterError
from cloud.analytics.models import AnalyticsRow
from cloud.analytics.snowflake_adapter import SnowflakeAnalyticsAdapter

REQUIRED_ENV = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PRIVATE_KEY_B64 or SNOWFLAKE_PRIVATE_KEY_PATH",
)

DDL_PATH = Path(__file__).resolve().parents[2] / "sql" / "001_create_acoustic_events.sql"


def _print(label: str, value: object) -> None:
    print(f"{label}: {value}")


def _execute_ddl(config: SnowflakeConfig) -> None:
    from snowflake.connector import connect

    ddl = DDL_PATH.read_text(encoding="utf-8")
    with connect(**config.connect_kwargs()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(ddl)
            _print("ddl_query_id", cursor.sfqid)


def _count_device_rows(config: SnowflakeConfig, device_key: str) -> int:
    from snowflake.connector import connect

    with connect(**config.connect_kwargs()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM ACOUSTIC_EVENTS WHERE ANALYTICS_DEVICE_ID = %s",
                (device_key,),
                timeout=config.query_timeout_seconds,
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0


def main() -> int:
    import os

    missing = [
        name
        for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER")
        if not os.environ.get(name, "").strip()
    ]
    if not (
        os.environ.get("SNOWFLAKE_PRIVATE_KEY_B64", "").strip()
        or os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH", "").strip()
    ):
        missing.append("SNOWFLAKE_PRIVATE_KEY_B64 or SNOWFLAKE_PRIVATE_KEY_PATH")
    if missing:
        _print("status", "blocked")
        _print("missing_env", ", ".join(missing))
        _print("action", "provision the Snowflake service user and export its key pair")
        return 2

    config = SnowflakeConfig.from_env()
    _print("status", "starting")
    _print("connection", config.sanitized())

    adapter = SnowflakeAnalyticsAdapter(config)
    device_key = f"selftest-{uuid.uuid4()}"
    now = dt.datetime.now(dt.timezone.utc)
    event_id = str(uuid.uuid4())
    row = AnalyticsRow(
        schema_version=1,
        event_id=event_id,
        analytics_device_id=device_key,
        occurred_at=_iso(now),
        label="knock",
        model_score=0.74,
        severity="info",
        model_id="yamnet/1",
        rule_version="demo-1",
        expires_at=_iso(now + dt.timedelta(minutes=5)),
    )

    try:
        _execute_ddl(config)
        first = adapter.upsert_events([row])
        second = adapter.upsert_events([row])
        rows_after_duplicate = _count_device_rows(config, device_key)
        summary = adapter.summarize(
            device_key, _iso(now - dt.timedelta(minutes=10))
        )
        adapter.delete_events(device_key)
        rows_after_delete = _count_device_rows(config, device_key)
    except AdapterError as exc:
        _print("status", "failed")
        _print("error_code", exc.code)
        _print("retryable", exc.retryable)
        return 1

    _print("status", "ok")
    _print("merge_query_ids", f"{first.query_id},{second.query_id}")
    _print("rows_after_duplicate_merge", rows_after_duplicate)
    _print("rows_after_delete", rows_after_delete)
    _print("summary_event_count", summary.event_count)
    _print("summary_counts", summary.counts)
    _print("summary_model", summary.model)
    _print("summary_query_id", summary.query_id)
    _print("summary_text", summary.text.replace("\n", " ")[:1000])

    if rows_after_duplicate != 1 or rows_after_delete != 0:
        _print("status", "failed")
        _print("reason", "MERGE idempotency or deletion check did not match expectations")
        return 1
    return 0


def _iso(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


if __name__ == "__main__":
    sys.exit(main())
