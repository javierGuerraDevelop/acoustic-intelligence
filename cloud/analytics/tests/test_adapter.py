"""Unit tests for the Snowflake analytics adapter (no live account needed)."""

from __future__ import annotations

import datetime as dt
import unittest

from cloud.analytics.config import DEFAULT_AI_MODEL, SnowflakeConfig
from cloud.analytics.errors import AdapterError
from cloud.analytics.models import AnalyticsRow
from cloud.analytics.snowflake_adapter import (
    MAX_ROWS_PER_MERGE,
    SnowflakeAnalyticsAdapter,
)

from .fake_snowflake import FakeConnection, make_connect_factory

DEVICE_KEY = "9d7db096-bae4-48b1-ade5-cf1df597e51e"

BASE_ROW = dict(
    schema_version=1,
    event_id="67e3664e-8f10-43d6-b2eb-ae0bf27d94df",
    analytics_device_id=DEVICE_KEY,
    occurred_at="2026-09-26T18:00:01.000Z",
    label="knock",
    model_score=0.74,
    severity="info",
    model_id="yamnet/1",
    rule_version="demo-1",
    expires_at="2026-09-27T18:00:01.000Z",
)


def make_row(**overrides) -> AnalyticsRow:
    values = dict(BASE_ROW)
    values.update(overrides)
    return AnalyticsRow(**values)


def make_config() -> SnowflakeConfig:
    return SnowflakeConfig(
        account="acct",
        user="user",
        private_key_der=None,
        private_key_passphrase=None,
        role="role",
        warehouse="wh",
        database="db",
        schema="schema",
        ai_model=DEFAULT_AI_MODEL,
    )


def make_adapter(connection: FakeConnection) -> SnowflakeAnalyticsAdapter:
    return SnowflakeAnalyticsAdapter(
        make_config(), connect_factory=make_connect_factory(connection)
    )


class UpsertTests(unittest.TestCase):
    def test_duplicate_event_ids_merge_once(self) -> None:
        connection = FakeConnection()
        adapter = make_adapter(connection)

        result = adapter.upsert_events([make_row(), make_row()])

        self.assertEqual(result.event_ids, [BASE_ROW["event_id"]])
        self.assertEqual(connection.merge_calls, 1)
        merge = connection.executed[0]
        self.assertIn("WHEN NOT MATCHED THEN INSERT", merge.sql)
        self.assertIn("ON t.EVENT_ID = s.EVENT_ID", merge.sql)
        self.assertIn("MERGE INTO ACOUSTIC_EVENTS", merge.sql)
        self.assertEqual(len(merge.params), 10)
        self.assertEqual(merge.timeout, 15)

    def test_batches_larger_than_limit_are_chunked(self) -> None:
        connection = FakeConnection()
        adapter = make_adapter(connection)
        rows = [
            make_row(event_id=f"event-{index:03d}") for index in range(MAX_ROWS_PER_MERGE + 1)
        ]

        result = adapter.upsert_events(rows)

        self.assertEqual(len(result.event_ids), MAX_ROWS_PER_MERGE + 1)
        self.assertEqual(connection.merge_calls, 2)
        self.assertEqual(len(connection.executed[1].params), 10)

    def test_parameter_order_matches_columns(self) -> None:
        connection = FakeConnection()
        adapter = make_adapter(connection)
        adapter.upsert_events([make_row()])

        params = connection.executed[0].params
        self.assertEqual(params[0], 1)
        self.assertEqual(params[1], BASE_ROW["event_id"])
        self.assertEqual(params[2], DEVICE_KEY)
        self.assertEqual(params[3], "2026-09-26T18:00:01.000Z")
        self.assertEqual(params[4], "knock")
        self.assertEqual(params[5], 0.74)
        self.assertEqual(params[9], "2026-09-27T18:00:01.000Z")

    def test_bad_label_is_terminal_input_error(self) -> None:
        adapter = make_adapter(FakeConnection())
        with self.assertRaises(AdapterError) as ctx:
            adapter.upsert_events([make_row(label="siren")])
        self.assertEqual(ctx.exception.code, "BAD_INPUT")
        self.assertFalse(ctx.exception.retryable)

    def test_non_finite_score_rejected(self) -> None:
        adapter = make_adapter(FakeConnection())
        with self.assertRaises(AdapterError) as ctx:
            adapter.upsert_events([make_row(model_score=float("nan"))])
        self.assertEqual(ctx.exception.code, "BAD_INPUT")

    def test_empty_batch_rejected(self) -> None:
        adapter = make_adapter(FakeConnection())
        with self.assertRaises(AdapterError) as ctx:
            adapter.upsert_events([])
        self.assertEqual(ctx.exception.code, "BAD_INPUT")


class SummaryTests(unittest.TestCase):
    def test_empty_window_skips_ai_call(self) -> None:
        connection = FakeConnection(counts_rows=[])
        adapter = make_adapter(connection)

        result = adapter.summarize(DEVICE_KEY, "2026-09-26T17:30:00.000Z")

        self.assertEqual(result.event_count, 0)
        self.assertEqual(result.counts, {})
        self.assertIsNone(result.model)
        self.assertIsNone(result.query_id)
        self.assertNotIn("AI_COMPLETE", " ".join(stmt.sql for stmt in connection.executed))
        counts_stmt = connection.executed[0]
        self.assertIn("EXPIRES_AT > CURRENT_TIMESTAMP()", counts_stmt.sql)
        self.assertEqual(counts_stmt.params, (DEVICE_KEY, "2026-09-26T17:30:00.000Z"))
        self.assertEqual(counts_stmt.timeout, 15)

    def test_summary_uses_real_counts_and_ai_complete(self) -> None:
        import re

        latest = dt.datetime(2026, 9, 26, 18, 0, 1, tzinfo=dt.timezone.utc)
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)
        connection = FakeConnection(
            counts_rows=[("knock", 3), ("doorbell", 1)], latest=latest
        )
        adapter = make_adapter(connection)

        result = adapter.summarize(DEVICE_KEY, since.isoformat())

        self.assertEqual(result.event_count, 4)
        self.assertEqual(result.counts, {"knock": 3, "doorbell": 1})
        self.assertEqual(result.model, DEFAULT_AI_MODEL)
        self.assertEqual(result.query_id, "ai-query")
        self.assertEqual(result.through, "2026-09-26T18:00:01.000Z")
        self.assertEqual(result.text, "fake summary")
        self.assertTrue(result.since.endswith("Z"))
        self.assertTrue(result.generated_at.endswith("Z"))

        ai_stmt = next(stmt for stmt in connection.executed if "AI_COMPLETE" in stmt.sql)
        self.assertEqual(ai_stmt.params[0], DEFAULT_AI_MODEL)
        prompt = ai_stmt.params[1]
        self.assertIn('{"doorbell":1,"knock":3}', prompt)
        self.assertRegex(prompt, r"last (29|30|31) minutes")
        self.assertIn("possible detections, not confirmed visits", prompt)
        self.assertIn("Do not infer emergencies", prompt)

    def test_unknown_labels_are_not_counted(self) -> None:
        connection = FakeConnection(counts_rows=[("knock", 2), ("siren", 9)])
        adapter = make_adapter(connection)
        result = adapter.summarize(DEVICE_KEY, "2026-09-26T17:30:00.000Z")
        self.assertEqual(result.counts, {"knock": 2})
        self.assertEqual(result.event_count, 2)

    def test_summary_text_is_capped(self) -> None:
        connection = FakeConnection(counts_rows=[("knock", 1)], ai_text="x" * 5000)
        adapter = make_adapter(connection)
        result = adapter.summarize(DEVICE_KEY, "2026-09-26T17:30:00.000Z")
        self.assertEqual(len(result.text), 1000)

    def test_future_since_is_rejected(self) -> None:
        adapter = make_adapter(FakeConnection())
        with self.assertRaises(AdapterError) as ctx:
            adapter.summarize(DEVICE_KEY, "2999-01-01T00:00:00.000Z")
        self.assertEqual(ctx.exception.code, "BAD_INPUT")


class DeleteAndPurgeTests(unittest.TestCase):
    def test_delete_is_parameterized_by_device(self) -> None:
        connection = FakeConnection()
        adapter = make_adapter(connection)
        adapter.delete_events(DEVICE_KEY)
        statement = connection.executed[0]
        self.assertEqual(statement.params, (DEVICE_KEY,))
        self.assertIn("DELETE FROM ACOUSTIC_EVENTS", statement.sql)
        self.assertEqual(statement.timeout, 15)

    def test_purge_returns_rowcount(self) -> None:
        connection = FakeConnection(purge_rowcount=7)
        adapter = make_adapter(connection)
        self.assertEqual(adapter.purge_expired("2026-09-27T00:00:00.000Z"), 7)
        statement = connection.executed[0]
        self.assertEqual(statement.params, ("2026-09-27T00:00:00.000Z",))
        self.assertIn("EXPIRES_AT <= TO_TIMESTAMP_TZ(%s)", statement.sql)


class ErrorMappingTests(unittest.TestCase):
    def test_authentication_failure_is_terminal(self) -> None:
        from snowflake.connector.errors import DatabaseError

        connection = FakeConnection(connect_error=DatabaseError("Authentication failed"))
        adapter = make_adapter(connection)
        with self.assertRaises(AdapterError) as ctx:
            adapter.upsert_events([make_row()])
        self.assertEqual(ctx.exception.code, "AUTH_FAILED")
        self.assertFalse(ctx.exception.retryable)

    def test_operational_timeout_is_retryable(self) -> None:
        from snowflake.connector.errors import OperationalError

        connection = FakeConnection(connect_error=OperationalError("connection timed out"))
        adapter = make_adapter(connection)
        with self.assertRaises(AdapterError) as ctx:
            adapter.upsert_events([make_row()])
        self.assertEqual(ctx.exception.code, "TIMEOUT")
        self.assertTrue(ctx.exception.retryable)

    def test_sql_programming_error_is_terminal_input(self) -> None:
        from snowflake.connector.errors import ProgrammingError

        connection = FakeConnection(
            fail_on="MERGE INTO", fail_exception=ProgrammingError("SQL compilation error")
        )
        adapter = make_adapter(connection)
        with self.assertRaises(AdapterError) as ctx:
            adapter.upsert_events([make_row()])
        self.assertEqual(ctx.exception.code, "BAD_INPUT")
        self.assertFalse(ctx.exception.retryable)


class ConfigTests(unittest.TestCase):
    def test_missing_account_is_input_error(self) -> None:
        with self.assertRaises(AdapterError) as ctx:
            SnowflakeConfig.from_env({"SNOWFLAKE_USER": "user"})
        self.assertEqual(ctx.exception.code, "BAD_INPUT")

    def test_defaults_model_and_parses_der_key(self) -> None:
        import base64

        der = b"\x30\x2a" + bytes(range(32))
        config = SnowflakeConfig.from_env(
            {
                "SNOWFLAKE_ACCOUNT": "acct",
                "SNOWFLAKE_USER": "user",
                "SNOWFLAKE_PRIVATE_KEY_B64": base64.b64encode(der).decode(),
            }
        )
        self.assertEqual(config.ai_model, DEFAULT_AI_MODEL)
        self.assertEqual(config.private_key_der, der)
        self.assertEqual(config.query_timeout_seconds, 15)


if __name__ == "__main__":
    unittest.main()
