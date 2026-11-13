# Architecture

V7 is one Flask application that serves three front ends and several inbound
channels for many businesses ("tenants") at once.

Read this page first. For the exact list of endpoints see
[reference/http-routes.md](reference/http-routes.md); for a one-line description of
every Python module see [reference/module-index.md](reference/module-index.md).
Both are generated from the code and checked by `tests/test_reference_docs.py`.

## Repository map

| Path | What it holds |
|---|---|
| `app/` | Application factory, settings, middleware, the per-tenant `Container`. |
| `routes/` | HTTP endpoints. One Flask blueprint per file, registered in `app/app_factory.py`. |
| `handlers/` | The three response strategies (`handler_v5/v6/v7.py`) and the V7 planner (`brain_v7.py`) and renderer (`renderer_v7.py`). |
| `service/` | All business logic: conversation pipeline, accounts and security, billing, channels, analytics. |
| `retrieval/` | Tenant data stores (catalog, FAQ, delivery, branches, offers, overrides) over `retrieval/storage.py`. |
| `connectors/` | Adapters for Stripe, Resend email, WhatsApp (Meta and Twilio), store product sync and the widget bridge. |
| `schemas/` | JSON Schemas for tenant documents and the generated REST contract (`vertex-api.openapi.json`). |
| `business/` | Bundled starter tenants (`EXAMPLE`, and `TARIQ` as a retail demonstration). Live tenant data lives in the data directory or PostgreSQL, not here. |
| `business_templates/` | Starter playbooks by business type used when a tenant is created. |
| `dashboard/` | Public website templates, widget page, shared CSS/JS and translation dictionaries. |
| `frontend/` | SvelteKit owner/admin console, built to static files and served at `/console`. |
| `sdk/` | JavaScript embed SDK and a small Python client. |
| `supabase/migrations/` | PostgreSQL schema, applied in filename order. |
| `scripts/` | Operator command-line tools (accounts, backup, export, migration, local preview). |
| `evals/` | Offline agent-quality and performance benchmarks. |
| `tests/` | Pytest suite. Console unit tests are in `frontend/tests/`. |
| `docs/` | This documentation. See [README.md](README.md) for the index. |

## The three front ends

1. **Public website** — Jinja templates in `dashboard/templates/`, served by
   `routes/public_seo_routes.py`, `routes/privacy_routes.py` and the `/` route in
   `app/app_factory.py`.
2. **Owner/admin console** — the SvelteKit app in `frontend/`. `routes/owner_console_routes.py`
   serves the built files. The console talks to `/auth/*`, `/admin/api/*`, `/billing/*`
   and `/business-applications/*`.
3. **Chat widget** — `/widget.js` injects an iframe pointing at `/chat_ui`
   (`dashboard/templates/chatbot.html`, `dashboard/static/js/widget.js`). The iframe
   posts messages to `/chat_api`.

## How a customer message is answered

Website chat is the reference path; WhatsApp, email and phone join it at step 4.

1. `routes/webchat_routes.py::chat_api` resolves the tenant and loads its container
   with `Container.for_tenant`.
2. The request origin is checked against the tenant's approved website origins.
3. The conversation is identified by a server-signed token; callers cannot choose
   another conversation or tenant. Plan and tester limits are enforced.
4. `service/message_handler.py::MessageHandler.handle` runs the turn: input guard,
   session load, strategy dispatch, reply validation, session save, CRM and telemetry.
5. The strategy is the tenant's `ai.mode` in `overrides.json`, read by
   `service/ai_mode.py`. `v7` is the default and the supported product; `v5` and `v6`
   are deterministic fallbacks kept for tenants that opt in.
6. `handlers/handler_v7.py` first tries a grounded answer
   (`service/grounded_conversation.py`), then tools over the tenant stores, with
   `handlers/brain_v7.py` planning and `handlers/renderer_v7.py` producing the text.
7. Every model call goes through `service/api_usage.py`, which records usage and
   charges the tenant's prepaid wallet (`service/usage_wallet.py`).

## Tenancy

- A tenant key (for example `EXAMPLE`) scopes every document, lead, statistic,
  account and credential.
- `app/container.py::Container` holds one set of stores and services per tenant.
  `for_tenant` builds and caches it; `invalidate_tenant` rebuilds it after an edit.
- HTTP handlers never trust a tenant named by the caller. They call
  `service.security.authorized_tenant`, which checks it against the signed-in account.
- In PostgreSQL every table is protected by row-level security keyed on the tenant.

## Accounts, roles and permissions

- Roles: `platform_admin`, `business_owner`, `business_staff`. Customers are anonymous.
- Permissions are the strings in `service/security.py::ALL_PERMISSIONS`. Owners get
  `OWNER_PERMISSIONS`; staff get an owner-chosen subset.
- Sessions are server-side and revocable (`service/session_store.py`). Sign-in requires
  a password and an authenticator code (`service/account_mfa.py`).
- State-changing requests need the session's CSRF token (`app/middleware.py`).
  Provider webhooks are exempt because each verifies its own signature.

## Storage

`V7_STORAGE_BACKEND` selects one of two backends. See
[reference/data-model.md](reference/data-model.md).

- `sqlite` (default): tenant documents are JSON files; accounts, sessions, billing
  and usage are in `security.db`; messages and leads are in `analytics.db`. File
  locations are resolved only by `service/runtime_paths.py`.
- `postgres`: the same data in private Supabase tables. Startup refuses to run if the
  database is missing or unsafe; it never falls back to local files.

## Request protections (in order)

`app/middleware.py` installs, for every request: request id and CSP nonce, trusted
host and same-origin write checks, strict JSON validation, rate limits, CSRF, and
response headers (CSP, HSTS, nosniff, cache rules).

## Configuration

`env.example` lists every environment variable. `tests/test_env_example.py` fails if
the code reads one that is not documented there. Core settings are parsed once in
`app/config.py`; feature-specific settings are read where they are used.

## Where to change things

| Task | Start here |
|---|---|
| Add an endpoint | A blueprint in `routes/`, then `python scripts/generate_route_map.py`. |
| Change how the assistant answers | `service/grounded_conversation.py`, `handlers/handler_v7.py`, `service/sales_agent.py`. |
| Add a tenant setting | `service/business_validation.py` (validation) and `routes/admin_api_routes.py` (API). |
| Add a permission | `service/security.py::ALL_PERMISSIONS`, then the route's `require_permission`. |
| Change plans or prices | `service/plan_catalog.py`. |
| Add a database table | A new file in `supabase/migrations/` and the SQLite `CREATE TABLE` in the owning service. |
| Change console screens | `frontend/src/lib/`; the workspace/route registry is `service/console_navigation.json`. |
| Change imports or store synchronisation | `service/business_sync.py` (rules), `connectors/store_sync.py` (providers); see [reference/business-sync.md](reference/business-sync.md). |
| Change the widget | `dashboard/templates/chatbot.html`, `dashboard/static/js/widget.js`, `dashboard/static/css/widget.css`. |

## Checks

```bash
ruff check .
mypy .
pytest
```

```bash
cd frontend && npm run check && npm test
```

Known gaps and deferred work are listed in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
