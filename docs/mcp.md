# Vertex Seven MCP interface

## Purpose and architecture

The existing Flask app exposes a stateless Streamable HTTP MCP endpoint at
`/mcp`. ChatGPT does the reasoning; Vertex returns structured data and executes
validated business actions. The MCP path makes no OpenAI or external AI calls.
No new runtime dependencies are required.

`ChatGPT → OAuth / scopes → MCP transport → reusable services → existing storage`

### Repository inspection

| Area | Existing implementation | Integration |
| --- | --- | --- |
| Catalogue | `retrieval/catalog_store.py`, `retrieval/storage.py`, `routes/catalog_routes.py`, `routes/files_routes.py` | Preserve numeric and legacy sheet formats; item actions use existing schema validation, atomic writes, snapshots and automatic reloads. |
| Offers | `retrieval/offer_store.py` and tenant `offers.json` | Reuse existing offer validation, history and deal types. |
| Statistics | `service/analytics_db.py` powers the dashboard; `service/analytics_service.py` records activity in the same SQLite database. | Reuse tenant-scoped KPI, daily, intent and channel reads; add bounded explicit windows and safe recent-error projections. |
| Users and roles | `service/security.py`, protected `ADMIN_USERS_FILE` registry | Return tenant-assigned account email/role/disabled status only. No credential fields. |
| Health/errors | `/health`, `/ready`, tenant analytics errors, global diagnostic logs | Report tenant observations. Exclude global logs and raw errors. No unsupported provider-health claims. |
| Authentication | Management login, scrypt passwords, mandatory authenticator verification, revocable `service/session_store.py` sessions | Reuse login for OAuth consent and the account revision mechanism for token revocation. |
| Tenant separation | Server-assigned owner tenant; `Storage.tenant_dir` validation; scoped analytics | MCP never accepts a tenant selector. Platform-wide admin access is not exposed. |
| Audit | `service/audit.py` | Record writes with actor, tenant, source, action, operation ID, safe price/stock changes and document revisions; write to the audit log. |

The transport contains no database queries or catalogue manipulation. New
`BusinessManagement` operations are reusable by future management screens.
Existing dashboard file saves still use the same storage writer. Local writers
now share a SQLite lock so an item read/modify/write cannot interleave with a
dashboard file replacement.

## Tools

All list tools have bounded pagination where applicable. Unknown arguments,
including `tenant`, are rejected. Successful tool results include both MCP text
content and `structuredContent`; failures set `isError` with a safe error code.

| Tools | Scope | Data/behavior |
| --- | --- | --- |
| `get_business_overview`, `get_statistics`, `get_conversation_stats` | `business:read` | Recorded messages, sessions, leads, daily and channel activity |
| `get_popular_queries` | `business:read` | Aggregated intent/fallback categories; no raw customer text |
| `get_catalog`, `search_catalog`, `get_catalog_stats` | `business:read` | Catalogue items, stock counts, revision and exact selectors |
| `get_offers` | `business:read` | Stored offers, revision and time-dependent active status |
| `get_users`, `get_roles`, `get_user_role` | `business:read` | Tenant account access; users and roles remain read-only |
| `get_agent_health`, `get_error_summary`, `get_recent_errors`, `get_service_status`, `get_usage` | `business:read` | Tenant observations, safe error counts, recorded usage |
| `add_catalog_item`, `update_catalog_item`, `disable_catalog_item` | `business:read business:write` | Add to an existing category, update exact category/name, or mark out of stock |
| `create_offer`, `update_offer`, `disable_offer` | `business:read business:write` | Manage current offers and deal types by ID |

No user deletion, role changes, admin creation, SQL execution, code execution,
bulk deletion, payment or refund actions are available.

### Dates and comparisons

Read tools default to the last seven days (`minutes=10080`), with a maximum of
30 days. `get_statistics` also accepts `start_at` and `end_at` instead of
`minutes`. Use ISO timestamps with time zones. The start is inclusive and the
end exclusive; each range must be positive and at most 30 days. To compare two
weeks, call once for each range. All stored analytics timestamps are UTC.

Lead counts use the existing `updated_utc` metric: they represent leads updated
in the window, not newly acquired customers. These tools do not expose revenue, completed purchases, token billing, product popularity or unmet-demand analysis.

### Safe write workflow

1. Read the catalogue or offers, including its `revision`.
2. Resolve the exact item category and name, or offer ID.
3. Send the requested changes with `expected_revision`.
4. If the tool returns `conflict`, read again and reassess the user's request.

Numeric catalogue prices accept nonnegative finite numbers with at most two
decimal places. Legacy sheet catalogues use `price_str`: supply the complete
displayed price, such as `£7.99 / kg`. The service rejects numeric price updates
to that format to avoid discarding units/ranges. Disabling an item marks it out
of stock; it does not delete it. New items must use an existing category.

Offers use the existing offer schema: title, description, active, optional
starts_on/ends_on, product selectors and deal fields. Buy-one-get-one and
minimum-spend deals are supported. Legacy enabled and whole-UTC-day timestamps
are mapped to the current format. Disabling preserves history. Writes require
an activated business and do not execute payments.

## Deployment and ChatGPT connection

1. Deploy the existing Flask app behind HTTPS with persistent business data,
   analytics, security database and audit logs. Keep the repository's existing
   single-worker recommendation while chatbot memory is process-local.
2. Configure `BASE_URL` to the public HTTPS origin so management cookies are
   secure. Set `MCP_PUBLIC_URL` to that same origin, with no path. Leaving it
   blank keeps MCP and OAuth unavailable.
3. Provision a `business_owner` through the existing account-management flow
   (`scripts/manage_account.py`), with exactly one assigned tenant. Do not use
   an unscoped platform-admin account for MCP.
4. Register a predefined OAuth client in the server's `MCP_OAUTH_CLIENTS` JSON
   environment variable. Copy the **exact HTTPS redirect URI** from your
   ChatGPT connector setup. Example shape (replace the callback placeholder):

   ```json
   {"vertex-chatgpt":{"redirect_uris":["https://chatgpt.com/connector/oauth/REPLACE_WITH_CALLBACK"]}}
   ```

   Public clients use mandatory S256 PKCE. If your connector setup requires a
   client secret, add `secret_hash` containing its Werkzeug **scrypt hash** and
   configure the corresponding secret privately in the connector. The token
   endpoint accepts `client_secret_post`, not `client_secret_basic`. Never put
   real secrets in tracked files. Dynamic client registration is not enabled.
5. In an account/workspace with custom MCP access enabled, add the deployed
   `https://YOUR_HOST/mcp` URL, choose OAuth, and supply the registered client ID
   and optional client secret. Sign in as the business owner and consent to
   `business:read`, optionally also `business:write`.
6. Start with a read such as “Show my catalogue.” Test an authorized edit and
   confirm it appears in the existing dashboard. Real ChatGPT linking requires
   your deployment and account; local regression tests do not prove that step.

Discovery endpoints:

- `/.well-known/oauth-protected-resource/mcp` (also available without `/mcp`)
- `/.well-known/oauth-authorization-server`

OAuth endpoints: `/oauth/authorize`, `/oauth/token`. Authorization and token
requests must send the exact resource `https://YOUR_HOST/mcp`. Exact callback
matching, consent CSRF, S256 PKCE and single-use authorization codes are enforced.
MCP requires Bearer authentication on every request; dashboard cookies never
authorize MCP. JSON response mode supports protocol versions `2025-03-26`,
`2025-06-18` and `2025-11-25`. GET/DELETE return 405 because no server stream or
session is allocated. Notifications cannot execute tools.

This follows the [OpenAI OAuth connection guidance](https://developers.openai.com/plugins/build/auth)
and [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).

## Security and operations

- Existing owner permissions and server-assigned tenant remain authoritative.
  Changing/disabling/removing the account invalidates its tokens. Removing a
  registered OAuth client also invalidates access. Staff console access remains available; MCP and REST grants are owner-only.
- Access tokens last 15 minutes; authorization codes last two minutes. Refresh
  tokens last 30 days and rotate on use. Only token digests are stored, in the
  existing security SQLite database. Refresh tokens are scoped to the same
  identity, client, resource and consented permissions.
- Authenticated owners can POST `/auth/mcp/revoke` with their management
  session and CSRF token to revoke their grants, access and refresh tokens.
  Dashboard logout alone does not revoke independent OAuth connections.
- MCP applies a shared per-owner/tenant limit of 60 requests per minute in
  SQLite, in addition to existing IP limits. These limits and file-write locks
  assume local workers share the same persistent files. Separate replicas
  without shared storage are not supported by this architecture.
- Origin headers are checked against the public origin and optional exact
  `MCP_ALLOWED_ORIGINS`; server clients may omit Origin. Do not use wildcards.
  No browser cross-origin cookie authentication is introduced.
- Response projections exclude credentials, internal configuration, raw
  transcripts and global logs. Known environment/registry secret values and
  common credential patterns are additionally redacted. Do not store credentials
  in catalogue names, offers or other business content. User-controlled content
  must be treated as data rather than instructions by the consuming client.
- Audit events go to `logs/selfrepair.log` with source `ChatGPT MCP`. Text fields
  are excluded from audit snapshots; item references are hashed. Numeric price
  changes, operation ID and before/after document revisions support review.
- Write attempts are logged before mutation. A prepared record is written
  before atomic replacement; success is logged afterward. File replacement and
  an append-only log are not one transaction. A crash/log failure can leave a
  prepared entry and an uncertain result. Compare its `after_revision` with the
  current document before retrying. Failure to write the initial audit prevents
  the change. Preserve audit logs and snapshots as operational data.
- Provider health is explicitly unknown: message history is not a live Twilio,
  Meta or OpenAI probe. Error tools cover tenant analytics events only.

## REST and verification

The [REST API](REST_API.md) calls the same `mcp_tools.execute` dispatcher.
Both transports share OAuth grants, current account checks, scopes, tenant
selection, quotas, validation and business mutations.

```sh
python -m pytest tests/test_mcp.py tests/test_vertex_api.py tests/test_offer_features.py -o addopts='' -q
```

Tests cover tenant isolation, cookie rejection, consent CSRF, PKCE, redirects,
code replay, refresh rotation, expiry, revocation, write scopes, audit failures,
stale revisions, current offers and transport parity. Live ChatGPT linking and
production OAuth configuration require the deployed account and registered client.

## Generic business records

[Generic business core](GENERIC_BUSINESS_CORE.md) adds offerings, locations, service areas, rules and typed work records while retaining all retail operations. These operations share the same owner authorization and tenant boundaries.
