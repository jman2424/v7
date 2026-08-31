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
