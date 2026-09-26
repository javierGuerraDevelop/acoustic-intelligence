-- Live Sound Radar analytics projection (M1).
-- Apply once per target database/schema before enabling the export worker.
-- The cloud adapter issues a parameterized MERGE keyed on EVENT_ID for
-- idempotency; uniqueness does not rely on a Snowflake constraint.

CREATE TABLE IF NOT EXISTS ACOUSTIC_EVENTS (
  SCHEMA_VERSION INTEGER NOT NULL,
  EVENT_ID VARCHAR NOT NULL,
  ANALYTICS_DEVICE_ID VARCHAR NOT NULL,
  OCCURRED_AT TIMESTAMP_TZ NOT NULL,
  LABEL VARCHAR NOT NULL,
  MODEL_SCORE FLOAT NOT NULL,
  SEVERITY VARCHAR NOT NULL,
  MODEL_ID VARCHAR NOT NULL,
  RULE_VERSION VARCHAR NOT NULL,
  EXPIRES_AT TIMESTAMP_TZ NOT NULL
);
