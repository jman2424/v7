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
pip install -r requirement.txt
pytest
ruff check .
mypy .
```

## Deployment

For an isolated local preview, run `python scripts/run_local.py`. It copies the
sample business into `logs/local-preview/business`, disables external AI and
WhatsApp calls, and creates temporary accounts. Read the generated password in
`logs/local-preview-access.txt`; accounts change on restart.

- Sign in: http://127.0.0.1:10000/admin/login
- Platform companies: http://127.0.0.1:10000/admin/companies?tenant=TARIQ
- Business overview: http://127.0.0.1:10000/admin/overview?tenant=TARIQ
- Agent test: http://127.0.0.1:10000/chat_ui?tenant=TARIQ

Products, FAQs, branches, delivery, business profile, agent settings,
conversations, errors and integrations each have their own dashboard URL.
Owners only access their assigned company; platform administrators can switch
companies from the Companies page.

For production, provision accounts with `scripts/manage_account.py` and export
the variables in `env.example`. Use a random SECRET_KEY, the correct HTTPS
BASE_URL and persistent protected storage. Follow [Security and operations](docs/SECURITY.md)
for account, authenticator and optional WhatsApp configuration.

The app can run with Gunicorn:

```bash
gunicorn -c gunicorn.conf.py 'app:create_app()'
```
