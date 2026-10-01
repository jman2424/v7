# Supabase storage and migration

## Current status

The application supports SQLite/files (the default) and PostgreSQL through
`V7_STORAGE_BACKEND`. PostgreSQL routes business documents and versions, accounts,
sessions, MFA, signup, billing, CRM, audits, webhook deduplication and analytics
through `v7_private`. It does not fall back to local files on a database error.
The runtime driver is included in `requirements.txt`.

**The current live V7 deployment has not been switched to PostgreSQL.** Obtain and
verify a complete independent export of its actual current data, rehearse import
and runtime checks, and configure a verified mail sender before enabling it live.
Pushing code or applying a schema does not preserve Render's ephemeral files.
See [complete live backup](LIVE_BACKUP.md) and the cutover gates below.
Existing password/authenticator verification, tenant permissions and Stripe
activation checks remain required. Supabase Auth and Google login are not part
of this database migration.

## Destination design

The SQL files in `supabase/migrations/`, applied in filename order on PostgreSQL 16
or newer, create private tables in `v7_private`, separate from the public Data API
schema:

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
an exact transaction-local `v7.tenant` setting. A bounded, fixed-search-path
`list_platform_tenant_keys` function returns tenant keys only for an unexpired
platform-admin management session. It does not relax tenant table policies or
expose business documents. Owner inventories remain scoped to their assigned and
owned businesses. `anon`, `authenticated` and
`service_role` have no access to the private schema. The non-login `v7_backend`
role cannot create schemas, bypass RLS or delete audit records. Global authentication
tables are accessible to that trusted backend role; they are not user-facing APIs.

The server authorizes management accounts before setting tenant context through
parameterized `SELECT set_config('v7.tenant', %s, true)` inside a transaction.
Public channel requests retain their signed conversation, origin or webhook
boundaries. A browser-supplied tenant ID is never management authorization. Tenant
document writes use a shared database lock; PostgreSQL staff approval commits the
account document and signup decision in that same transaction. Never use a
superuser or the migration-owner connection for normal application requests.
Owner signup also creates the workspace, account and approved request atomically;
a failed PostgreSQL transaction leaves no partial workspace.
Repository initialization is serialized per `Storage` instance, so concurrent
first requests reuse the same tenant transaction context. Connections themselves
remain isolated between requests.

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
5. Review and run all SQL migrations in filename order as the migration owner.
   Do not edit migrations already applied to a project. The importer requires
   schema versions 1–8; the separate transcription migration adds `audio_seconds`.
   Version 4 adds the gated tenant-key inventory. Version 5 preserves generated
   `_snapshot.json` provenance files in document history. Versions 6–8 add
   authentication hardening, trusted devices, and linked OAuth identities.

Official references: [database connections](https://supabase.com/docs/guides/database/connecting-to-postgres),
[SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement),
[securing data](https://supabase.com/docs/guides/database/secure-data).

## Rehearse the data copy

Obtain the actual current source files and quiesce all application and webhook
writers while retaining access to that filesystem. Do not stop or redeploy the
current Free Render instance to install an exporter. Follow
[LIVE_BACKUP.md](LIVE_BACKUP.md) to create and verify an independent protected copy
with `scripts/export_runtime.py`. Include the business tree, security and analytics
databases, CRM snapshot, audit records and any configured account registry. Keep
the live originals; a snapshot on the same disk is not an independent backup.

Install the import tooling dependency (also included in the runtime requirements):

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

Legacy SQLite analytics and CRM can contain uppercase tenant references while
business directory names preserve case. Preparation reconciles these references
only to a unique existing business and reports counts; orphan or ambiguous keys
stop migration. The protected raw backup remains unchanged.

The copy is transactional, checks row counts and content digests before committing,
and restores identity sequences. It refuses nonempty destinations and never
overwrites data. Reports contain counts, not credential values or business records.
An error prints its exception class only, because database error details can expose
rejected records. A failed import rolls back; schema preparation remains in place.

## Required before live cutover

- Keep source-only pushes from deploying the current Render Free service while
  its local account and business data remains unbacked. The service tracks
  `main`; automatic deploys are currently off. A database schema alone does not
  make its local files durable. Render Free does not provide Shell or SSH access
  for exporting those files. Obtain and verify a complete independent backup
  before the first deployment that changes the storage backend.
- Create a separate, restricted server login that inherits `v7_backend`, with no
  other role memberships, table ownership, DDL, superuser or RLS-bypass powers.
  Revoke database/schema CREATE privileges, including inherited PUBLIC grants.
  Configure it only as the server secret `V7_POSTGRES_DSN`; never reuse the
  migration-owner credential. Set `V7_SUPABASE_CA_FILE` when a project CA is needed.
  Runtime connections enforce `verify-full` even if the DSN requests weaker TLS.
- Run the disposable PostgreSQL checks below, then verify the actual Supabase
  connection, TLS and pooler behavior with the restricted role. Test auth, MFA,
  tenant boundaries, concurrent account writes, payment state, reports and voice
  accounting with isolated data before changing live configuration.
- Rehearse restore, back up the final frozen source, repeat the import into a clean
  destination and run `--verify-only`. Import preserves existing password hashes;
  new/reset managed passwords use scrypt and legacy bcrypt sign-in remains supported.
- Configure a sender on a domain verified by the mail provider. For Resend, the
  runtime uses its HTTPS Email API with the protected SMTP-compatible settings;
  MCP authorization alone does not configure Flask. See [registration](REGISTRATION.md).
- Only after these gates, deploy with `V7_STORAGE_BACKEND=postgres` and an imported
  `BUSINESS_KEY`. Startup checks required tables, forced RLS, restricted ownership,
  private Data API permissions, runtime additions and the default tenant. Missing
  or unsafe storage stops startup instead of creating a parallel local copy.
- Verify live signup email receipt, password/authenticator sign-in, owner/staff
  boundaries, web dictation and signed WhatsApp voice notes. Provider acceptance
  of an email does not prove inbox delivery; mocked audio tests do not prove
  microphone or WhatsApp delivery behavior.
- Keep the old source read-only after cutover. Rolling back after new PostgreSQL
  writes requires reconciling those writes; switching to an old snapshot would lose data.

## Checks

```sh
python -m pytest tests/test_supabase_preparation.py -q
python -m pytest tests/test_postgres_runtime.py tests/test_postgres_auth_runtime.py tests/test_postgres_reports.py tests/test_postgres_channels.py -q
```

Set `V7_TEST_POSTGRES_DSN` only to an **empty disposable test database**. The native
runtime fixtures require localhost/127.0.0.1 and a database name beginning
`v7_disposable_`; they create the schema and a restricted test login and refuse an
existing `v7_private` schema. Use a fresh database for the import and runtime
commands separately. Supply a trusted local TLS CA when required. Without the
test DSN these integration tests skip. They do not establish live Supabase network,
backup, pooler, email or external voice-delivery behavior.
