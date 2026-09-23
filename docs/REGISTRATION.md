# Verified account creation

The console sign-in page offers **Create an account or request to join**.
Public signup is disabled until SMTP is configured. Existing sign-in is unaffected.

## Server configuration

Set these as deployment secrets; never commit credentials:

- `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`: required.
- `SMTP_TLS_MODE`: `starttls` (default) or `ssl`. Plaintext SMTP is unsupported.
- `SMTP_PORT`: default 587 for STARTTLS, 465 for TLS.

The server validates TLS certificates and authenticates before sending. Configure
the sender domain with your email provider. SMTP delivery has not been verified
until real provider configuration is supplied. There is no development-code fallback.

For an existing Render service, add the four required `SMTP_*` settings in
the service's Environment settings and redeploy. The `render.yaml` entries prompt
for secrets when creating a new Blueprint, but Render does not add `sync: false`
values to an existing service during a Blueprint update. Use a verified sender
address or domain accepted by your mail provider. If sending fails, the signup
endpoint returns 503 and the server log records the exception type without the
email address, password, or code. A failed send can be retried without waiting
for the email cooldown; an accepted send still has the normal 60-second limit.

## Access model

1. An applicant submits email, password, company key and either owner or join.
2. A code is emailed, valid for ten minutes and five attempts. The browser receives
   only an opaque request ID. Passwords use scrypt; codes use keyed hashes.
3. Verified owners receive a clean, payment-gated workspace. They must sign in with
   password and authenticator, then pay through Subscription. Business data edits,
   team management and agent use unlock only after verified Stripe payment records.
4. Verified join requests appear in the tenant owner's **Team access** section.
   Approval creates `business_staff` with no cost or subscription permissions.
   Rejection creates no account. Applicants can refresh signup status to check the
   decision; decision emails are not currently sent. Pending requests expire in 30 days.
5. Approved staff must also complete password and authenticator verification.

Owners cannot approve requests for other businesses. Client-supplied roles,
permissions or payment flags cannot grant access. CSRF, same-origin checks and
shared login throttling protect signup mutations; email requests also have a
60-second cooldown and a five-per-day limit per address. Codes cannot be replayed.

`service/registration.py` holds the workflow, `registration_mail.py` sends mail,
`routes/auth_routes.py` exposes signup, and the admin API handles owner decisions.
Registration records use the private `SECURITY_DB_PATH` database; credentials are
cleared on expiry, rejection or completion. Keep this database and business files
on durable, access-restricted storage together. Operator recovery is required if
workspace creation is interrupted between filesystem publication and status update.

Checks: `python -m pytest tests/test_registration.py tests/test_business_access.py -q`
and, from `frontend`, `npm run check` and `npm run build`.
