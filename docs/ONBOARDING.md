Tenant Onboarding Guide

Platform operators can create a clean tenant through `POST /admin/api/tenants`.
The endpoint creates a new folder with neutral starter data; it never copies another
company's catalog, delivery rules, branding, or allowed website origins.

Example request:

```json
{
  "key": "NORTHSTAR",
  "name": "Northstar Homewares"
}
```

The new tenant is intentionally not launch-ready: its starter catalog is marked
out of stock and its widget has no allowed website origins. Complete the setup
before sharing the embed code.

## Configure the sales agent

The normal setup path is the SvelteKit owner console in `frontend/`. A business
owner can sign in to manage their own tenant's website widget, business profile,
branches and opening hours, product catalog, current offers, FAQs, delivery
coverage, fees, minimum orders, collection setting, delivery exceptions, and the
V7 sales tone. An offer can be limited to specific catalog SKUs and given a
start/end date; the agent only presents active offers within that date range.
The console saves atomically, validates the tenant data, records an audit event,
and reloads the tenant runtime so new conversations use the updated knowledge.

Platform operators can select a tenant in the console; business owners are
restricted to the tenant bound to their account. The corresponding protected
endpoints are:

| Endpoint | Purpose |
| --- | --- |
| `GET/PUT /admin/api/widget` | Widget branding and approved website origins |
| `GET/PUT /admin/api/catalog` | Products, categories, prices, tags, and stock status |
| `GET/PUT /admin/api/faq` | Sales FAQs and topic tags |
| `GET/PUT /admin/api/offers` | Current offers, customer-facing terms, codes, dates, and eligible product SKUs |
| `GET/PUT /admin/api/delivery` | Delivery zones or postcode prefixes, fees, and exceptions |
| `GET/PUT /admin/api/profile` | Business identity, contact paths, and certifications |
| `GET/PUT /admin/api/branches` | Branch addresses, coordinates, and daily opening hours |
| `GET/PUT /admin/api/agent-settings` | Grounded V7 reply tone and response length |
| `PUT /admin/api/leads/<lead_id>` | Move a tenant lead through its sales status |

`catalog.json`, `faq.json`, and `delivery.json` remain useful for an audited
bulk import or controlled deployment change. The schemas accept both the
existing postcode-prefix delivery format and the zone format used by the owner
console.

## Link Google Sheets (optional)

If using analytics or data sync:

Share the target Google Sheet with your service account email.

Add the sheet ID in .env as SHEETS_ID.

Enable sync with SHEETS_SYNC=true.

## Validate setup

Run validation to catch schema or SKU issues:

python scripts/validate_catalog.py

This ensures your JSON files follow all required formats and contain valid data.

## Deploy tenant

Commit and push the new tenant folder:

git add business/NEW_TENANT
git commit -m "Add new tenant NEW_TENANT"
git push

Render or your deployment environment will automatically include the new tenant data.

## Test tenant

After deployment, test your bot via /chat_ui or WhatsApp:

Confirm product queries return correct results.

Check delivery fees match postcode rules.

Verify store info responses.

## Backups and snapshots

Nightly snapshots run automatically via scripts/snapshot_backup.py.
You can also trigger manual backups:

python scripts/snapshot_backup.py --tenant NEW_TENANT

To test restore behavior safely:

python scripts/restore_snapshot.py --dry-run

Summary

Every tenant has its own data folder, schema validation, and analytics link.
Once configured, it becomes immediately available to the AI for real-time responses — no code edits required.
