# Security and operations

These controls reduce risk; they are not a guarantee against compromise or a
certification of legal compliance. Live provider, infrastructure and dependency
security need deployment-specific review.

## Accounts and sessions

Management routes require a server-configured account. The implemented roles are
platform_admin, business_owner and business_staff; the legacy admin role retains
platform access. Staff are restricted server-side to their assigned company.
Owners can manage their assigned company and additional businesses they create.
Ownership is recorded by account ID, email and home tenant in the private security
database; clients cannot assign ownership or activate a business. Owners can
manage staff in those businesses; only platform operators can manage owners.
There is no public registration.

Staff have no API cost or subscription access by default. Owners grant the
independent `view_costs` and `view_subscriptions` permissions through Team access.
Subscription access for staff is read-only; checkout, customer portal, invoice
payment links and subscription changes remain owner/operator-only. Subscription
reports omit API invoices, usage and their totals without `view_costs`.
Permission changes revoke existing sessions and require a fresh sign-in with 2FA.

New businesses are editable while awaiting activation. The agent, public widget
and WhatsApp processing require an active platform subscription, a confirmed paid
platform invoice, and confirmed implementation payment. Only verified Stripe
events and canonical Stripe responses update that ledger. Test-agent requests
also respect activation. Existing businesses without an onboarding record retain
their previous operation. An inactive/past-due subscription stops a managed
business again. Test Stripe payments satisfy these checks in a test deployment.
Ownership, activation and billing use `SECURITY_DB_PATH`; preserve it with the
business files on durable storage. Never delete it to reset onboarding.

Run from the repository root:
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

All management accounts (platform administrator, business owner and staff) must
complete password and authenticator verification in every environment. A correct
password with no enrolled authenticator starts a five-minute enrollment challenge
and returns a locally generated QR code. Until a valid code is confirmed, no
management session or tenant data is available. Existing configured TOTP secrets
are preserved; they never appear in setup responses. The retired `/admin/login` endpoint redirects
to `/console/` without processing or forwarding credentials. The console uses
the CSRF-protected `/auth` endpoints for enrollment and verification. Old dashboard
URLs preserve account and tenant authorization before redirecting signed-in users.

Only an opaque challenge token and CSRF token enter the signed cookie. Pending
secrets and enrolled authenticators live in the private `SECURITY_DB_PATH` SQLite
database. Treat that database as credential storage: use persistent storage,
restrict access, and include it in protected backups. Enrollment allows five
attempts and also shares the server login rate limit. Challenges are single-use,
bound to the browser and account credential revision, and cannot replace an
existing authenticator. Existing sessions must sign in again after this policy
upgrade. A TOTP permits one time step of clock skew; reuse within that short
window is not currently prevented for the legacy combined password/code login.

There is no public registration or unauthenticated MFA reset. Losing an existing
authenticator requires operator recovery through the server's protected account
configuration. Do not delete the security database as an account recovery method.

### A correct password is followed by Forbidden

A correct password now returns an HTTP 202 verification/enrollment challenge.
Complete it in the console. Invalid passwords still return `invalid_credentials`.
Local preview accounts exist only on localhost and cannot sign in on Render.

For the environment admin, generate a private Base32 TOTP secret locally,
add that key to your authenticator as a time-based account, and save the same
key as `ADMIN_TOTP_SECRET` in the service's environment. Keep the existing
`ADMIN_USERNAME` and `ADMIN_PASSWORD` / `ADMIN_PASSWORD_HASH` unchanged.
Redeploy, then use the same password and the authenticator's six-digit code.
Do not use an online QR-code generator or commit the setup key.

A `csrf_failed` response means the sign-in page expired or its session cookie
was blocked. Reload the page and allow site cookies. The console refreshes an
expired authenticated cookie before submitting a new login.

SECRET_KEY must be random and at least 32 characters. Cookies are HttpOnly,
SameSite=Lax and Secure when BASE_URL uses HTTPS. Management sessions expire
after eight hours and are revocable in SECURITY_DB_PATH. Logout revokes copied
session cookies. A shared SQLite login limiter allows five attempts per minute
per observed client IP. Ordinary request limits are process-local.

## Request and tenant boundaries

Management APIs, file access, analytics, CSV exports and diagnostics require
authentication and enforce the account's tenant scope. The platform company
inventory is filtered to the owner's businesses; the all-company operational
overview requires platform-admin access. Writes require CSRF tokens, except
public chat and separately signed integration webhooks. Business files use
allowlisted names, path containment checks, validation and pre-edit snapshots.
CSV exports neutralize formula-leading values.

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

Provider message IDs are deduplicated in SECURITY_DB_PATH for seven days.
Completed Twilio replies can be replayed safely; failed processing can retry.
This does not guarantee exactly-once external delivery if a process crashes
after a provider accepts a send but before completion is recorded.

## Deployment requirements and limitations

- Use HTTPS and set BASE_URL to the exact externally reachable origin.
- Persist business data, snapshots, account registry and both SQLite databases.
  Back up and restrict access to them; they contain private information.
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
