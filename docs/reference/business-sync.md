# Business Sync Engine and imports

Keeps a business's products and prices in V7 in step with the system that owns them,
and gives one reviewed route for importing information during setup. Added November
2026. Verified with simulated providers only; see "What has not been verified".

## Pieces

| Module | Job |
|---|---|
| `service/sync_store.py` | Sources, job queue, item links, change sets. SQLite tables in `security.db`; PostgreSQL tables in `supabase/migrations/20261112090000_business_sync.sql` (forced tenant RLS). Encrypts credentials. |
| `service/sync_http.py` | Outbound JSON requests: HTTPS only, one authorised host, DNS result pinned and checked public, no redirects, size and time limits. |
| `connectors/store_sync.py` | Read-only adapters for WooCommerce (REST v3), Shopify (Admin GraphQL) and a custom JSON feed; webhook signature checks. |
| `service/business_imports.py` | Reads an uploaded CSV or JSON bundle into raw rows. |
| `service/business_sync.py` | Cleans and validates rows, plans changes, decides what needs a person, applies atomically, records links, undoes. |
| `service/data_sources.py` | Connect, settings, reconnect, disconnect, import, run a job. |
| `service/sync_worker.py` | Background loop (off unless `V7_SYNC_WORKER=true`; defaults to `V7_CHANNEL_WORKER`). |
| `routes/data_sync_routes.py` | `/admin/api/data-sources*` for the console and `/sync/hooks/<tenant>/<source>` for signed notifications. |
| `frontend/src/lib/DataSources.svelte` | My Business → Data Sources & Sync. |

Nothing duplicates business data. The engine writes the existing documents
(`catalog.json`, `faq.json`, `branches.json`) through `Storage._write_json` under the
tenant write lock, so schema validation, daily snapshots, plan limits and cache
invalidation behave exactly as for a console edit. Every channel and MCP then read the
same documents.

## Source of truth

Each source has an ownership setting per group: names, prices, categories,
availability. `source` (default) or `v7`.

For a field the source owns, with `last` = the value the source gave at the previous
sync and `now` = the value currently in V7:

| Source value | V7 value | Result |
|---|---|---|
| unchanged since `last` | anything | Nothing. A manual V7 edit is kept. |
| changed, equals `now` | | Nothing to write; remember the new value. |
| changed | still equals `last` | Update. |
| changed | edited since `last` | **Conflict**: not written; a person chooses. |

Fields V7 owns are never written by a source. FAQ answers written by hand are never
replaced by an import unless the reviewer ticks that row. Declining a proposal is
remembered until the source changes that record again.

## What applies automatically

A plan is applied without review only when the owner switched on "apply routine
updates" **and** none of these is true:

- first import from the source;
- a conflict with a V7 edit;
- text that looks like an instruction to an AI system (`suspicious_text`; that row is
  also left out);
- a price that at least halves or triples;
- a product matched to an existing V7 product by name or SKU for the first time;
- the source returned no products at all, or more than max(3, 20%) of linked products
  are missing (those removals are unticked);
- a currency different from the catalogue's.

Removals happen on a signed delete notification, on a product becoming unpublished, or
when a complete, successful listing no longer contains a linked product. A failed or
partial fetch never removes anything.

## Queue, retries, duplicates, ordering

- `sync_jobs` is unique on (tenant, source, event key). A redelivered webhook is the
  same job; the endpoint answers `duplicate: true`.
- A job is leased for fifteen minutes. A crashed run is queued again; writes are atomic
  and idempotent, so repeating is safe.
- Retryable failures (network, 429, 5xx) back off 2, 4, 8, 16, 32 minutes; after six
  attempts the job fails and the source shows "needs attention". Refused credentials
  (401/403) are not retried; the source shows "needs renewing".
- A notification older than the last value seen for that product is ignored.
- While a review is open, further notifications trigger one fresh full comparison
  instead of stacking reviews. An identical proposal keeps the existing review.
- Limits: 2,000 jobs per source per hour, 10,000 products per source, ten sources per
  business, polling every 15 minutes to 24 hours.

## Permission records

Every permission is one row in `sync_consents` (SQLite in `security.db`; PostgreSQL in
`supabase/migrations/20261113090000_business_sync_consent.sql`, forced tenant RLS, no
DELETE grant). A row holds the exact statement ticked, the account and role, the time,
the source kind and domain, what it covers and `TERMS_VERSION`. Rows are written by
`sync_store.create_source` and `update_source` in the same transaction as the source:

| Event | Record |
|---|---|
| Connect, or first upload | New row. |
| Reconnect, or another upload to the same source | Previous row ended as `renewed`; new row. |
| Disconnect | Row ended as `withdrawn`, with who did it. |

Rows are never edited otherwise and never deleted by the application. The console
shows them under Data Sources & Sync → Permission records; `GET /admin/api/data-sources`
returns them as `permissions`.

## The business's own website

Source kind `website`. Its address is always the `website` in the business profile;
no other address can be read.

- **Permission first.** `POST /admin/api/data-sources` with `kind: "website"` and
  `authorised: true` records `data_sources.WEBSITE_STATEMENT`. Without an active source
  for the current host, `POST /admin/api/website-knowledge/import` answers 409
  `website_permission_required` and nothing is fetched.
- **Reading.** `website_knowledge.import_website`: HTTPS only, public address pinned,
  no redirects, same host, at most 20 HTML pages, size and time limits, identified as
  `V7-Business-Knowledge-Importer/1.0`. `robots.txt` is honoured by default
  (`respect_robots=True`); if it cannot be read (other than a 404) nothing is fetched.
- **Cleaning.** `data_sources.clean_website` drops lines that read as instructions to
  an AI system. The source then shows `some_lines_skipped`.
- **When.** On permission, on "Read again now", and once a day while automatic reading
  is on (interval fixed at 1440 minutes). A failed read is retried and never replaces
  or deletes the stored pages.
- **One address.** If the profile website changes, the job stops with
  `website_changed` and the handler already ignores pages from the old address. The new
  address needs its own permission.
- **Withdrawal.** Disconnecting ends the permission record, cancels queued jobs and
  writes an empty `website_knowledge.json`.

## History and undo

Each applied change set keeps the documents as they were. Undo restores them only if
their current revision is exactly what that change produced; otherwise it refuses
(`changed_since_import`) and the dated snapshots under Versions remain available.
Undo copies are kept for the ten most recent applied changes per business.

## Security

- Connecting requires a signed-in owner (or platform operator), CSRF token, an active
  business and a ticked authorisation. The statement, account, time, domain and
  `TERMS_VERSION` are stored on the source and as a permanent permission record (below).
- Credentials are Fernet-encrypted with a key derived from `V7_SYNC_ENCRYPTION_KEY`
  (or `SECRET_KEY`), bound to the tenant, and never returned by any endpoint. The
  webhook signing secret is shown once, at connection.
- Webhooks: WooCommerce `X-WC-Webhook-Signature`, Shopify `X-Shopify-Hmac-Sha256` plus
  shop domain, custom `X-V7-Signature: t=<unix>,s=<hex HMAC-SHA256 of "t.body">` within
  five minutes. The tenant in the URL only selects where to look; a wrong tenant or a
  disconnected source is a 404.
- Imported text has markup and control characters removed and is length-limited.
- Disconnect wipes the credentials, cancels queued jobs and stops the endpoint.

## Operating it

1. Apply the migration (PostgreSQL deployments), then set `V7_SYNC_WORKER=true`.
   Without the worker, connecting, Sync Now and webhooks still run in the request;
   only scheduled checks need it. The console says when automatic updates are waiting
   for the worker.
2. Optional: set `V7_SYNC_ENCRYPTION_KEY` so rotating `SECRET_KEY` does not make stored
   credentials unreadable (sources would then ask to reconnect).
3. One pass by hand: `python -m service.sync_worker`.
4. Operator detail (job counts and codes, never payloads): the "Operator diagnostics"
   disclosure on the page, or `GET /admin/api/data-sources/diagnostics`.

## What has not been verified

- No request has been made to a real WooCommerce or Shopify store. Field names,
  signature headers and the Shopify GraphQL query follow the providers' documentation
  as understood in November 2026; test against a real development store before
  offering each connector to a customer. `V7_SHOPIFY_API_VERSION` defaults to `2026-07`.
- The PostgreSQL migration and `tests/test_postgres_business_sync.py` run only where
  `V7_TEST_POSTGRES_DSN` is set (CI). They were not run on the development machine.

## Limits to know

- Connectors synchronise products, prices, categories and availability. Opening hours,
  FAQs, offers and delivery rules come from an import or the console.
- One V7 product per store product, at the lowest variant price. Variants are not
  listed separately.
- The older "sheet" catalogue layout (`product_catalog`) cannot be synchronised.
- Product descriptions are not stored: the catalogue schema has no description field.
- Excel files must be saved as CSV. Uploads are limited to about 900 KB.
- Website reading covers page text for answers only. It does not turn web pages into
  products or prices, reads at most 20 pages, and checks at most once a day.
- Control of a website is the owner's recorded declaration. There is no technical
  proof of control (such as a code placed on the site).
- Withdrawing website permission empties `website_knowledge.json`, but earlier dated
  snapshots of that document remain until the workspace is closed.
- WooCommerce does not report a currency per product, so the currency check only works
  for Shopify and custom feeds.
