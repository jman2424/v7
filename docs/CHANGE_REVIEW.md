# Dashboard and security change review

The dashboard and security patches are integrated with GitHub main at
`ea55ce894654d6a1a8de552d387cdece3e9f6851`. The integration retains the existing
Svelte console, tenant onboarding, owner/staff accounts, offers, sales playbooks,
pipeline, widget installation and multi-tenant WhatsApp routing.

## Result

- Separate URL-based owner console pages and Flask management pages.
- Tenant-scoped APIs, platform company/error monitoring, validated file updates,
  audit events and pre-edit snapshots.
- Revocable server sessions, credential-change invalidation, login throttling,
  mandatory CSRF checks, nonced scripts and production platform-admin MFA.
- Signed Meta/Twilio webhooks, recipient mapping, persistent deduplication and
  retry/error reporting. WhatsApp remains optional.
- Signed web conversation continuation, approved embedding origins, optional
  browser speech controls and Python-client conversation-token compatibility.
- Persistent deployment paths, isolated preview/account tools, and frontend
  checks/builds added to CI.

## Main files

- `frontend/src/lib/Console.svelte`, `frontend/src/routes/`, `routes/owner_console_routes.py`
- `routes/admin_routes.py`, `routes/admin_api_routes.py`, `dashboard/templates/pages/`
- `service/security.py`, `service/session_store.py`, `app/middleware.py`
- `routes/whatsapp_routes.py`, `service/webhook_inbox.py`, `connectors/whatsapp.py`
- `routes/webchat_routes.py`, `routes/files_routes.py`, `retrieval/storage.py`
- `app/container.py`, `service/message_handler.py`, `sdk/python/client.py`
- `scripts/run_local.py`, `scripts/manage_account.py`, `docs/SECURITY.md`
- `tests/test_platform_security.py`, `tests/test_whatsapp_security.py`,
  `tests/test_owner_console.py`, `tests/test_python_sdk.py` and updated auth fixtures.

## Release checks and limits

Validated on the integrated tree:

- `python -m pytest -o addopts='' -q`: 165 passed (45 datetime deprecation warnings).
- `python -m ruff check .`: passed.
- `npm run check`: zero errors and warnings.
- `V7_CONSOLE_BASE_PATH=/console npm run build`: production build passed.
- `git diff --check`: passed.

Provider requests in tests are mocked and business data is isolated. CI repeats
the backend and frontend checks before its image build.

Browser visual QA was blocked by automatic approval review's account usage
limit. No visual-layout, microphone or live-provider verification is claimed.
No independent penetration test has been performed. See SECURITY.md for
deployment requirements and remaining operational limitations.

Secrets, preview accounts, customer logs, databases, build outputs and local
test dependencies are excluded from source control.
