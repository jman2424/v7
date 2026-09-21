# One Vertex core, multiple business types

## Inspection and smallest compatible change

| Area | Existing evidence | Approach |
| --- | --- | --- |
| Products/prices | `schemas/catalog.schema.json` requires SKU and numeric price; `catalog-sheet.schema.json` preserves display-price text. `CatalogStore` and V7 planner actions use product vocabulary. | Add a generic offering view over these records, plus native typed offerings. Keep existing catalog storage, stock handling, routes and UI. |
| Branches | `branches.schema.json` requires postcode/coordinates; `GeoStore` provides retail delivery and nearest-branch lookup. | Project existing branches as stores; add office/workshop/warehouse/mobile/remote locations without requiring a postcode. |
| Sales conversations | `sales_playbook.py` already supports products/services/mixed and consultation/lead goals. Profiles, FAQs and delivery policies are tenant-owned. | Reuse these settings. Add public generic facts and operating rules to the local V7 handler. |
| Permissions/CRM/analytics | Accounts, CRM and statistics are already tenant-scoped. | Preserve all roles/scopes and existing records. Work records stay management-only. |
| Transactions | No shared booking/job/project engine exists. | Store typed work records with status; expose read tools. Do not claim slot availability, charge customers or confirm work through these records. |
| Promotions | Existing offer validation/history support general title/description plus retail SKU and discount fields. | Keep this contract. Use general promotions without SKU targeting; automatic service pricing/promotion execution is not added. |

## Storage and compatibility

`business/{TENANT}/business_core.json` is optional and schema-validated. It contains
`offerings`, `locations`, `business_rules`, `work`, optional `industry`, and
`operation_types`. Missing documents behave as empty collections.

Existing `catalog.json`, `branches.json`, prices, stock, delivery rules, product
IDs and Tariq's files are not rewritten. Generic offerings combine native records
and a read-through retail view. They are not copied into a second catalog.
Retail tools and responses retain their names and shapes. A retail offering's
`retail:` ID identifies its category/name; renaming changes that selector, so read
again after an edit. Native IDs remain stable.

Each offering carries its source document `revision`. `get_offerings.revision`
is the **business-core document** revision used for creating native offerings.
Use an individual offering's revision when updating it. Retail aliases support
name/numeric-price edits through the original catalog mutation service; existing
catalog tools remain the route for stock and legacy display-price edits.
`active` is distinct from stock availability. Legacy display prices remain
`price_str`; they are never silently converted to a fixed amount.

No SQLite tables or applied migrations change. The prepared Supabase
`business_documents` and `document_versions` JSONB tables already accept this
additional filename and preserve its tenant boundary. The offline importer copies
it with other tenant JSON. The application still needs the previously documented
PostgreSQL runtime adapter before a live Supabase cutover. If work volume later
requires concurrent scheduling, add normalized, indexed tenant/work tables and
transactional availability checks in a new migration at that point.

## Configuration and templates

Reviewed starting examples live in `business_templates/`:

- `retail.json`: existing catalog/branches plus order vocabulary.
- `professional-services.json`: per-word translation, remote coverage, manual quotes.
- `appointment-services.json`: service duration, starting price, mobile radius.
- `property.json`: viewing vocabulary and an office.

Examples are configuration, not separate applications. Replace example facts and
prices before use. Do not apply a template over an existing business document.
There is no automatic onboarding-template UI in this change.

An authorized owner of an activated tenant (or platform operator with existing
permissions) can save the reviewed document through the existing authenticated,
CSRF-protected `PUT /files/raw/business_core.json` workflow. It uses the existing
validation, snapshots, audit and runtime invalidation. Keep the latest document
when editing: this whole-document settings route has the same last-writer behavior
as existing configuration saves. MCP offering writes provide revision checks.

Use the existing Agent playbook settings to select services/mixed and a consultation
or lead goal. Keep the existing business profile, FAQs and policies. Retail UI labels
remain intact; native offerings are managed through MCP/REST/configuration for now.

## MCP and REST

Both call the same services and retain owner OAuth, scopes, rate limits, tenant
selection, activation checks, revisions and audit. No new roles are introduced.

- `get_offerings`, `get_offering`, `create_offering`, `update_offering`
- `get_locations`, `get_service_areas`, `get_business_rules`
- `get_jobs`, `get_bookings`, `get_orders`, `get_projects`, `get_viewings`,
  `get_appointments`, `get_tickets`
- `get_business_health`; existing `get_statistics` remains shared

REST paths mirror these under `/api/v1`: `/offerings`, `/offerings/{offering_id}`,
`/locations`, `/service-areas`, `/business-rules`, `/business-health`, and the work
collection names. See `schemas/vertex-api.openapi.json` for the exact contract.
Lists are paginated. Work tools return stored records only, not inferred historical
orders, external CRM jobs or live calendar availability.

## Customer AI context and limits

No model training or new AI call is added. The existing tenant profile, FAQs and
policy paths remain. When a business-core document exists, V7 builds a bounded
public context from active native offerings, public locations and active rules.
The local handler answers matching service/pricing/location/rule questions directly
from those facts. It distinguishes starting prices, per-word rates and quotes,
includes duration and applicable saved rule text, and requests team confirmation.
The context contains at most 50 offerings, 30 locations and 50 rules; this is a
small-business foundation, not semantic retrieval over an unbounded database.

Rule descriptions are data, not executable scripts. Manual-review rules are
communicated to customers; no quote calculation, radius enforcement, booking,
job execution or payment action is invented. Such future actions must enforce rules
in deterministic services before committing. Unmatched questions keep the existing
V7 handling; V5/V6 retain their existing behavior.

Private work notes, customer references, account credentials, staff access data and
management analytics are excluded from public conversation context. Management MCP
can read authorized work records; customer chat cannot. No business-core data is
sent to an external model by this change.

## Validation

`pytest tests/test_business_core.py tests/test_mcp.py tests/test_vertex_api.py -o addopts='' -q`
covers generic service pricing, native and legacy mutations, stale revisions,
permissions, tenant scope, private-context exclusions, and unchanged Tariq files.
