# Snowflake setup notes (M1)

Owned by M1. The cloud host (`cloud/app.py`, M2) calls the blocking adapter in
`cloud/analytics/` from a dedicated executor; this directory only holds DDL and
provisioning notes.

## Objects

- Database/schema: any dedicated demo database, e.g. `ACOUSTIC_DEMO.RADAR`.
- Table: `ACOUSTIC_EVENTS`, created by `001_create_acoustic_events.sql`.
- Warehouse: any XS warehouse; Cortex calls run on the same warehouse.
- Role: one service role used by the adapter.

## Key-pair authentication

1. Generate an unencrypted PKCS#8 private key (store it only in the ignored
   local env or encrypted runtime variables):

   ```bash
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out snowflake_key.pem
   openssl pkey -in snowflake_key.pem -pubout -out snowflake_key.pub
   ```

2. Register the public key on the service user:

   ```sql
   ALTER USER <service_user> SET RSA_PUBLIC_KEY='<base64 DER of snowflake_key.pub>';
   ```

3. Give the launcher `SNOWFLAKE_PRIVATE_KEY_B64` (base64 of the PEM file) or
   `SNOWFLAKE_PRIVATE_KEY_PATH` plus optional
   `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE`. The adapter converts PEM to DER in
   memory; nothing is written to disk by the service.

## Privileges

```sql
GRANT USAGE ON DATABASE <db> TO ROLE <service_role>;
GRANT USAGE ON SCHEMA <db>.<schema> TO ROLE <service_role>;
GRANT USAGE ON WAREHOUSE <warehouse> TO ROLE <service_role>;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE <db>.<schema>.ACOUSTIC_EVENTS TO ROLE <service_role>;

-- Cortex access for AI_COMPLETE. Per the Snowflake AI SQL access-control
-- guide, grant either the account-level AI_FUNCTIONS privilege or the
-- per-function privilege together with a qualifying Cortex database role:
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE <service_role>;
-- and/or (account-level, requires ACCOUNTADMIN):
-- GRANT EXECUTE AI FUNCTION SNOWFLAKE.CORTEX.AI_COMPLETE TO ROLE <service_role>;
```

Exact privilege names and the supported model list depend on the region and
Snowflake release; verify in the actual account (`SNOWFLAKE_AI_MODEL`,
documented example `llama3.3-70b`).

## Verification

Run the adapter self-test after provisioning. It authenticates with the key
pair, creates the table if missing, MERGEs a random test event twice, asserts
one row, calls `AI_COMPLETE`, and deletes only the test device's rows:

```bash
python -m cloud.analytics.selftest
```

Exit code 0 prints sanitized evidence (query IDs, counts, AI text). A missing
credential exits 2 with the env var names that are required.
