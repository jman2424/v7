# V7 Agents by Vertex Seven

Unified AI-driven sales and support framework for WhatsApp, website chat
widgets, tenant management, and admin CRM analytics.

## Overview

V7 Agents by Vertex Seven is a modular, multi-tenant chatbot and sales automation
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

The owner console has separate URLs under `/console/`: `pipeline`, `test`, `conversations`, `agent`,
`website`, `integrations`, `catalog`, `offers`, `faqs`, `delivery`,
`profile`, `branches`, and `team`. Platform operators also have `companies`
and `errors` pages. The Flask dashboard at `/admin` provides separate overview,
company monitoring, conversation, error, knowledge and integration pages.
Permissions are enforced by the APIs as well as the navigation.

Platform administrators signing in at `/console/` land on `/console/platform`,
which lists companies, recorded activity and issues, with company-specific links
to workspaces, statistics and owner/staff accounts. The existing platform-only
`/admin/api/platform` supplies this overview. Company owners retain their own
workspace and may create additional businesses on the Companies page. The server
records ownership and allows switching only among those businesses. Staff remain
restricted to their assigned company. Use Team access as a platform
administrator to create a `business_owner` for the selected company. Owner-created
accounts are restricted to staff within their own company.

API usage and cost appears only on its dedicated `/console/usage` page; the
duplicate Statistics cost tab has been removed.

Conversations uses the same console layout with separate message, lead and common
question views. Profile and delivery forms use the available page width and wrap
on smaller screens. Saving delivery or branch settings retains existing postcode
exceptions, area notes and branch holiday dates.

The V7 agent reads configured profile contacts, social links, certifications and
branch hours, plus delivery notes and applicable dated service notices. Dated
delivery requests use ISO dates (`YYYY-MM-DD`); postcode-specific notices stay
scoped to their postcode. FAQ, business-information and delivery replies retain
their full conditions even when the tone's sentence limit is shorter.

**Implementation** (`/console/implementation`) guides owners through website
approval, installation, launch testing, optional WhatsApp and troubleshooting.
It provides company-specific floating-widget, responsive iframe and direct-chat
code, with instructions for HTML, WordPress, Shopify, Wix and Squarespace. The
website checker compares the saved allowlist only; it does not scan a website.
Setup data comes from authenticated, tenant-scoped widget and integration APIs.
Only exact localhost/loopback hosts permit HTTP origins for local development.
The floating loader ignores duplicate installation for the same company and
supports Escape to close the chat, restoring focus to its launcher. Speech still
requires browser support, user permission and the host website's permissions policy.
Installing the widget does not import website content or connect bookings,
payments or inventory automatically. Use `pytest tests/test_widget_tenancy.py
tests/test_owner_console.py` and `npm run check` in `frontend/` to check setup changes.

**WhatsApp QR** (`/console/whatsapp-qr`) creates a click-to-chat link and downloadable
SVG for an international WhatsApp number, with an optional 160-character message.
The authenticated, CSRF-protected `POST /admin/api/whatsapp-qr` scopes requests to
the permitted company, validates input and generates the QR locally with the pinned
`qrcode` library. No external QR service, scan tracking or stored number/message is
used. Owners must scan and verify the destination before sharing. Creating a QR
does not connect the agent or change WhatsApp routing; automated replies require
the same number to be configured through Meta/Twilio. See WhatsApp's
[click-to-chat instructions](https://faq.whatsapp.com/5913398998672934/?locale=en_US).

**Statistics** (`/console/statistics`) adds 1â€“365 day activity comparisons, UTC daily
charts and tables, web/WhatsApp filters, handoff/contact counts, current lead stages,
fallback topics and error breakdowns. The authenticated `/admin/api/statistics`
endpoint returns tenant-scoped aggregates without customer messages or contact
records. Its prior-period comparison uses an equal preceding window. Current lead
statuses cover all dates/channels because the lead table has no reliable creation
date or channel field. API costs remain restricted to owners/platform operators.
Counts represent retained events, not unique people, verified sales, uptime or QR
scans. Test with `pytest tests/test_statistics.py`.

The **Reply rates & trends** view matches each inbound message ID to the response
ID generated by its channel route, scoped to the same tenant and session. Reply
rate is matched replies / eligible inbound messages; answer success excludes
fallbacks, clarification, no-results and system failures. Neither metric confirms
customer satisfaction, delivery or purchase. Untracked messages are excluded and
shown separately. Reply timing uses retained event timestamps (one-second
precision). Daily rates follow the inbound day, while message-volume graphs use
each event's own day. Busiest-hour, query-topic and fallback/error charts use UTC.

**Products, sales & stock** ranks matched product enquiries, owner-recorded units
sold and current quantities in either direction. Product interest is recorded at
the web/WhatsApp boundary for search, price, comparison and category replies;
each returned SKU counts once per reply. It is not a literal search-term count or
a purchase, and earlier missing telemetry is not backfilled. No new customer
message text is stored for these metrics.

Owners/platform operators can record a completed product sale in GBP, with date,
quantity and channel, or void an incorrect entry. The authenticated, CSRF-protected
`POST /admin/api/recorded-sales` accepts a client-generated idempotency ID;
`POST /admin/api/recorded-sales/<id>/void` keeps the original record for audit.
These entries do not charge customers, update inventory or imply chat attribution.
All-channel sales include offline entries. No shop/POS connector is configured by
this feature. Reports show up to 30 recent sale entries and all product rankings.

Catalogue items support optional `stock_quantity` and `low_stock_threshold`
(default 5 catalogue units). Unknown quantities remain null. A supplied quantity
controls `in_stock`; zero makes the product unavailable to the agent. Saving the
catalogue snapshots changed stock levels; history starts with the first save and
never invents past levels. Stock graphs carry the last recorded quantity forward;
current stock ignores period/channel filters. Keep quantities updated manually
until a stock-source integration is configured.

`recorded_sales` and `inventory_history` are additive tables in the existing
analytics database, initialized without rewriting old records. Back up that
database with tenant files; ephemeral storage cannot retain long-term reports.
Implementation: `service/product_metrics.py`, `service/statistics.py`, the channel
routes and the console statistics components. Checks:
`pytest tests/test_product_statistics.py tests/test_statistics.py` plus
`npm run check` / `npm run build` in `frontend/`.

Agent qualification now retains the pending question while answering customer
questions, avoids restarting completed qualification within a conversation, and
does not append a second question after an existing one. Empty offers do not start
a qualification interview. Checks: `pytest tests/test_sales_agent.py
tests/test_whatsapp_qr.py`.

Use **Test agent** (`/console/test`) to type questions, dictate them with a supported
browser, or hear replies aloud. Tests use the selected company's saved settings
and real response engine (including its configured AI provider). They retain
conversation memory separately and do not create sales leads or customer analytics.
The authenticated, CSRF-protected test API binds expiring conversation tokens to
both the company and management session; test actions are audited without message
contents. New conversation or switching companies clears the displayed chat.
Microphone permission is requested only when the user starts dictation.

**API usage & cost** (`/console/usage`) shows the selected company's configured
planning/rewriting models, actual response models, recorded input/output/cached
tokens and estimated GBP cost. Platform operators can select all companies;
company owners can only see their own company; staff cannot access this report.
The authenticated `/admin/api/api-usage` endpoint enforces these restrictions.
The 1â€“90 day report includes web, WhatsApp and Test agent calls at both OpenAI
call sites, including paid responses subsequently rejected by a guard.
Fast paths and deterministic replies do not create API-call records.

Accounting stores only model, company, channel, purpose, timestamps, status,
token counts and a USD cost snapshot in an additive `api_usage` table in
`ANALYTICS_DB_PATH`. Keep that database on persistent storage and back it up;
ephemeral hosting loses retained usage after replacement/redeployment. There is
no import of spending before this feature. Unknown prices, nonstandard tiers,
failed requests and missing provider usage are explicitly unpriced. SDK retries
without returned usage, taxes, credits and other applications are not included;
this is an estimate, not the provider invoice. Browser speech is not billed by
this OpenAI text ledger. Recording failures log a safe operational error and do
not discard customer replies.

Standard text rates in `service/api_usage.py` were checked on 2026-09-11 against
[GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini) and
[GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o). Only listed aliases
and snapshots are priced; update explicit rates and version after verifying
provider prices. Stored USD costs do not change when rates are updated.
GBP estimates convert the report at the latest retained ECB reference rate via
[Frankfurter](https://frankfurter.dev/), showing the rate and date. The server
refreshes hourly with a three-second timeout and sends no company data. An outage
uses the saved rate, labelled stale after four days; no retained rate means the
GBP estimate is unavailable. Estimates may change with exchange rates and differ
from actual card charges. No extra API key or dependency is required.

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

### Subscription payments and mandatory two-factor authentication

Every management account now completes authenticator verification. New accounts
scan their own QR after their password is accepted; this does not grant dashboard
access until a valid code is confirmed. Local preview credentials are not live
Render credentials. Existing server-configured admin passwords and authenticators
are unchanged. See [security and recovery](docs/SECURITY.md).

The `/console/subscription` page shows the £400 monthly platform subscription,
£200 one-time implementation and optional £200 monthly WhatsApp add-on. Each has
20% exclusive VAT: £480/month, £240 once and £240/month respectively. Only platform
administrators create tenants and see the all-company subscription list. Owners
see their own billing; staff need explicit view permission. API billing requires explicit
platform approval of a completed month's amount; usage estimates are not charged
automatically. Staff need explicit view_costs and/or view_subscriptions permissions;
subscription access is read-only. All accounts require authenticator 2FA. New
businesses can be configured before launch, but only activate after both the
platform subscription invoice and implementation payment are confirmed. Existing
businesses keep their current operation. Ownership and activation records live in
SECURITY_DB_PATH and need persistent storage along with account and billing data.
No real Stripe charge is taken by tests or by deploying the code.

Stripe setup (server-side only):
- Set `BILLING_PROVIDER=stripe`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, and
  `STRIPE_TAX_RATE_ID` for an active **20% exclusive** tax rate.
- Point Stripe webhooks to `/billing/stripe/webhook`; subscribe to
  `checkout.session.completed`, `customer.subscription.created`,
  `customer.subscription.updated`, `customer.subscription.deleted`,
  `invoice.paid`, `invoice.payment_failed`, `invoice.finalized`, `invoice.updated`,
  `invoice.voided`, and `invoice.marked_uncollectible`.
- Enable the Stripe customer portal for payment method changes and subscription
  cancellation. The portal uses the authenticated company's stored customer ID.
- Use a Stripe test account first. Checkout accepts server-owned GBP prices;
  implementation uses its own one-time checkout and invoice, separate from the
  monthly plan. Earlier combined implementation payments remain recognised.
  Old open combined checkouts are expired when replaced. Optional WhatsApp has
  its own monthly subscription. API usage is additional and paid separately.
  The homepage and subscription page explain all four charges and VAT.
- Use **persistent** `SECURITY_DB_PATH`, `V7_DATA_DIR` and `ANALYTICS_DB_PATH`
  storage before onboarding paying companies. This deployment's previous free
  Render instance has ephemeral local storage; deploying code alone does not
  configure durable billing, account, authenticator or usage storage.

Only signature-verified webhooks update payments. The server re-fetches Stripe
objects, scopes them to recorded billing references and upserts invoices by ID;
retries do not duplicate totals. Checkout redirects never grant paid status.
Amounts are stored as integer pence. Totals are recorded invoice payments before
refunds; credit notes/refunds are managed in Stripe and are not netted here yet.
History shows up to 120 invoices, and recorded API usage up to 24 calendar months.

WhatsApp deactivation pauses bot responses immediately and cancels renewal at the
paid-through date, without automatic refunds. Reactivation before expiry resumes
renewals. An expired subscription requires new checkout. Existing integrations
remain available before Stripe configuration; after billing is configured,
WhatsApp requires an active, unexpired, unpaused contract. Routes remain present.

Implementation references: [Stripe Checkout](https://docs.stripe.com/api/checkout/sessions/create),
[subscription events](https://docs.stripe.com/billing/subscriptions/webhooks), and
[signature verification](https://docs.stripe.com/webhooks/signature).

## Public website

The root URL `/` renders the public Vertex Seven / V7 Agents homepage without
login. It includes illustrative, fictional conversations; these do not call an AI
provider or read tenant data. Management pages still require authentication.
The former root status JSON is replaced by HTML; use `/healthz` for health checks.
Homepage assets live in `dashboard/templates/home.html`, `dashboard/static/css/home.css`,
`dashboard/static/js/home.js`, and `dashboard/static/img/vertex-seven.svg`.
