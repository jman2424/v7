# Security and operations

These controls reduce risk; they are not a guarantee against compromise or a
certification of legal compliance. Live provider, infrastructure and dependency
security need deployment-specific review.

## Accounts and sessions

Management routes require an authenticated account. The implemented roles are
platform_admin, business_owner and business_staff; the legacy admin role retains
platform access. Staff are restricted server-side to their assigned company.
Owners can manage their assigned company and additional businesses they create.
Ownership is recorded by account ID, email and home tenant in the private security
database; clients cannot assign ownership or activate a business. Owners can
manage staff in those businesses; only platform operators can manage owners.
Public registration requires email verification; tenant join requests additionally
require owner approval. See [Registration](REGISTRATION.md) for mail setup.
Account creation and sign-in accept email addresses up to 254 characters;
managed-account creation validates ASCII mailbox syntax. New and reset managed
passwords use scrypt. Existing bcrypt hashes remain supported for sign-in,
including `ADMIN_PASSWORD_HASH` and the protected operator registry. The console
accepts existing usernames as well as email addresses; public signup still requires
an email address. The anonymous session response supplies the configured default
company key, while a valid company key in a sign-in link takes precedence.

Staff have no API cost or subscription access by default. Owners grant the
independent `view_costs` and `view_subscriptions` permissions through Team access.
Subscription access for staff is read-only; checkout, customer portal, invoice
payment links and subscription changes remain owner/operator-only. Subscription
reports omit API invoices, usage and their totals without `view_costs`.
Permission changes revoke existing sessions and require a fresh sign-in with 2FA.

Staff also need explicit grants for tenant reads and writes. Server-side checks
apply to dashboard APIs, file editors, model settings, diagnostics, MCP and REST.
Owner accounts can carry a restricted permission set; legacy tenant owner records
without the permission-version marker keep their previous owner permissions.
Registry accounts use their explicit grants. Environment business accounts must
specify their tenant; a login request cannot supply missing account scope.

New business data editing, team changes, the agent, public widget
and WhatsApp processing require an active platform subscription, a confirmed paid
platform invoice, and confirmed implementation payment. Only verified Stripe
events and canonical Stripe responses update that ledger. Test-agent requests
also respect activation. Existing businesses without an onboarding record retain
their previous operation. An inactive/past-due subscription stops a managed
business again. Test Stripe payments satisfy these checks in a test deployment.
Ownership, activation and billing use `SECURITY_DB_PATH` with SQLite, or private
PostgreSQL tables when `V7_STORAGE_BACKEND=postgres`. Preserve the active storage
with the business data. Never delete it to reset onboarding.

For a SQLite deployment, or to prepare the protected registry before PostgreSQL
import, run from the repository root:

```bash
python scripts/manage_account.py operator@example.com --role platform_admin
python scripts/manage_account.py owner@example.com --tenant TARIQ
python scripts/manage_account.py owner@example.com --disable
```

Set ADMIN_USERS_FILE to the resulting registry's absolute path. Passwords are
entered interactively and stored as Werkzeug scrypt hashes. Never commit the
registry. Restrict its filesystem permissions to the service operator. Store it
outside business and dashboard directories. Account removal, disabling,
password changes and role changes invalidate existing sessions. Existing
BUSINESS_USERS_JSON and tenant-managed bcrypt accounts remain supported.
Tenant accounts can be managed on the console's Team access page.
PostgreSQL uses the imported `operator_accounts` rows instead of rereading this
registry file; editing a local registry after cutover does not update those rows.

All management accounts (platform administrator, business owner and staff) must
enroll an authenticator in every environment. Sign-in requires a verified first
factor and either authenticator verification or a valid opted-in device proof. A correct
password with no enrolled authenticator starts a five-minute enrollment challenge
and returns a locally generated QR code. Until a valid code is confirmed, no
management session or tenant data is available. Existing configured TOTP secrets
are preserved; they never appear in setup responses. The retired `/admin/login` endpoint redirects
to `/console/` without processing or forwarding credentials. The console uses
the CSRF-protected `/auth` endpoints for enrollment and verification. Old dashboard
URLs preserve account and tenant authorization before redirecting signed-in users.

Only an opaque challenge token and CSRF token enter the signed cookie. Pending
secrets and enrolled authenticators live in the private security database
(`SECURITY_DB_PATH` with SQLite, `v7_private` with PostgreSQL).
Treat that database as credential storage: use persistent storage,
restrict access, and include it in protected backups. Enrollment allows five
attempts and also shares the server login rate limit. Challenges are single-use,
bound to the browser and account credential revision, and cannot replace an
existing authenticator. Logout revokes the pending server challenge. Disabling
or changing the account invalidates the challenge before any setup key is returned.
Existing sessions must sign in again after this policy upgrade. A TOTP permits
one time step of clock skew. Each accepted account/secret/time-step combination
is consumed atomically with enrollment or session creation, including legacy
combined password/code login, so a concurrent or repeated submission cannot reuse it.

### Trusted devices

After successful authenticator verification, a user may explicitly trust a personal
device for 30 days. This skips the authenticator on a subsequent successful password
sign-in or fully verified sign-in from an explicitly linked provider. It does not
silently sign in, remove the password requirement from password sign-in, or extend
the normal session lifetime. Trust expires 30 days after verification; use never
extends that absolute expiry.

The high-entropy proof is a host-only, HttpOnly, SameSite=Lax cookie, Secure with
the production session-cookie setting. Only its SHA-256 hash is stored in the private
`trusted_devices` table. Proofs require the same canonical account, an enrolled
authenticator and the current credential revision. Accepted proofs rotate atomically
with session creation; the previous value cannot be replayed. Explicit logout revokes
the current proof, and managed-account edits revoke that account's proofs. Registry
and environment credential changes invalidate proofs through their revision.

The account security page uses authenticated `GET /auth/devices` to show only the
own-account device count, absolute expiry and current-device status. CSRF-protected
`DELETE /auth/devices` revokes all own-account proofs, including this browser's cookie.
It leaves existing authenticated sessions active until expiry or logout. Normal
session expiry alone preserves an unexpired device proof. Device proofs and spent
authenticator codes are security state and must be preserved in complete backups.
Accepted authenticator steps also have a per-account high-water mark, so an older
step cannot be reused after a newer one. Preserve replay state in backups.
Password verification, pending MFA and OAuth consent are bound to the exact
credential revision verified at the beginning of authentication. Account changes
cannot turn an earlier password proof into a session for newer credentials.

Apply `supabase/migrations/202609300001_totp_replay_protection.sql` (schema version 9)
before starting the updated PostgreSQL runtime. SQLite creates this private table
on first use. The credential policy upgrade invalidates existing management
sessions and MCP/REST grants; sign in and consent again after deployment.

There is no unauthenticated MFA reset. Losing an existing
authenticator requires operator recovery through the server's protected account
configuration. Do not delete the security database as an account recovery method.

### A correct password is followed by Forbidden

A correct password now returns an HTTP 202 verification/enrollment challenge.
Complete it in the console. Invalid passwords still return `invalid_credentials`.
Local preview accounts exist only on localhost and cannot sign in on Render.

For the environment admin, generate a private Base32 TOTP secret locally,
add that key to your authenticator as a time-based account, and save the same
key as `ADMIN_TOTP_SECRET` in the service's environment. Keep the existing
`ADMIN_USERNAME`. Production HTTPS login requires `ADMIN_PASSWORD_HASH`; hash
the existing password with the account-management tool before deployment if
only `ADMIN_PASSWORD` is configured. Plaintext password compatibility is limited
to local HTTP development. After the live-data backup and deployment steps,
use the same password and the authenticator's six-digit code.
Do not use an online QR-code generator or commit the setup key.

A `csrf_failed` response means the sign-in page expired or its session cookie
was blocked. Reload the page and allow site cookies. The console refreshes an
expired authenticated cookie before submitting a new login.
Sign-in links retain their valid company key. The console loads only workspace
data permitted by the authenticated account and clears cached company data before
loading or signing out. Workspace loading failures are reported separately from
successful authentication.
Password, authenticator and provider failures show guidance for company keys,
expired cookies, consumed codes and rate limits. Unknown server failures use a
generic message; internal provider details are never copied into sign-in errors.
Session-loading failures are shown on the sign-in page.
Console navigation and sign-in redirects respect the account's explicit read
grants. Accounts without workspace read access open Account & security. Optional
model and conversion panels require their own permitted reads.

SECRET_KEY must be random and at least 32 characters. Cookies are HttpOnly,
SameSite=Lax and Secure when BASE_URL uses HTTPS. Management sessions expire
after eight hours and are revocable in the configured security database. Logout
revokes copied session cookies. A shared database login limiter allows five
attempts per minute per observed client IP. A separate shared account limiter reserves
password and MFA attempts atomically across workers, browsers, challenges and client
addresses. Its defaults are eight attempts per 900 seconds, configurable with
`AUTH_LOGIN_MAX_ATTEMPTS` and `AUTH_LOGIN_WINDOW_SECONDS`. Correct passwords alone
do not clear failures; successful MFA or validated device proof does. Account failure
subjects are HMAC digests, without raw email or client address keys. Ordinary request
limits are process-local.
Chat, analytics and management writes have additional bounded buckets; none bypass
a stricter configured global limit. Forwarded headers cannot choose a rate-limit key.

## Request and tenant boundaries

Management APIs, file access, analytics, CSV exports and diagnostics require
authentication and enforce the account's tenant scope. The platform company
inventory is filtered to the owner's businesses; the all-company operational
overview requires platform-admin access. Writes require CSRF tokens, except
public chat and separately signed integration webhooks. Business files use
allowlisted names, path containment checks, validation and pre-edit snapshots.
CSV exports neutralize formula-leading values.

Private console HTML sections and their `.html` aliases enforce account and tenant
authorization before serving the page. Platform, company/team, cost and subscription
sections also enforce their respective roles or permissions. The sign-in page and
static JS/CSS remain public; anonymous private-page redirects use allowlisted section
names and validated company keys. Account/security and privacy remain available to
authenticated inactive businesses. On SQLite, directory aliases resolve to the unique
actual tenant key before authentication; legacy alias authenticator records are reused
unchanged, and conflicting saved secrets fail closed.

JSON requests reject duplicate keys, non-finite or overflowed numbers and excessive
nesting. Repeated query selectors are rejected. MCP and REST bodies are bounded at
64 KiB; OAuth token forms are bounded at 8 KiB and reject repeated/unknown fields.
Raw-file editors require JSON content types and validate settings field allowlists.
Tenant files, legacy loaders, audit reads and snapshots reject symlink/junction
aliases, traversal and Windows device names. Spreadsheet imports require an exact,
nonblank tenant column; blank rows do not become shared tenant data.
Offline backup, export, restore and import preparation check junction metadata
before resolving paths, including on Windows Python 3.11.

Management writes record an attempt before mutation; document edits also record
prepared revisions and a success outcome. Audit preparation failure blocks the
write. Filesystem replacement and the audit append are separate operations: if
success logging fails after replacement, inspect the prepared revision before
retrying. Do not assume an error means no write occurred.

Signed catalog imports use the deployment's server-selected business, validate
bounded rows and persist delivery digests before processing. Completed replays
return the prior result and cannot undo later owner edits. Request tenant selectors
are not accepted for signed imports.

PostgreSQL tenant document mutations use a database lock shared by workers.
Staff-request approval commits the new account document and request status
together; failure rolls back both. Concurrent account edits use the same tenant
lock. Owner signup commits its workspace, owner account and approved request in
one transaction. These controls supplement account authorization and CSRF checks.
Owner signup also commits its tenant, account, ownership and approved request
together in PostgreSQL; a failed final approval leaves the request retryable.

PostgreSQL connections require a separate restricted login inheriting only
`v7_backend`, verified TLS, and transaction-local tenant context. All private
tables have forced RLS; Supabase Data API roles have no private-schema access.
The platform inventory function returns only bounded pages of tenant keys for
an unexpired administrator session, with a fixed `pg_catalog` search path.
Owners continue listing only their assigned and owned businesses. Startup
rejects missing or unsafe database objects and never falls back to local files.
See [PostgreSQL setup and migration](SUPABASE_MIGRATION.md).

Management responses disable caching and framing. The content security policy
uses local scripts or per-request nonces. Each widget's allowed_origins controls
browser origins and iframe ancestors. Origin checks do not authenticate
customers or prevent non-browser callers from using public chat.

Web conversations use server-generated identities and tenant-bound signed
continuation tokens with a 24-hour lifetime. Do not put private internal material
in a customer-facing agent's catalog, FAQs or other retrievable business data.
Company management data and credentials must remain outside that public corpus.

## Optional WhatsApp

Routes remain available at GET/POST /whatsapp/webhook and GET/POST
/whatsapp/status. Unconfigured webhooks fail closed with 503.

For Meta configure WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN, WHATSAPP_TOKEN,
WHATSAPP_PHONE_ID and the appropriate WHATSAPP_API_URL for your provider setup.
POST signatures use X-Hub-Signature-256 over the original request body. The
verification handshake checks the configured token. Incoming recipient IDs must
match the configured phone ID or an explicit WHATSAPP_TENANT_MAP_JSON entry.

For Twilio configure TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_NUMBER (including the
whatsapp: prefix). Signatures are checked with Twilio's validator against BASE_URL
and the callback path; recipient numbers must match the configured number or
an explicit server-side mapping.

WHATSAPP_TENANT_MAP_JSON maps incoming business phone IDs or Twilio recipient
numbers to tenant keys. When present, unknown recipients are rejected. Without
a mapping, only the configured recipient is assigned to BUSINESS_KEY. Provider
credentials are shared by this deployment; arbitrary per-tenant credentials
are not supported. Web chat continues to work while WhatsApp is unconfigured.

Provider message IDs are deduplicated in the configured security database for
seven days.
The entire signed Meta message batch, including every recipient mapping, is
validated before any message dispatch. Malformed later entries cannot partially
dispatch earlier messages. Outbound sends require validated HTTPS URLs and do not
follow redirects carrying provider credentials. Repeated Twilio form fields fail
validation.
Completed Twilio replies can be replayed safely; failed processing can retry.
This does not guarantee exactly-once external delivery if a process crashes
after a provider accepts a send but before completion is recorded.
Voice-note downloads are limited to authenticated provider media URLs and 10 MiB.
The source webhook signature and recipient-to-tenant mapping are checked before
audio is fetched. V7 keeps audio in memory for transcription and logs only the
transcribed text under the existing conversation retention rules.

## Deployment requirements and limitations

- Use HTTPS and set BASE_URL to the exact externally reachable origin.
- With SQLite, persist business data, snapshots, account registry, both databases
  and the CRM snapshot. With PostgreSQL, back up the complete private schema and
  retain protected service configuration. Both contain private information.
- The current Free Render deployment has not completed PostgreSQL cutover.
  Obtain a verified independent export of its actual live files before any
  deployment/restart that could discard them. [LIVE_BACKUP.md](LIVE_BACKUP.md)
  describes the offline exporter and current recovery limitations.
- Public signup requires a sender domain verified by the mail provider and
  protected runtime mail credentials. Resend MCP authorization alone does not
  configure delivery. Verify real email receipt before opening signup.
- The default Gunicorn worker count is one because conversation memory is
  process-local. Shared session storage does not make agent memory distributed.
- Configure trusted proxy addresses explicitly. The application does not trust
  arbitrary X-Forwarded-For headers; behind a proxy clients may share its rate
  limit until trusted client-IP handling is configured.
- Conversations and leads contain personal data and currently have no automatic
  retention/deletion policy. Define retention and operating procedures before
  handling real customer data.
- Review dependencies, hosting, backups, incident response and access policies
  before launch. No independent penetration test has been performed.
- Live OpenAI, WhatsApp delivery and microphone behavior require configured
  services and end-to-end checks. Local regression tests use isolated data and
  mocked provider calls.

## Checks

```bash
python -m pytest tests/test_platform_security.py tests/test_whatsapp_security.py
```

These tests exercise real Flask authentication, CSRF, tenant isolation, file
validation, session revocation, webhook signatures and duplicate handling.
The full regression suite also covers existing sales, account-management,
tenant configuration and console asset routes. Run it with `python -m pytest`.
Frontend checking and a production console build are separate release checks.


## September 2026 hardening

- The standalone widget SDK restricts outbound messages to the configured chat origin
  and accepts incoming events only from that origin and the current iframe window.
  HTTP(S) URLs with no embedded credentials are required. Run `npm test` in `sdk/js`.
- Production requests accept the hostname from BASE_URL and, on Render, the platform's
  RENDER_EXTERNAL_HOSTNAME. Keep BASE_URL set to the actual public console origin;
  other custom domains must not be used as console entry points without configuration.
  Development localhost previews retain their existing host behavior.
- Management writes reject cross-site Fetch Metadata and foreign/null Origin headers,
  even with a CSRF token. This adds a browser boundary; CSRF tokens, authentication,
  roles and tenant checks remain mandatory. Signed provider webhooks and public chat
  keep their separate signature/origin controls.
- Sign-in field sizes are bounded before expensive password verification. Missing MFA
  secrets fail verification. Password plus authenticator remains the login method;
  Google/OAuth login was not added.
- Raw-file offer writes now enforce the same business constraints as the Offers API.
- Python security updates: Flask 3.1.3, Requests 2.33.0, python-dotenv 1.2.2,
  PyJWT 2.15.0 and pytest 9.0.3, based on the local pip-audit findings.

Use `pytest tests/test_request_hardening.py` alongside the existing security suites.
Dependency and static scans supplement these tests; they do not establish that every
possible attack is prevented. Hosting access, backups and provider secrets remain
operator responsibilities.
