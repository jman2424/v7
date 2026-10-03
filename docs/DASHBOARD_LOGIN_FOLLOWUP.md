# Login and dashboard follow-up — 3 October 2026

This change preserves existing account identities, tenant boundaries, MFA, CSRF,
permissions, activation and the current Flask/Svelte architecture.

## Login and account creation

- The console now accepts existing usernames. Its previous email-only input could
  stop an `ADMIN_USERNAME` such as a non-email operator name before a request reached Flask.
- Anonymous sign-in uses the server's configured default company key instead of
  always showing `EXAMPLE`. A valid company key in a supplied URL takes precedence.
- Operator environment and registry sign-in now use the existing bcrypt/scrypt
  verifier. Existing bcrypt hashes previously failed the scrypt-only operator path.
  Password verification still grants no access until MFA succeeds. Wrong passwords,
  disabled identities and tenant/permission checks retain their existing controls.
- Signup requests stop waiting after 20 seconds, covering headers and the body.
  Leaving the form aborts requests. The status action checks the existing request
  before a user submits again; submissions are never retried automatically.

Public signup still requires configured verification mail. Both previously inspected
hosted services reported signup disabled and Google/Microsoft unconfigured. Existing
production admin setups containing only `ADMIN_PASSWORD` must migrate that same
password to `ADMIN_PASSWORD_HASH`; plaintext production sign-in stays disabled.
No credentials, MFA records or live environment settings were changed in this pass.

The user confirmed `v7-sales-agent.onrender.com`. A fresh read of its public
registration/provider status also reported `enabled=false`, no sender, and both
providers unconfigured. The valid supplied route is
`/console/?next=branches&tenant=EXAMPLE`; concatenating the whole URL into the
company-key query does not produce a valid company key.

## Delays and design

- Console data loads per section. In the synthetic full-permission owner case,
  opening Sales pipeline requests activation, insights and the company list: three
  requests instead of the former twelve. The independent company list does not
  hold up the current page. Loaded editor data survives same-company navigation.
- Pending reads are canceled on tenant changes, logout and component destruction.
  Current-page reads have 20-second bounds. Failed/partial reads leave editing
  disabled until retry succeeds; retries keep successfully loaded resources.
- Conversations, statistics and health reads discard stale/destroyed requests,
  report timeouts, and allow another attempt. Statistics reload when the tenant
  changes even if period/channel filters remain the same.
- Navigation groups related tasks and preserves permission checks. Cost metrics
  precede model configuration. Table regions support keyboard scrolling, and
  conversation/overview pages show clearer progress, counts and empty states.
  Green remains the shared brand colour; tenant widget branding remains configurable.
- Currency refresh no longer holds the process lock or a database connection during
  public networking. Concurrent readers use the saved reference and its stale marker.
  An empty usage report reads the cache without contacting the provider. Missing
  reference rates do not become invented paid costs. Malformed, boolean, oversized
  and excessively nested provider responses preserve the last valid rate.

## Verification and live status

Regression tests execute the actual console/component TypeScript with controlled
HTTP and timers, plus real Flask authentication/CSRF/MFA and event-controlled
SQLite/mocked-PostgreSQL rate concurrency. The PostgreSQL concurrency test models
connection leasing; it is not a live database performance measurement.

Relevant checks are pytest, Ruff, Svelte check and the production console build.
The local full suite passed with 1,318 passed and 35 skipped. The skips require a
disposable PostgreSQL database (32), OS symlink permission (2), or a case-sensitive
filesystem (1). Final loading changes were checked separately: 58 login/workspace
scenarios passed, followed by all 13 workspace scenarios after the last role update.
Ruff passed; Svelte check reported zero errors and warnings; the production build
passed. The final repository contains 1,356 collected tests. CI results for the
published commit are recorded in the separate verification report.
Browser verification for this follow-up was blocked by automatic approval review
because its usage limit was reached. No replacement browser surface was used.

The live deployment hold remains: existing ephemeral business/security/analytics
data must be preserved and recovery confirmed before deployment or environment
changes. A push to `main` is not evidence that either hosted service is updated or
that live credentials/email delivery work. See [LIVE_BACKUP.md](LIVE_BACKUP.md),
[SECURITY.md](SECURITY.md) and [REGISTRATION.md](REGISTRATION.md).

## Files changed

- `frontend/src/lib/Console.svelte`, `ApiUsage.svelte`, `Conversations.svelte`,
  `ErrorsHealth.svelte`, `PlatformOverview.svelte`, `Registration.svelte`, `Statistics.svelte`
- `routes/admin_api_routes.py`, `routes/auth_routes.py`
- `service/security.py`, `service/usage_currency.py`
- `tests/test_console_login_followup.py`, `test_console_workspace_loading.py`,
  `test_dashboard_delay_security.py`, `test_dashboard_loading_followup.py`,
  `test_login_compatibility.py`, `test_registration_console_loading.py`
- `docs/SECURITY.md`, `docs/REGISTRATION.md`, this report
