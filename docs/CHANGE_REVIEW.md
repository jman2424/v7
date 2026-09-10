# Dashboard and security change review

This change set was developed in the downloaded V7 workspace based on archive
commit `a9c67c3bca62db56af761e41c50e4db03bba1ca2`. GitHub main was subsequently
found at `ea55ce894654d6a1a8de552d387cdece3e9f6851`, 39 commits ahead of that
archive. It contains additional account, sales and Svelte console work.

The downloaded-workspace changes are published on their own review branch.
They must be reconciled with those newer implementations before merging or
deploying; replacing main with this snapshot would discard newer functionality.

## Changes in this workspace

- Dedicated Flask dashboard URLs and templates for overview, companies,
  conversations, products, FAQs, branches, delivery, profile, settings, errors
  and integrations. Product search, filtering and pagination; mobile sign-out.
- Tenant-scoped management APIs, file validation and recoverable snapshots.
- Scrypt account registry, revocable server-side sessions, login throttling,
  CSRF protection, security headers and HTTPS platform-admin MFA requirement.
- Optional signed Meta/Twilio WhatsApp routes with recipient validation,
  persistent deduplication and retry/error reporting.
- Tenant-bound web conversation tokens, approved embedding origins, browser
  speech controls, scoped agent configuration and safer catalog matching.
- Deployment configuration corrections, local preview/account tooling and
  security documentation describing actual controls and limitations.

## Main files

- `routes/admin_routes.py`, `routes/admin_api_routes.py`, `dashboard/templates/pages/`
- `dashboard/templates/dashboard.html`, `dashboard/static/css/workspace.css`
- `dashboard/static/js/management.js`, `workspace.js`, `widget.js`, `admin.js`, `charts.js`
- `service/security.py`, `service/session_store.py`, `app/middleware.py`
- `routes/whatsapp_routes.py`, `service/webhook_inbox.py`, `connectors/whatsapp.py`
- `routes/webchat_routes.py`, `routes/files_routes.py`, `retrieval/storage.py`
- `app/container.py`, `service/message_handler.py`, `handlers/handler_v7.py`
- `retrieval/catalog_store.py`, `retrieval/policy_store.py`, `schemas/`
- `scripts/run_local.py`, `scripts/manage_account.py`, `docs/SECURITY.md`
- `tests/test_platform_security.py`, `tests/test_whatsapp_security.py`

## Validation

- Targeted pytest suite: 50 passed, using temporary companies and mocked providers.
- JavaScript syntax: six dashboard/widget scripts passed Node checks.
- Live localhost HTTP: login, eleven dashboard pages and agent greeting passed.
- Full legacy suite collection: three stale `services` imports fail in the
  downloaded baseline. It is not a passing full-release test suite.
- Browser visual QA was blocked by automatic approval review's account usage
  limit. No visual-layout, microphone or live-provider verification is claimed.

No secrets, preview accounts, customer logs, local databases or test dependencies
belong in this branch. See SECURITY.md for operational limitations.
