# Security and Access Control

## Overview
This system implements multiple layers of protection to safeguard tenant data and prevent unauthorized access.

---

## Authentication
- Admin access uses username/password + **TOTP** (Time-based One-Time Password) via `pyotp`.
- Session cookies include CSRF tokens for all admin POST requests.
- All credentials are stored as bcrypt hashes in `services/security.py`.

---

## Webhook Signatures
- WhatsApp webhooks are validated using the `X-Hub-Signature` header.
- Billing webhooks (Stripe/Paddle) are verified using provider-specific secrets.
- Invalid or replayed signatures are rejected immediately.

---

## RBAC (Role-Based Access Control)
- Roles: `admin`, `editor`, `viewer`.
- Permissions mapped in `services/security.py`.
- Used by `routes/admin_routes.py` and templates to hide restricted UI components.

---

## Rate Limiting
- Implemented per IP and per endpoint in `services/rate_limit.py`.
- Default burst: 10 req/sec; sustained: 3 req/sec.
- Exceeding limits returns HTTP 429.

---

## Logging & Privacy
- Logs are written to `logs/chatbot.log` and `errors.log`.
- No message text or PII is stored beyond 7 days.
- GDPR compliance ensured through anonymized analytics.

---

## Summary
Security controls are consistent across all channels (WhatsApp, Web, Admin).  
Every inbound request is verified, authenticated, and rate-limited before being processed.
