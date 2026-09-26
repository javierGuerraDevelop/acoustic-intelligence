"""Minimal DB-API fakes for adapter unit tests.

The fakes match statements by SQL substring and record every call so tests can
assert parameterization and idempotency without a live account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutedStatement:
    sql: str
    params: Any
    timeout: Any


@dataclass
class FakeResult:
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    rowcount: int = -1
    sfqid: str = "fake-query-id"


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self._connection = connection
        self._result = FakeResult()
        self._rows: list[tuple[Any, ...]] = []
        self.sfqid = ""
        self.rowcount = -1

    def execute(self, sql: str, params: Any = None, timeout: Any = None) -> "FakeCursor":
        self._connection.executed.append(ExecutedStatement(sql=sql, params=params, timeout=timeout))
        if self._connection.fail_on is not None and self._connection.fail_on in sql:
            raise self._connection.fail_exception
        result = self._connection.result_for(sql)
        self._rows = list(result.rows)
        self.sfqid = result.sfqid
        self.rowcount = result.rowcount
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows, self._rows = self._rows, []
        return rows

    def fetchone(self) -> tuple[Any, ...] | None:
        if not self._rows:
            return None
        return self._rows.pop(0)

    def close(self) -> None:
        self._connection.closed_cursors += 1


class FakeConnection:
    def __init__(
        self,
        counts_rows: list[tuple[Any, ...]] | None = None,
        latest: Any = None,
        ai_text: str = "fake summary",
        delete_rowcount: int = 0,
        purge_rowcount: int = 0,
        fail_on: str | None = None,
        fail_exception: Exception | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self.counts_rows = counts_rows or []
        self.latest = latest
        self.ai_text = ai_text
        self.delete_rowcount = delete_rowcount
        self.purge_rowcount = purge_rowcount
        self.fail_on = fail_on
        self.fail_exception = fail_exception or RuntimeError("fake failure")
        self.connect_error = connect_error
        self.executed: list[ExecutedStatement] = []
        self.closed = False
        self.closed_cursors = 0
        self.merge_calls = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True

    def result_for(self, sql: str) -> FakeResult:
        normalized = " ".join(sql.split())
        if "MERGE INTO" in normalized:
            self.merge_calls += 1
            return FakeResult(sfqid=f"merge-{self.merge_calls}")
        if "GROUP BY LABEL" in normalized:
            return FakeResult(rows=self.counts_rows, sfqid="counts-query")
        if "SELECT MAX(OCCURRED_AT)" in normalized:
            return FakeResult(rows=[(self.latest,)], sfqid="latest-query")
        if "AI_COMPLETE" in normalized:
            return FakeResult(rows=[(self.ai_text,)], sfqid="ai-query")
        if normalized.startswith("DELETE FROM") and "EXPIRES_AT <=" in normalized:
            return FakeResult(rowcount=self.purge_rowcount, sfqid="purge-query")
        if normalized.startswith("DELETE FROM"):
            return FakeResult(rowcount=self.delete_rowcount, sfqid="delete-query")
        return FakeResult()


def make_connect_factory(connection: FakeConnection):
    def factory(**_kwargs: Any) -> FakeConnection:
        if connection.connect_error is not None:
            raise connection.connect_error
        return connection

    return factory
