# Analytics adapter (M1)

Snowflake export, Cortex summary, expiration purge and device deletion for
Live Sound Radar. Interface frozen in architecture plan section 5.7:

```python
upsert_events(rows: list[AnalyticsRow]) -> ExportResult
summarize(device_key: str, since_utc: str) -> SummaryResult
delete_events(device_key: str) -> None
purge_expired(now_utc: str) -> int
```

Blocking functions. The cloud host (M2) supplies auth context, the scheduler
and the single-writer serialization guard, and runs these in a dedicated
executor. This package starts no server, thread or daemon.

## Guarantees

- Every statement is parameterized (`%s` binds only).
- `upsert_events` deduplicates the input batch by `event_id` and issues a
  parameterized `MERGE ... WHEN NOT MATCHED` keyed on `EVENT_ID`, so a retried
  or duplicated export inserts once. Nothing relies on a Snowflake constraint.
- `summarize` counts only nonexpired rows, filters to `knock`/`doorbell`,
  calls real `SELECT AI_COMPLETE(%s, %s)`, and returns `model:null`,
  `query_id:null` with a deterministic empty-state text when no rows exist.
- `delete_events` removes rows for one `analytics_device_id`;
  `purge_expired` removes rows past `EXPIRES_AT` and returns the row count.
- Every query uses a 15-second statement timeout; login and network timeouts
  come from `SnowflakeConfig`.
- Failures raise `AdapterError(code, retryable)`: `AUTH_FAILED`/`BAD_INPUT`
  terminal, `TIMEOUT`/`RATE_LIMITED`/`UNAVAILABLE` retryable. No secrets or
  provider text in errors.

## Configuration

| Variable | Purpose |
| --- | --- |
| `SNOWFLAKE_ACCOUNT` | account identifier |
| `SNOWFLAKE_USER` | service user with the registered RSA public key |
| `SNOWFLAKE_PRIVATE_KEY_B64` | base64 of the PEM (or DER) private key |
| `SNOWFLAKE_PRIVATE_KEY_PATH` | alternative local PEM path |
| `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` | optional passphrase |
| `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA` | session context |
| `SNOWFLAKE_AI_MODEL` | Cortex model id, default `llama3.3-70b` |
| `SNOWFLAKE_LOGIN_TIMEOUT_SECONDS` | default 10 |
| `SNOWFLAKE_NETWORK_TIMEOUT_SECONDS` | default 15 |
| `SNOWFLAKE_QUERY_TIMEOUT_SECONDS` | default 15 |

See `sql/README.md` for DDL, key-pair registration and privileges.

## Verified environment (26 September 2026)

Installed and import-verified on this workstation with Python 3.14.3:

```
snowflake-connector-python==4.7.5
cryptography==50.0.1
```

Full transitive pin set: `requirements-analytics.lock`. The architecture plan
targets Python 3.11 for the local inference stack; this adapter is pure Python
and the same pins install on 3.11, but only 3.14.3 was verified here.

Install and test:

```bash
python -m venv build/venv-analytics
build/venv-analytics/Scripts/python -m pip install -r cloud/analytics/requirements-analytics.lock
build/venv-analytics/Scripts/python -m unittest discover -s cloud/analytics/tests -t .
```

Live account check (needs credentials; see `sql/README.md`):

```bash
python -m cloud.analytics.selftest
```

## Label boundary

The adapter accepts only the canonical `knock`/`doorbell` labels from M2's
event projection; anything else is a terminal `BAD_INPUT` before SQL runs. The
downloaded YAMNet class map (`Knock`, `Doorbell`, `Ding-dong`) and its mapping
into those two classes stay in M2's inference contract. No model or class map
is created, copied or downloaded here.

## Account status

At the time of this commit no Snowflake credentials are present in the
environment (`SNOWFLAKE_*` unset), so live key-pair authentication and the real
`AI_COMPLETE` call are **blocked account prerequisites**. The self-test exits
with code 2 and names the missing variables. Unit tests exercise SQL shape,
parameter binding, dedupe, empty-summary behavior and error mapping with
DB-API fakes; they do not substitute for the live check.
