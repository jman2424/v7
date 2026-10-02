# Vertex Seven security hardening — 2 October 2026

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
  formatter uses Black 26.3.1. Setuptools 83.0.0 replaces vulnerable preinstalled
  packaging tooling in the canonical runtime requirements. Actions and the official secret-scanner image are
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
- Follow-up Python dependency audit: **106 installed dependencies, zero advisories,
  zero skipped** in a fresh full development/runtime environment. A separate
  Python 3.11 Linux resolution audited **87 dependencies, zero advisories,
  zero skipped**. Console lockfile audit: **83 dependencies, zero
  vulnerabilities**. Runtime and dev dependencies are included.
- Backup/archive/scanner regressions: **73 passed, 1 Windows symlink skip**.
  URL fixture follow-ups: **129 passed**; their exact hostile values and
  assertions are preserved. All three workflow YAML files, 28 Action SHA pins,
  12 Bash blocks and eight release-tag cases passed targeted checks.
- Follow-up security regressions through the pytest 9.0.3 console entry:
  **297 passed, 1 PostgreSQL skip** across 14 directly relevant modules.
- Final executable console authentication/state regressions: **17 passed**;
  existing MFA/OIDC/trusted-device/signup/private-console subset: **131 passed**.
  Final combined Svelte check: **zero errors/warnings**; `/console` production
  build: **passed**.
- Follow-up pinned URI-pattern screening: zero matches across 390 publishable
  text files. GitHub security run `36893988511` completed the
  full TruffleHog scan with **zero findings**. CodeQL completed successfully
  and reported **28 open alerts**; its successful execution does not mean zero
  findings. Docker is unavailable locally. Semgrep was unavailable as described below.

## Sign-in and green branding fixes

Anonymous company deep links now prefill their validated company key, including
when the initial session request rejects a revoked cookie. Previously the form
could submit to `EXAMPLE` instead of the requested company.

The console previously required settings/catalog/offer reads after every successful
sign-in, so restricted staff could complete MFA and then receive a false login
error. Workspace loading now uses the account's server-derived permissions and
reports loading failures separately. Cached company data is cleared on sign-out
and before loading; responses from earlier accounts or workspace selections are
discarded. Executable component regressions and independent delayed-response
reproduction cover this client isolation boundary. Backend permissions and MFA
remain unchanged.

The homepage and console restore the established green palette while retaining
their current layout and configurable tenant widget colors. Both homepage demo
links now activate the existing delivery example, move keyboard focus to its
control and scroll to the conversation. The example remains explicitly labeled
as an illustrative fictional conversation. A local browser confirmed the updated
sample text, pressed/focused Delivery button and green computed styles.
The final `/console` build also passed browser owner/staff password and MFA
enrollment/sign-in, logout and tenant deep-link checks with disposable accounts.
Restricted staff reached the workspace without a false login error while private
settings and cross-tenant activation requests still returned HTTP 403.

These are local source and regression findings. The exact current live website
origin/error was not supplied; live sign-in has not been verified by these checks.

## CI and static-analysis follow-up

The first published CI run (`36893988453`) passed dependency installation,
Ruff, console checks/build and SDK tests, but failed pytest collection because
`tests.conftest` imported a test helper before adding the repository to `sys.path`.
The import now follows the existing path bootstrap; the pytest console entry
collects the suite successfully. The security audit identified vulnerable
preinstalled setuptools 79.0.1 (PYSEC-2026-3447); the canonical 83.0.0 pin fixes
the installer rather than excluding the finding from the audit.

CodeQL review identified three concrete improvements, each covered by hostile
input regressions:

- Account creation bounds email length before invoking its validation regex.
- Credentialed WhatsApp audio downloads reject raw controls, whitespace,
  backslashes and malformed URL ports/brackets before dispatch. Existing exact
  provider-host/path allowlists and redirect denial remain in force; no arbitrary
  host SSRF was reproduced. Signed Meta CDN query strings remain supported.
- Shared Stripe URL validation handles parser failures with its existing safe
  rejection result. Malformed provider netlocs cannot appear in public billing
  errors; checkout and portal preserve `stripe_response_invalid`.

The other reported flows were traced to bounded validation with fixed error
codes, digests of random high-entropy challenges, or intentionally issued secure
trusted-device proofs. No additional sensitive-data disclosure was established
in those paths. Alerts were not suppressed or dismissed; remaining static-analysis
findings require their normal review. This review does not establish that every
alert is a false positive.

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
- `ai_modes/v7_tool_runtime.py`
- `app/app_factory.py`
- `app/config.py`
- `app/logging_setup.py`
- `app/middleware.py`
- `app/routes/route_helpers.py`
- `connectors/sheets.py`
- `connectors/web_widget.py`
- `connectors/whatsapp_audio.py`
- `connectors/whatsapp.py`
- `dashboard/static/css/home.css`
- `dashboard/static/js/home.js`
- `dashboard/templates/home.html`
- `docs/LIVE_BACKUP.md`
- `docs/mcp.md`
- `docs/OPERATIONS.md`
- `docs/SECURITY_HARDENING.md`
- `docs/SECURITY.md`
- `docs/SUPABASE_MIGRATION.md`
- `frontend/src/app.css`
- `frontend/src/lib/AccountSecurity.svelte`
- `frontend/src/lib/AgentTest.svelte`
- `frontend/src/lib/AiParameters.svelte`
- `frontend/src/lib/ApiUsage.svelte`
- `frontend/src/lib/ConnectionSettings.svelte`
- `frontend/src/lib/Console.svelte`
- `frontend/src/lib/Conversations.svelte`
- `frontend/src/lib/ConversionSettings.svelte`
- `frontend/src/lib/CookiePreferences.svelte`
- `frontend/src/lib/ErrorsHealth.svelte`
- `frontend/src/lib/Implementation.svelte`
- `frontend/src/lib/JoinRequests.svelte`
- `frontend/src/lib/PerformanceStatistics.svelte`
- `frontend/src/lib/PlatformOverview.svelte`
- `frontend/src/lib/PrivacySettings.svelte`
- `frontend/src/lib/ProductStatistics.svelte`
- `frontend/src/lib/Registration.svelte`
- `frontend/src/lib/Statistics.svelte`
- `frontend/src/lib/Subscription.svelte`
- `frontend/src/lib/TrendChart.svelte`
- `frontend/src/lib/WhatsAppConnection.svelte`
- `frontend/src/lib/WhatsAppQr.svelte`
- `gunicorn.conf.py`
- `README.md`
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
- `service/subscriptions.py`
- `service/trusted_devices.py`
- `service/website_knowledge.py`
- `supabase/migrations/202609300001_totp_replay_protection.sql`
- `tests/conftest.py`
- `tests/test_account_management.py`
- `tests/test_account_mfa.py`
- `tests/test_api_second_pass.py`
- `tests/test_auth_second_pass.py`
- `tests/test_auth_session_security.py`
- `tests/test_billing_error_security.py`
- `tests/test_business_access.py`
- `tests/test_business_core.py`
- `tests/test_codeql_api_audio_followup.py`
- `tests/test_console_login_followup.py`
- `tests/test_main_security_boundaries.py`
- `tests/test_mcp_security_followup.py`
- `tests/test_mcp.py`
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
