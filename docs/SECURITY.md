# Security and operations

These controls reduce risk; they are not a guarantee against compromise or a
certification of legal compliance. Live provider, infrastructure and dependency
security need deployment-specific review.

## Accounts and sessions

Management routes require a server-configured account. The implemented roles are
platform_admin and business_owner; the legacy admin role retains platform access.
Business owners are restricted server-side to their assigned company. There is
no staff role implementation or public registration.

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
password changes and role changes invalidate existing sessions.

Platform admins must configure an authenticator TOTP secret to log in when
BASE_URL uses HTTPS. TOTP codes allow one 30-second step of clock skew; a valid
code is not currently single-use within that window. Owners may configure TOTP.
There is no self-service account recovery or authenticator enrollment screen.
The environment admin fallback remains for compatibility; prefer the registry.

SECRET_KEY must be random and at least 32 characters. Cookies are HttpOnly,
SameSite=Lax and Secure when BASE_URL uses HTTPS. Management sessions expire
after eight hours and are revocable in SECURITY_DB_PATH. Logout revokes copied
session cookies. A shared SQLite login limiter allows five attempts per minute
per observed client IP. Ordinary request limits are process-local.

## Request and tenant boundaries

Management APIs, file access, analytics, CSV exports and diagnostics require
authentication and enforce the account's tenant scope. The platform company
inventory requires platform-admin access. Writes require CSRF tokens, except
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
match the configured phone ID.

For Twilio configure TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_NUMBER (including the
whatsapp: prefix). Signatures are checked with Twilio's validator against BASE_URL
and the callback path; recipient numbers must match.

WhatsApp currently belongs to BUSINESS_KEY for this deployment. It does not
provide independent phone/credential mappings for every company. Web chat
continues to work while WhatsApp is unconfigured.

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
The older test suite has stale imports and fixtures and must be reconciled
before it can act as a full release gate.
