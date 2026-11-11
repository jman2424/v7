# Optional agent module controls — stage 2a

This extends the existing Flask services and Svelte Business hub. It does not
introduce another model provider, agent framework, database table or pricing
tier. No production settings are migrated or enabled by this code change.

## What is implemented

One registry describes the six existing operational capabilities: appointment
requests, quote requests, callbacks, native appointment management, support email
and business calls. Tool names, supported channels and approval requirements are
fixed server-side metadata, never instructions or arbitrary operations supplied
by the model. Business knowledge, conversation quality, grounding and security
are core across every subscription plan and are not optional modules.

`service/agent_modules.py` evaluates platform restrictions and the tenant's
operator grants and owner switches. Existing service configuration, integration
readiness, active-account checks, actor permissions, signatures, credit, consent,
customer receipts, approvals, rate limits and idempotency remain additional
mandatory controls. A module grant alone grants no customer identity or provider
access and configures no external system.

Effective checks are used at:

- Native form discovery, deterministic form suggestions and final form rendering
  after generation. Revocation removes the proposed form while preserving the
  accepted business-information answer.
- Public action availability and the native SQLite/PostgreSQL service immediately
  before creating a request or reserving a slot. Direct HTTP, hub and internal
  callers reuse that guarded service. A retry can read a previously committed
  idempotent receipt; it cannot perform a second side effect.
- Native booking changes/cancellation. Viewing an existing receipt remains
  possible. Disabling new appointments does not disable independently authorised
  cancellation; rescheduling requires both capabilities. Receipt verification and
  customer confirmation remain required by the public routes.
- Signed inbound email/calls, queued generation, approval/send and spoken-reply
  polling through the existing channel activation check. Revocation is rechecked
  after generation and before a later side effect. Local content retention still
  runs; a disabled module does not claim to erase or undo existing records.

Permissions are not cached. Native actions batch their module-policy reads, and
channel checks reuse the authoritative migrated grant decision. Default all-plan
policy requires no extra billing-plan read. There are no extra model calls.

## Owner/operator controls and compatibility

Business hub now contains **What your agent is allowed to do**, with effective
state and a reason when setup or permissions prevent a capability. Owners can
change only enabled switches for permitted modules. Platform operators alone can
grant modules. Staff follow the existing role/permission boundary and cannot
grant themselves access. All changes use existing authenticated, tenant-scoped,
CSRF-protected, revision-bound and audited document writes.

The policy uses the existing private tenant-document store (`agent_modules.json`).
It is not added to raw-file or MCP editing allowlists. No production DDL or new
global tenant access is required.

Before initialization, only explicitly inventoried legacy services retain their
existing enablement rules. The operator reviews their current switches and
explicitly initializes the new policy. Existing enabled-service choices are
preserved at that point. A new grant leaves a previously disabled service off;
provider/privacy/service setup is still required. Owners cannot initialize or
modify grants through the settings API. Missing future registry entries default
off in older policies; malformed policy fails closed for optional execution.

After initialization, the module document is the sole email/phone grant source.
The older channel-grant endpoint remains compatible and updates those same grant
fields with a revision check; it cannot overwrite other module/owner settings.
The duplicate legacy grant form is then hidden in the console. Old grant files
cannot override a migrated module revocation.

GET `/admin/api/agent-modules` returns the current revision and safe state.
PUT of that path accepts only `revision` and a complete boolean `enabled` map.
PUT `/admin/api/agent-modules/grants` accepts only `revision` and the operator's
complete boolean `grants` map. Unknown fields, tools, plan claims, non-booleans and
cross-tenant requests are rejected. A stale update must reload before retrying.

## Platform-wide control: explicit current limit

This phase's global policy is deployment-owned `V7_AGENT_MODULE_POLICY_JSON`:

```json
{"disabled":["email"],"plans":{"quote":["starter","business","scale"]}}
```

Only known module and existing plan IDs are allowed. Missing policy permits the
existing plan set; there is no new premium-intelligence or default paid-feature
restriction. A restricted module uses the server's actual configured plan, not a
client's selected plan or model argument. Malformed global policy blocks optional
operations without making knowledge/core security optional.

**This is not yet a live global administrator switch.** Changing deployment
environment configuration requires the operator's normal rollout/restart across
instances. Per-company grants and owner switches take effect through existing
storage. A durable global policy service/console and its migration/recovery design
remain unfinished stage 2 work; do not mark the entire roadmap stage complete.

An operation already accepted by a provider may finish if revocation races its
network request. Reconcile its receipt and stop subsequent steps; do not claim
that changing a switch unsent an email or undid a booking. Do not downgrade past
these enforcement guards while relying on module-only revocations; first mirror
required restrictions into the legacy service configuration under operator review.

## Verification and remaining transformation work

Synthetic tests cover legacy migration, owner/operator roles, tenant isolation,
revision races, grant escalation, raw-file bypass, JSON types, actual-plan checks,
global kill policy, malformed policy, registry extension, direct execution, native
booking changes, queued send blocking, mid-generation revocation and audit failure.
Request tests cover CSRF, duplicate saves, revoked settings and late company
responses. A native PostgreSQL test uses the existing private document port and is
included by the existing `test_postgres*.py` CI selection.

The final test counts and exact CI revision are recorded in the PR. Local native
PostgreSQL skips are not counted as passes. No live customer email/call, client
account, production database mutation or paid AI request is part of this work.

Local checks: **215 passed, 3 skipped** in the combined regression group; the
final focused policy group passed **26 tests**, including the last storage-failure
and future-module compatibility cases. These runs overlap. All **116 frontend
tests** passed, Svelte/TypeScript reported zero errors/warnings, repository Ruff
passed, and the production frontend build passed. Chrome verification against
invented localhost data confirmed explicit initialization, preservation of prior
switches, removal of duplicate grant controls and disabling quote requests. Mobile
width testing showed no horizontal overflow. Native PostgreSQL verification is
delegated to the existing disposable CI jobs, not a production database.

This establishes policy infrastructure for the next stages. A full bounded
multi-step executor, support cases, third-party order/calendar/refund adapters,
approved scheduled work and the global policy console are not delivered here.
They need their remaining roadmap gates and concrete business/provider authority.
