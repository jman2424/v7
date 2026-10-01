# Vertex Seven security hardening — 1 October 2026

## Result and scope

This pass implements additional controls on current `main`, based on commit
`2331a086cb7c7637107e11111e9cced53b52be7b`, rebased onto
`1c0fa7d` when main advanced, preserving its Docker translation build fix and
migration documentation updates. It preserves Flask, both storage
runtimes, the owner console, mandatory MFA, multi-business ownership, activation,
MCP/REST, OIDC, trusted devices, privacy, business-core records, website chat,
per-tenant WhatsApp/audio and sales behavior.
Earlier security changes from the extracted workspace were ported where compatible
with current main. Existing stronger widget/prompt boundaries were retained.

This is implementation and regression evidence, not a guarantee against every
attack or a substitute for an independent penetration test.

## Highest-priority findings fixed

| Severity | Evidence and prior behavior | Change and regression coverage |
| --- | --- | --- |
| P0 | `service/security.py` assigned an unscoped `BUSINESS_USERS_JSON` account to the tenant requested at login. | Environment accounts need an explicit matching tenant. `test_auth_second_pass.py` denies omitted scope and cross-company login. Tenant-local records keep directory-derived scope. |
| P1 | Authentication could verify old credentials and stamp a session, MFA challenge or OAuth consent with a newer credential revision. Re-enabling a tenant account could revive unused old sessions. | Bind password proof to its original account snapshot, check the live revision before session/challenge/consent, and change a credential nonce on account updates. Race, permission, role, disable/re-enable and consent tests exercise real services. |
| P1 | The original combined password/TOTP login permitted reuse of an accepted authenticator step. Newer main already added atomic replay consumption. | Preserve that transaction and add a per-account high-water mark to reject older steps after newer ones. A private forced-RLS migration adds `totp_steps`; backup/import preserves both replay ledgers. |
| P1 | Management auditing imported nonexistent `services.audit` and swallowed the import error. | Use `service.audit`; require initial/prepared audit persistence before writes, lock document edits, record safe revisions and success outcomes. Audit-failure tests prove no pre-write mutation. |
| P1 | Meta batches dispatched early messages before later recipient/message validation. | Validate the complete signed envelope and all mappings before dispatch; mixed valid/invalid batches produce no partial send. HTTPS provider sends reject redirects and unsafe path/URL values. |

## Other controls implemented

- Explicit server permissions protect dashboard/file/analytics/model endpoints
  and all 37 MCP/REST tools, including composite projections. Staff receive no
  implicit tenant-data grants. Legacy owner records retain compatible defaults;
  explicit restrictions are versioned. MCP roles/users remain read-only and
  exclude platform-wide records.
- OAuth supports bounded connection listings and owner-scoped individual
  revocation. Token forms reject repeated/unknown fields and bodies over 8 KiB.
  RPC bodies use an actual-stream 64 KiB bound, strict JSON and bounded nesting.
- JSON/query validation rejects duplicate selectors/keys, non-finite values,
  floating-point overflow and excessive nesting. Raw editors require JSON content
  types, bounded settings and explicit supported fields. Both catalog formats
  remain available, including current stock/options fields in numeric catalogs.
- Public chat/actions use configured or safe local origins; a caller cannot
  approve its own Host/Origin pair. The configured global rate limit applies
  alongside dedicated chat, analytics and mutation buckets. Forwarded headers
  cannot choose limiter identity. Throttled responses include `Retry-After`.
- Conversation cursors/IDs remain local to the selected tenant in SQLite and
  PostgreSQL. Sheets rows require an exact nonblank tenant. Storage readers,
  snapshots, write locks and legacy loaders reject linked aliases/traversal;
  Windows device names are rejected.
- Signed catalog imports use server-selected tenant scope and durable replay
  suppression, validate all rows before write, record revisions and cannot replay
  a completed delivery to undo a later owner edit.
- Website fetching rejects malformed URLs, private translated/transition IPs,
  redirects and proxies, pins validated public destinations, and bounds page,
  read and total fetch time. Tests cover slow responses and unsafe addresses.
- Internal agent tools have an explicit read allowlist. MCP projections redact
  configured credentials, live bearer values and password hashes. Application
  exception logs omit raw messages/source lines; access logs omit query strings.
  Secret-bearing dataclass fields are excluded from representations.
- Complete SQLite backup/verify/restore validates contained paths, manifest
  uniqueness, checksums, size limits and database integrity before writes.
  Prepared restored state clears sessions/grants/challenges, trusted-device proofs
  and pending OIDC state, and preserves authenticator replay and linked OIDC
  accounts. Tenant archives require safe regular files. File
  backup/restore fails closed in PostgreSQL mode.
- Runtime pins update PyJWT to 2.15.0 and constrain oauthlib to 4.0.0; the dev
  formatter uses Black 26.3.1. Actions and the official secret-scanner image are
  immutable pins. CI retains lint/tests/builds and adds dependency/SDK checks.
  Release tags enter shell through validated environment variables, checkout
  credentials are not persisted and source archives contain tracked files only.

## Verification

- `python -m pytest` with isolated temporary data and JUnit output: **1,160
  passed, 35 skipped**, in 754.90 seconds. Local runtime: Python 3.13.2,
  pytest 9.0.3. The first full run found a real-time minute rollover in the
  rate-limit test; its clock is now fixed and the full rerun passes.
- Skips: 32 native PostgreSQL cases have no disposable `V7_TEST_POSTGRES_DSN`;
  two Windows symlink cases lack the OS permission, and one requires distinct
  directories differing only by case. These are not claimed as passing.
- `ruff check .`: passed with unchanged repository rules. `git diff --check`:
  passed. The native PostgreSQL concurrency hook was checked offline; this
  does not substitute for database integration execution.
- Console `npm run check`: zero errors/warnings; production `/console`
  `npm run build`: passed. Both widget SDK suites: **4 passed**.
- Final Python dependency audit: **78 resolved dependencies, zero advisories,
  zero skipped**. Final console lockfile audit: **83 dependencies, zero
  vulnerabilities**. Runtime and dev dependencies are included.
- Backup/archive/scanner regressions: **73 passed, 1 Windows symlink skip**.
  URL fixture follow-ups: **129 passed**; their exact hostile values and
  assertions are preserved. All three workflow YAML files, 28 Action SHA pins,
  12 Bash blocks and eight release-tag cases passed targeted checks.
- Local pinned URI-pattern screening: zero matches across 386 publishable text
  files. Docker is unavailable locally, so the full TruffleHog scanner and
  CodeQL run through GitHub CI after publication; their results are reported
  separately. Semgrep was unavailable as described below.

Focused tests cover Company A/B tenant selectors, permissions, account races,
MFA replay, OAuth refresh/revocation, all MCP tools, strict request parsing,
audit failure, signed webhook replay/batches, website fetching and restore safety.
All tests use isolated data; provider traffic is mocked.

## Credential exposure review

No confirmed live credential exposure was identified in the reviewed changes.
The previous CI secret scan reported four unverified URI findings in deliberately
hostile test URLs, using synthetic user/password values. The same URLs are now
constructed at runtime; rejection behavior and scanner rules remain unchanged.
Additional new fixtures were corrected the same way. No credential rotation was
identified as required from these findings. The final CI scanner result is
reported separately from the local URI-pattern screen.

## Deployment and remaining limitations

1. This push uses `[skip render]`. Preserve and verify the actual live data before
   any Render redeploy/restart; the existing Free instance has an ephemeral
   filesystem. Pushing these scripts does not obtain that data.
   [LIVE_BACKUP.md](LIVE_BACKUP.md) describes the recovery limitation.
2. Before a PostgreSQL deployment, apply the new
   `202609300001_totp_replay_protection.sql` migration after existing migrations.
   It adds schema version 9 and a private forced-RLS replay table. Import/export
   tooling preserves its state. No live database was changed by this pass.
3. The credential policy change requires management users to sign in and
   MCP/REST owners to consent again. Configure explicit staff grants and an
   explicit tenant for environment business accounts before deployment.
4. Native PostgreSQL integration tests need a named disposable local database
   via `V7_TEST_POSTGRES_DSN`; no production database is used for tests. Real
   ChatGPT linking, provider delivery and infrastructure recovery still require
   controlled deployment verification.
5. Ordinary IP limits and conversation memory are process-local. Global backend
   security tables are accessible only to the trusted restricted backend role;
   they are not exposed through Supabase Data API. Keep forced RLS and TLS intact.
6. File replacement and filesystem audit append are separate operations. A
   post-write audit failure can leave a prepared record and uncertain response;
   compare the document revision before retrying. Backup restores are atomic per
   file, not across the entire platform; stop all writers and rehearse recovery.
7. Semgrep CLI was unavailable because the Windows certificate-store integration
   failed. TLS verification was not disabled. CI CodeQL/secret checks are separate;
   dependency audits and regression tests do not establish complete security.

See [SECURITY.md](SECURITY.md), [MCP.md](MCP.md),
[OPERATIONS.md](OPERATIONS.md) and [SUPABASE_MIGRATION.md](SUPABASE_MIGRATION.md)
for behavior and recovery procedures.

## Files changed

- `.dockerignore`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `.github/workflows/security.yml`
- `.gitignore`
- `README.md`
- `ai_modes/v7_tool_runtime.py`
- `app/app_factory.py`
- `app/config.py`
- `app/logging_setup.py`
- `app/middleware.py`
- `app/routes/route_helpers.py`
- `connectors/sheets.py`
- `connectors/web_widget.py`
- `connectors/whatsapp.py`
- `docs/LIVE_BACKUP.md`
- `docs/OPERATIONS.md`
- `docs/SECURITY.md`
- `docs/SECURITY_HARDENING.md`
- `docs/SUPABASE_MIGRATION.md`
- `docs/mcp.md`
- `gunicorn.conf.py`
- `requirement.txt`
- `requirements-dev.txt`
- `requirements.txt`
- `retrieval/storage.py`
- `routes/admin_api_routes.py`
- `routes/analytics_routes.py`
- `routes/auth_routes.py`
- `routes/catalog_routes.py`
- `routes/conversion_routes.py`
- `routes/diag_routes.py`
- `routes/files_routes.py`
- `routes/health_routes.py`
- `routes/mcp_oauth_routes.py`
- `routes/mcp_routes.py`
- `routes/mode_routes.py`
- `routes/model_settings_routes.py`
- `routes/privacy_routes.py`
- `routes/webchat_routes.py`
- `routes/whatsapp_routes.py`
- `schemas/catalog-sheet.schema.json`
- `scripts/backup_utils.py`
- `scripts/manage_account.py`
- `scripts/platform_backup.py`
- `scripts/prepare_supabase.py`
- `scripts/restore_snapshot.py`
- `scripts/snapshot_backup.py`
- `sdk/js/package.json`
- `sdk/js/security.test.js`
- `sdk/js/tests/security.test.js`
- `service/account_mfa.py`
- `service/account_service.py`
- `service/audit.py`
- `service/business_management.py`
- `service/business_validation.py`
- `service/mcp_auth.py`
- `service/mcp_tools.py`
- `service/security.py`
- `service/session_store.py`
- `service/storage_readiness.py`
- `service/trusted_devices.py`
- `service/website_knowledge.py`
- `supabase/migrations/202609300001_totp_replay_protection.sql`
- `tests/conftest.py`
- `tests/test_account_mfa.py`
- `tests/test_api_second_pass.py`
- `tests/test_auth_second_pass.py`
- `tests/test_auth_session_security.py`
- `tests/test_business_access.py`
- `tests/test_business_core.py`
- `tests/test_main_security_boundaries.py`
- `tests/test_mcp.py`
- `tests/test_mcp_security_followup.py`
- `tests/test_model_security_followup.py`
- `tests/test_model_settings.py`
- `tests/test_ops_second_pass.py`
- `tests/test_postgres_auth_runtime.py`
- `tests/test_privacy_permission_followup.py`
- `tests/test_privacy_settings.py`
- `tests/test_request_hardening.py`
- `tests/test_settings_security_followup.py`
- `tests/test_supabase_preparation.py`
- `tests/test_trusted_devices.py`
- `tests/test_vertex_api.py`
- `tests/test_website_import_security.py`
- `tests/test_whatsapp_configuration.py`
- `tests/test_whatsapp_security_followup.py`
