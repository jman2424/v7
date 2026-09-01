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

## Website Widget

Platform operators can create a blank tenant with `POST /admin/api/tenants`.
Business owners configure their chat title, greeting, avatar, and approved
website origins in `/admin/widget`. The page provides a tenant-specific script
tag; the chat runs in an isolated iframe and each chat request resolves that
tenant's own catalog, policies, FAQs, and analytics.

## Owner Console

The SvelteKit owner console lives in [frontend](frontend/README.md). During
local development it runs on port `5173` and proxies `/api/*` to Flask on port
`5055`. In production, keep both behind the same HTTPS origin so the admin
session remains same-origin and no administrative CORS policy is needed.

Tenant owners can be configured with `BUSINESS_USERS_JSON`. Each entry has an
email, tenant key, bcrypt `password_hash`, optional TOTP secret, and a role such
as `business_owner`. The value is server-only configuration; never put it in a
client bundle or commit a real password/hash.

The console currently gives each owner structured controls for their business
profile, branches and opening hours, website widget, product catalog, FAQs,
delivery areas, fees, minimum orders, collection availability, service
exceptions, and V7 sales tone. Changes are tenant-scoped, validated, audited,
snapshotted, and applied to new conversations immediately.
