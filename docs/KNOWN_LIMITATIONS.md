# Known limitations and deferred work

Verified against the code in November 2026. Remove an entry when it is resolved.

## Deployment

- **One web worker.** Conversation memory, rate-limit buckets and the per-tenant
  container cache are held in process memory. Keep `WEB_CONCURRENCY=1` until these
  move to shared storage.
- **Per-tenant containers are cached without eviction.** Memory grows with the number
  of tenants that have received traffic since the last restart.
- **The live instance has not moved to PostgreSQL.** See
  [operations/supabase-migration.md](operations/supabase-migration.md) and
  [operations/live-backup.md](operations/live-backup.md) before changing its storage.

## Product scope

- **UK-shaped delivery logic.** Postcode parsing in `service/validators.py`,
  `service/router.py` and `service/message_handler.py` assumes UK postcodes, and prices
  default to GBP. Other regions work for everything except postcode-based delivery
  and nearest-branch answers.
- **`/catalog_webhook` is single-tenant.** A signed import always replaces the catalog
  of the default `BUSINESS_KEY` tenant and writes the older `product_catalog` layout.
  Use the console or `/api/v1/catalog/items` for every other tenant.
- **Stripe is the only supported billing provider.** `connectors/billing.py` contains
  an untested Paddle branch.
- **Legacy `halal_certified` profile field.** Still accepted for existing tenants;
  new certifications belong in `certifications`.

## Code health

- **Type checking is a ratchet.** `mypy .` passes, but the modules listed under
  `[[tool.mypy.overrides]]` in `pyproject.toml` are skipped because they had errors
  when checking was enabled. Untyped function bodies are not checked.
- **Large modules.** `handlers/handler_v7.py`, `routes/admin_api_routes.py` and
  `frontend/src/lib/Console.svelte` each exceed 1,700 lines. Splitting them was
  deferred: they carry the most behaviour and the most tests.
- **Imports inside functions.** Several hundred exist, mostly to avoid import cycles
  between `service/` modules.
- **Environment variables are read where they are used.** Only core settings go
  through `app/config.py`. `env.example` is complete and enforced by a test.
- **Some console tests read source text.** Most files in `frontend/tests/` extract
  functions from `.svelte` files by pattern. Restructuring a component can fail them
  without a behaviour change.

## Console and public site (planned redesign)

- The console is English-only. Spanish, French and Arabic dictionaries cover only part of
  it, so the language picker is switched off (`consoleLanguageChoice` in
  `frontend/src/lib/i18n.ts`). Only the public homepage is translated; other public
  pages are English.
- The public site, console and widget use separate colour and type definitions.
- All languages ship in the initial console bundle.
