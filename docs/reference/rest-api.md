# Vertex Seven REST API

The existing MCP operations are also available under `/api/v1`. Both transports
call `service.mcp_tools.execute`, then the same `BusinessManagement`, retrieval,
analytics, validation and audit functions. REST contains only route mapping,
query/body parsing and HTTP error formatting. It makes no AI calls.

## Authentication and tenant scope

Use `Authorization: Bearer <access token>` from the existing Vertex OAuth flow.
See [MCP setup](mcp.md) for registered clients, S256 PKCE and owner consent. Both
transports deliberately belong to the same protected Vertex resource: request
the canonical resource `https://YOUR_HOST/mcp` when obtaining or refreshing tokens.
This REST facade accepts those same tokens; it does not accept dashboard cookies,
unrelated OAuth tokens, API keys or caller-provided tenant IDs.

`MCP_PUBLIC_URL` must match the HTTPS `BASE_URL`, and clients must be registered in
the server-only `MCP_OAUTH_CLIENTS` configuration. Without configuration, both
transports fail closed. Owners sign in through `/console/` and complete
authenticator verification before returning to the consent page.

- Only the MCP-supported `business_owner` identity can obtain a grant.
- The tenant comes from that grant's server-authenticated identity. `tenant`
  parameters are rejected; owning another company does not widen an existing grant.
- Reads require `business:read`; writes also require `business:write` and business
  activation. Users and roles remain read-only.
- Tokens expire and revoke identically on both transports. Each owner/tenant shares
  one 60-request/minute quota across MCP and REST, plus the existing IP limiter.
- If an Origin header is supplied, it must match the same MCP origin allowlist.
  There is no permissive CORS or cookie fallback. Bearer-only REST mutations do not
  need CSRF tokens; browser OAuth consent and revocation still do.

## Main endpoints

| Method and path | Existing operation |
| --- | --- |
| `GET /api/v1/statistics` | `get_statistics` |
| `GET /api/v1/catalog` | `get_catalog` |
| `GET /api/v1/catalog/search?query=...` | `search_catalog` |
| `POST /api/v1/catalog/items` | `add_catalog_item` |
| `PATCH /api/v1/catalog/items` | `update_catalog_item` |
| `POST /api/v1/catalog/items/disable` | `disable_catalog_item` |
| `GET /api/v1/offers` | `get_offers` |
| `POST /api/v1/offers` | `create_offer` |
| `PATCH /api/v1/offers/{offer_id}` | `update_offer` |
| `POST /api/v1/offers/{offer_id}/disable` | `disable_offer` |
| `GET /api/v1/roles` | `get_roles` |
| `GET /api/v1/users` | `get_users` |
| `GET /api/v1/health` | `get_agent_health` |
| `GET /api/v1/errors` | `get_error_summary` |
| `GET /api/v1/errors/recent` | `get_recent_errors` |

The public contract is available at `GET /api/v1/openapi.json` and in the
[repository](../../schemas/vertex-api.openapi.json). It covers every mapped REST
operation, including business overview, conversations, usage and service status.
Generate it with `python scripts/export_vertex_api.py` after changing shared MCP
arguments or REST mappings.

GET arguments use query parameters, with bounded integer `minutes`, `offset` and
`limit` where supported. Statistics accepts either `minutes` or both `start_at`
and `end_at`; explicit ranges require time zones and are at most 30 days.
Unknown/repeated query parameters fail validation. Writes accept JSON only, with
no query parameters and a 64 KiB request limit. Path selectors must not also be
supplied in the body.

### Update one catalog item

Read `/api/v1/catalog` to obtain the current revision, then PATCH
`/api/v1/catalog/items` with:

```json
{
  "category": "Devices",
  "name": "Example product",
  "expected_revision": "REPLACE_WITH_THE_REVISION_FROM_GET_CATALOG",
  "changes": {"price": 7.99}
}
```

The change is visible through both MCP and the existing console. Conflicting
revisions return 409; re-read before retrying. Offer fields and deal validation use
the existing offer store, including archived offers, BOGO and minimum-spend deals.

Success responses are the MCP tool's structured result directly, without a JSON-RPC
envelope. Failures use `{"error":{"code":"...","message":"..."}}` with an
appropriate HTTP status. Replies are `Cache-Control: no-store`. Raw transcripts,
credentials, stack traces and global error logs are excluded. Health reports
observed availability, not an unverified claim that external providers are healthy.

Writes retain the same audit workflow, with `source: Vertex REST API` instead of
`ChatGPT MCP`. No user deletion, role writes, arbitrary SQL/code, payments or refunds
are exposed. An uncertain write failure requires re-reading the revision.

## Validation

```sh
python -m pytest tests/test_vertex_api.py tests/test_mcp.py -o addopts='' -q
```

The tests cover shared dispatch/results, OAuth scope enforcement, tenant isolation,
revocation, revision conflicts, invalid arguments, audit records and activation.
Live OAuth client linking requires deployment-specific configuration and validation.

## Console setup

Open **Settings → Connected apps → MCP & API connections** for the public contract, OAuth
endpoints, registered client IDs and a copyable request. Register the
integration's exact HTTPS callback with the platform operator, request
`business:read` with S256 PKCE, and approve from the assigned business-owner
account. Include the MCP resource URL in both the authorization and token
requests. The resulting access token authenticates `GET /api/v1/health`.
Owners can view and revoke their MCP and REST grants together.

An HTTP 503 with an integration configuration error requires an operator to
correct the HTTPS address or OAuth client settings. An HTTP 401 from a
configured REST endpoint means it needs a valid Vertex access token.

## Generic business records

[Generic business core](generic-business-core.md) adds offerings, locations, service areas, rules and typed work records while retaining all retail operations. These operations share the same owner authorization and tenant boundaries.
