# AI Sales Assistant - Flagship Repo (AI Mode V7)

Unified AI-driven sales and support framework for WhatsApp, website chat
widgets, tenant management, and admin CRM analytics.

## Overview

AI Sales Assistant V7 is a modular, multi-tenant chatbot and sales automation
platform. It combines deterministic business logic, tenant-specific retrieval,
and AI-assisted response generation so each company can run a focused sales
agent for its own niche.

## Goals

- Sell and support through web chat and WhatsApp.
- Keep each tenant's catalog, FAQs, policies, analytics, and leads isolated.
- Let business owners manage their own products, FAQs, branches, delivery
  settings, offers, and website widget settings.
- Let the platform operator onboard companies, configure integrations, monitor
  analytics, and troubleshoot knowledge issues.
- Make the agent easy to embed on a business website as a branded widget or
  hosted chat page.

## Current Stack

- Python/Flask backend
- JSON-backed tenant configuration under `business/`
- V5/V6/V7 AI mode strategies under `ai_modes/`
- Web and WhatsApp routes under `routes/`
- Admin and widget assets under `dashboard/`
- Pytest test suite under `tests/`

## Common Commands

```bash
pip install -r requirements.txt
pytest
ruff check .
mypy .
```

## Deployment

The app can run with Gunicorn:

```bash
gunicorn -c gunicorn.conf.py 'app:create_app()'
```

### Render

`render.yaml` deploys the Flask web service with the existing `EXAMPLE` tenant,
binds Gunicorn to Render's `PORT`, and performs liveness checks at `/health`.
It also declares a persistent `/var/data` disk for tenant configuration,
accounts, leads, analytics, and audit data. Render generates `SECRET_KEY` when
it first creates the service. Add the WhatsApp, OpenAI, and billing secrets
marked `sync: false` in the Render dashboard; Blueprint updates intentionally
do not overwrite existing secret values.

Do not run a customer-facing deployment on Render's Free plan: it has no
persistent disk, so owner edits and lead data are not durable across restarts.
The first start with `V7_DATA_DIR` seeds the bundled starter tenant once and
never overwrites subsequent tenant data.

## Website Widget

Platform operators can create a blank tenant with `POST /admin/api/tenants`.
Business owners configure their chat title, greeting, avatar, and approved
website origins in `/admin/widget`. The page provides a tenant-specific script
tag; the chat runs in an isolated iframe and each chat request resolves that
tenant's own catalog, policies, FAQs, and analytics.

## WhatsApp Routing

One Meta WhatsApp Cloud app can serve multiple tenants. Set the server-only
`WHATSAPP_TENANT_MAP_JSON` environment variable to map each inbound Cloud phone
number ID to a tenant key. When a map is present, unrecognised inbound business
numbers are rejected rather than falling back to another tenant. Cloud webhooks
always require a valid `X-Hub-Signature-256`.
Twilio WhatsApp webhooks require `TWILIO_AUTH_TOKEN` and a valid
`X-Twilio-Signature`, plus an assigned recipient number. Unconfigured providers
fail closed; website chat works independently. Both `/whatsapp/webhook` and
`/whatsapp/status` remain available for later integration.

## Owner Console

The SvelteKit owner console lives in [frontend](frontend/README.md). During
local development it runs on port `5173` and proxies `/api/*` to Flask on port
`5055`. The production image serves it at `/console/` under the same HTTPS
origin, so the admin session remains same-origin and no administrative CORS
policy is needed.

The first platform-admin account is configured server-side with
`scripts/manage_account.py` and `ADMIN_USERS_FILE`, or the legacy
`ADMIN_USERNAME` and `ADMIN_PASSWORD_HASH` environment variables. Platform
admins require a TOTP authenticator in production or HTTPS deployments.
That operator can create tenant owner
and staff accounts in the Team section of `/console/`; hashes stay server-side
in the tenant's protected account data. `BUSINESS_USERS_JSON` remains available
for migration from existing deployments. Never put a real password or hash in a
client bundle or commit one to the repository.

The console gives each owner structured controls for their business profile,
branches and opening hours, website widget, catalogue, current offers, FAQs,
delivery areas, fees, minimum orders, collection availability, service
exceptions, and V7 sales playbook. A catalogue can represent products,
services, or both. The playbook sets the business focus, ideal customer,
verified customer benefits, catalogue type, primary conversion goal, optional
qualification questions, handoff wording, and reply tone without exposing a
free-form system prompt. V7 uses those structured fields locally to choose
grounded discovery questions and catalogue suggestions; tenant profile,
catalogue, policy, and playbook data are not sent to an external model by the
planner. Offers can be scoped
to catalogue references and given start/end dates; only active, in-date offers
are shown to customers.
Owners can also move a captured lead through Open, Contacted, Qualified, Won,
or Lost directly from the Sales activity view.
Platform operators can manage owner and staff access, while business owners can
create, reset, and disable staff accounts for their own tenant. Disabling a
tenant-managed account rejects its next protected request and clears its
browser session.
Changes are tenant-scoped, validated, audited, snapshotted, and applied to new
conversations immediately.

## Dashboard pages and local testing

The owner console has separate URLs under `/console/`: `pipeline`, `agent`,
`website`, `integrations`, `catalog`, `offers`, `faqs`, `delivery`,
`profile`, `branches`, and `team`. Platform operators also have `companies`
and `errors` pages. The Flask dashboard at `/admin` provides separate overview,
company monitoring, conversation, error, knowledge and integration pages.
Permissions are enforced by the APIs as well as the navigation.

For an isolated localhost preview, run `python scripts/run_local.py`. It writes
temporary login details to the ignored `logs/local-preview-access.txt`; test at
`http://127.0.0.1:10000/admin/login` and `http://127.0.0.1:10000/chat_ui?tenant=TARIQ`.
Build the console first with `cd frontend && npm ci && npm run build`, setting
`V7_CONSOLE_BASE_PATH=/console` in the build environment. The preview disables
AI-provider and WhatsApp calls and stores edits in its own data directory.

Use a random `SECRET_KEY` of at least 32 characters for other deployments.
See [security and operations](docs/SECURITY.md) for account setup, persistence,
webhook configuration and remaining limitations. Run `python -m pytest`,
`python -m ruff check .`, and `npm run check` / `npm run build` in `frontend`
before release.
