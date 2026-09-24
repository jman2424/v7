# Supabase migration preparation

## Current status

**Preparation only: the running application still uses SQLite and JSON files.**
This package creates and tests the destination schema and provides a verified,
non-destructive import. It does not replace the application's storage adapter or
switch the live deployment. The offline preparation does not contact Supabase.
Do not set a database URL expecting Flask to switch over or remove any existing
persistent disk before the data has been independently backed up.

`service/postgres_business_documents.py` is an unwired tenant-scoped document
repository; existing path-based callers still use local JSON. Management
session and login-throttling methods now have a PostgreSQL path that
will use server-only `V7_POSTGRES_DSN` and optional `V7_SUPABASE_CA_FILE`.
`create_app` still rejects `V7_STORAGE_BACKEND=postgres`, and the shared
security connection fails closed in that mode, because MFA, registration,
billing, tenant access, MCP and webhook callers still use SQLite SQL. The
runtime PostgreSQL dependency belongs in `requirements.txt` when the full
adapter is ready. **Do not enable this setting on Render yet.** The remaining
cutover work is listed below explicitly. Keep existing sign-in,
authenticator verification, tenant permissions and Stripe activation checks.
Supabase Auth and Google login are not part of this database migration.

## Destination design

The SQL files in `supabase/migrations/`, applied in filename order, create private tables in
`v7_private`, separate from the public Data API schema:

| Existing source | Destination |
| --- | --- |
| `logs/security.db` | Sessions, MFA, signup, ownership, billing and webhook tables |
| `logs/analytics.db` | Events, leads, usage, sales, sales requests, inventory and exchange-rate tables |
| `business/COMPANY/*.json` and tenant `audit.log.jsonl` | `tenants` and tenant-scoped `business_documents` (JSONB) |
| Dated business snapshots | `document_versions` |
| Optional protected account registry | `operator_accounts` |
| Optional CRM snapshot | `crm_records` |
| Optional `logs/selfrepair.log` | `audit_records` |

Passwords remain existing hashes. Enrolled authenticator secrets and ownership
identifiers are preserved. Active management sessions and unfinished MFA challenges
are not copied: everyone must sign in again after cutover. MCP/REST OAuth grants
are also discarded, requiring fresh owner consent. Unfinished email
verification/workspace-creation requests are expired with their credentials cleared.
Verified pending join requests are retained. No paid status is inferred or invented.

All tables have row-level security (RLS) enabled and forced. Tenant tables require
an exact transaction-local `v7.tenant` setting. `anon`, `authenticated` and
`service_role` have no access to the private schema. The non-login `v7_backend`
role cannot create schemas, bypass RLS or delete audit records. Global authentication
tables are accessible to that trusted backend role; they are not user-facing APIs.

The future server adapter must authorize the account **before** setting tenant
context using a parameterized `SELECT set_config('v7.tenant', %s, true)` inside a
transaction. A browser-supplied tenant ID is never authorization. Never use a
superuser or the migration-owner connection for normal application requests.

## Create the project

1. Create a dedicated Supabase project in your chosen region.
2. Keep `v7_private` out of exposed Data API schemas; disable the Data API if no
   other application needs it. Do not enable public policies for these tables.
3. Enable database SSL enforcement. Obtain the connection details and root CA from
   Supabase's Connect/Database settings. Use a direct connection or session pooler
   for this migration; avoid transaction pooling for schema administration.
4. Store the migration connection string as `V7_SUPABASE_MIGRATION_DSN` in a
   protected server environment and the CA path as `V7_SUPABASE_CA_FILE` when a
   project-specific certificate is needed. The importer enforces `verify-full`,
   even if a weaker SSL mode is present in the connection string. Never paste
   credentials into chat, shell arguments, source files, or browser bundles.
5. Run all SQL migrations in filename order in the Supabase SQL editor as the migration owner.
   Review it first; it changes only the new `v7_private` schema and `v7_backend` role.

Official references: [database connections](https://supabase.com/docs/guides/database/connecting-to-postgres),
[SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement),
[securing data](https://supabase.com/docs/guides/database/secure-data).

## Rehearse the data copy

Take a protected backup while **all application and webhook writers are stopped**.
The backup must include `business/`, `logs/security.db`, `logs/analytics.db`, and
any configured CRM/audit/registry files. If their deployment paths differ, copy
them into the documented layout in the backup, not in the live data directory.
Keep the live originals and an independent backup. A snapshot on the same Render
disk is not an independent backup.

Install the migration-only dependency:

```sh
python -m pip install -r requirements-migration.txt
```

Offline dry run (the default; no database connection or source changes):

```sh
python scripts/prepare_supabase.py --data-dir /protected/v7-backup --accounts /protected/accounts.json
```

Omit `--accounts` only if the app does not use `ADMIN_USERS_FILE`; environment-managed
accounts remain environment-managed and are not exported. Unknown SQLite tables,
unexpected business files, malformed JSON or JSONL and missing security data stop the tool
instead of silently discarding data. Review custom deployment files before proceeding.

Import into an **empty** destination, using the protected migration connection:

```sh
python scripts/prepare_supabase.py --data-dir /protected/v7-backup --accounts /protected/accounts.json --apply --source-frozen
python scripts/prepare_supabase.py --data-dir /protected/v7-backup --accounts /protected/accounts.json --verify-only --source-frozen
```

The copy is transactional, checks row counts and content digests before committing,
and restores identity sequences. It refuses nonempty destinations and never
overwrites data. Reports contain counts, not credential values or business records.
An error prints its exception class only, because database error details can expose
rejected records. A failed import rolls back; schema preparation remains in place.

## Required before live cutover

- Implement and test PostgreSQL connections in `session_store`, `analytics_db`,
  and `analytics_service`; port SQLite-specific SQL and transaction locks explicitly.
- Route `Storage` reads/writes/versioning, tenant creation/listing, account registry,
  CRM and audit persistence through the new tables. Do not leave parallel writable
  copies in SQLite/JSON or fall back to local storage on database errors.
- Create a separate, restricted server login that inherits `v7_backend`, with no
  owner, DDL, superuser or RLS-bypass powers. Configure it only as a server secret.
- Test the existing auth/MFA/payment/tenant suite against Supabase, including
  transaction-local tenant scope with connection pooling and concurrent writes.
- Rehearse restore, back up the final frozen source, repeat the import into a clean
  destination, verify it, and only then deploy the completed PostgreSQL adapter.
- Keep the old source read-only after cutover. Rolling back after new PostgreSQL
  writes requires reconciling those writes; switching to an old snapshot would lose data.

The local integration test uses PostgreSQL compiled to WebAssembly (PGlite). It
checks schema application, import verification and RLS. It does not establish
Supabase network, TLS, backup, pooler or concurrent-worker behavior.

## Checks

```sh
python -m pytest tests/test_supabase_preparation.py -q
```

Set `V7_TEST_POSTGRES_DSN` only to an **empty disposable test database** to include
the PostgreSQL integration test. It creates a schema and test roles and refuses an
existing `v7_private` schema. Without that variable, the integration test is skipped.

Apply all files in `supabase/migrations/` in filename order, including the additive billing-discounts migration (schema version 2) and sales-actions/usage migration (schema version 3). The importer preserves saved tenant discounts and sales requests, skips short-lived sales rate-limit attempts, and requires all three versions.
