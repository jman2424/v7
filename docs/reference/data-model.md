# Data model

Everything is scoped by a tenant key. The same logical data exists in both storage
backends; `V7_STORAGE_BACKEND` chooses which one a deployment uses.

## Tenant documents

One set per tenant. In the `sqlite` backend they are JSON files under
`<V7_DATA_DIR>/business/<TENANT>/` (or `business/<TENANT>/` without a data directory).
In the `postgres` backend they are rows in `business_documents`, with history in `document_versions`.
`retrieval/storage.py::KNOWN_FILES` is the authoritative list.

| Document | Schema in `schemas/` | Contents |
|---|---|---|
| `store_info.json` | `store_info.schema.json` | Business name, description, contact details. |
| `business_core.json` | `business-core.schema.json` | Generic offerings, locations and rules for non-retail businesses. |
| `catalog.json` | `catalog.schema.json` | Products and services, prices, availability. |
| `faq.json` | `faq.schema.json` | Questions and approved answers. |
| `branches.json` | `branches.schema.json` | Locations and opening hours. |
| `delivery.json` | `delivery.schema.json` | Delivery areas, rules and exceptions. |
| `offers.json` | `offers.schema.json` | Current and archived offers. |
| `branding.json` | validated in `service/business_validation.py` | Widget appearance, greeting, approved website origins. |
| `overrides.json` | validated in `service/business_validation.py` | Assistant settings, including `ai.mode`. |
| `synonyms.json` | none | Search synonyms for the catalog. |
| `sales_actions.json` | validated in `service/conversion_actions.py` | Booking and lead-capture actions offered in chat. |

Two catalog layouts are accepted when reading: `categories` (current, written by the
console and API) and `product_catalog` (written only by the legacy `/catalog_webhook`
import, validated by `catalog-sheet.schema.json`).

Every write goes through `Storage`, which validates the document, takes a per-tenant
lock and keeps a snapshot under `business/versions/`.

## SQLite files

Paths are resolved only by `service/runtime_paths.py`.

### `security.db`

Created on demand by the owning service module (search for the table name).

| Area | Tables |
|---|---|
| Sessions and sign-in | `management_sessions`, `login_attempts`, `auth_login_failures`, `mfa_challenges`, `mfa_code_uses`, `totp_steps`, `account_authenticators`, `trusted_devices`, `oidc_links`, `oidc_states` |
| Accounts and tenants | `managed_businesses`, `registration_requests` |
| Subscriptions | `billing_contracts`, `billing_invoices`, `billing_references`, `billing_discounts`, `billing_api_charges`, `billing_plan_state`, `billing_plan_choices`, `billing_plan_changes`, `billing_plan_events`, `billing_plan_reservations`, `billing_plan_usage` |
| Prepaid AI usage | `usage_wallets`, `usage_wallet_entries`, `usage_wallet_payments`, `usage_wallet_reservations`, `usage_checkout_requests`, `usage_exchange_rate`, `api_usage` |
| AI budget | `ai_budget_settings`, `ai_budget_authorisations`, `ai_budget_recharges`, `ai_budget_events`, `ai_budget_notifications`, `ai_budget_payment_costs`, `ai_budget_work_tenants`, `ai_provider_funding_settings`, `ai_provider_cost_snapshots`, `ai_provider_limit_snapshots`, `ai_provider_health` |
| Business applications | `business_applications`, `business_application_events`, `business_application_notifications`, `business_application_permits`, `business_application_settings` |
| Referrals | `referral_program`, `referral_codes`, `referral_claims`, `referral_rewards` |
| Sales and operations | `recorded_sales`, `sales_action_requests`, `sales_action_attempts`, `business_operations`, `inventory_history` |
| Conversation and integrations | `conversation_memory`, `webhook_inbox`, `mcp_grants`, `mcp_rate` |

### `analytics.db`

| Table | Contents |
|---|---|
| `events` | One row per inbound/outbound message, error and pipeline event, by tenant and channel. |
| `leads` | One row per lead, by tenant, with status and latest session. |

### Other files

| File | Contents |
|---|---|
| `crm_snapshot.json` | Lead conversations for the in-process CRM (`service/crm_service.py`). |
| `selfrepair.log` | The append-only audit trail (`service/audit.py`). The name is historical. |

## PostgreSQL

`supabase/migrations/` holds the schema, applied in filename order. Tables are private,
reached only through a restricted login, and protected by tenant row-level security.
[../operations/supabase-migration.md](../operations/supabase-migration.md) covers setup,
import from SQLite and verification.
