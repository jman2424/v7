# Business intelligence and modular capabilities

Owner brief: [original requirements](business-intelligence-brief.md). Audit baseline:
`db765d9f8ba1dba450935c240cb96e573ac52bfe`, 29 October 2026. This is a
living implementation record, not a claim that the entire vision is delivered.

## Invariants

- Business understanding, relevant retrieval, conversation continuity, truthful
  answers and appropriate recommendations are core on **Starter, Business and
  Scale**. No premium intelligence switch. Existing AI usage credit still applies.
- Keep the Flask orchestrator, deterministic services and Svelte console. Do not
  create a second catalogue, a second identity system or a multi-agent framework.
- Tenant identity comes from the existing authenticated/verified channel scope;
  never from model arguments. Authentication, authorization, isolation, billing,
  validation and audits are mandatory infrastructure, never optional modules.
- No fabricated price, policy, availability or action outcome. An opened page or
  form is not a completed booking, payment, refund or sale.
- New optional execution capabilities default off. Existing enabled native forms
  must be explicitly grandfathered before introducing a stricter module policy.
- No new subscription prices, external communications, provider accounts, paid
  infrastructure or production customer mutations are implied by this plan.

## A. Existing capabilities (code, not just older documentation)

| Area | Implementation and actual boundary |
| --- | --- |
| Business identity and goals | `sales_playbook.py`, `tenant_sales_context.py`, `sales_agent.py`; owner UI in `Console.svelte`. Business focus, customer type, differentiators, qualification questions, fulfilment, tone and goals already exist. |
| Structured facts | `BusinessCore.public_context`, catalog/FAQ/policy/branch stores; native offerings project alongside the original catalogue. Private work records are not customer knowledge. |
| Website retrieval | `website_knowledge.py`: bounded public HTTPS import with SSRF defenses; current configured site checked before use. It is a saved snapshot, not a live crawl each turn. |
| Relevant context and memory | `MessageHandlerV7._grounded_answer`, `agent_knowledge.py`, `conversation_memory.py`; current-question retrieval, selected offerings, public size rules and bounded same-session history. |
| Verification and responses | `grounded_conversation.py`, `grounded_money.py`, `grounded_statements.py`, structured response schema and approved destinations. One ordinary accounted model call; bounded repair rather than unrestricted tool loops. |
| Practical native actions | Consultation slots, quote/callback requests in `conversion_actions.py`; verified native booking changes/cancellation in `booking_management.py`. Persistent requests and private receipts, not external-calendar authority. |
| Customer/lead records | Existing CRM, lead/session state and owner conversation review. A new general CRM is unnecessary. |
| Management integrations | `mcp_tools.py`/MCP routes and REST management services enforce OAuth scopes and roles. Management MCP is not an outbound customer-chat integration. |
| Performance | Version-checked tenant read cache, request reuse, pooled DB/HTTP clients, bounded history/prompts, staged timing and durable optional telemetry outbox already exist. |
| Analytics | Channel/conversation/funnel and request records exist. They do not prove revenue or external conversions. |

`docs/ARCHITECTURE.md`, `GENERIC_BUSINESS_CORE.md` and `AGENT_EVALUATION.md`
contain historical descriptions; runtime code and current tests take precedence.

## B. Verified weaknesses and limits

1. Small knowledge sets can retain unrelated FAQs after a focused match. Strong
   question matches coexist with incidental answer-text matches, encouraging long
   answers (observed AI-credit question accompanied by plan-pricing information).
2. Exact duplicate FAQ questions can hold conflicting answers. Neither a stable
   insertion order nor a model choice establishes which policy is authoritative.
3. Owners configure knowledge in several working screens but lack one bounded,
   actionable review of missing information, duplicate/conflicting FAQs and website
   import freshness. No semantic contradiction detector is currently proven.
4. Native form switches, subscription/activation checks and management permissions
   exist separately. There is no unified three-level optional-module policy with
   platform kill switches, tenant grants and owner settings at every boundary.
5. External orders, arbitrary CRM writes, refunds and external booking changes
   require real adapters and customer ownership verification; public website text
   cannot supply these permissions or credentials.
6. Existing evaluations cover important regressions but do not establish universal
   industry, language or provider reliability. Offline reference replay is not a
   model-quality result. Full replies consistently below two seconds remain unproven.
7. The first live check reproduced a metadata reliability failure: valid public
   capability statement IDs lacked their matching source citations. The validator
   correctly rejected the answer. A narrowly scoped, single accounted correction
   now handles missing source citations for approved, request-local statements.
   Unknown/malformed IDs, disabled form capabilities, unsafe prose and unauthorized
   actions retain the rejection path. Repeated errors are still rejected; no
   citation is automatically added or accepted.
8. A later live missing-discount case exposed a renderer problem: the model's
   explicit uncertainty was replaced by a complete but unrelated monthly-pricing
   FAQ. When supported model prose explicitly identifies missing information but
   cites an unrelated FAQ, that FAQ's facts are now withheld. The existing verified
   unknown-policy statement and an approved support destination are used without
   another model call. Original agent metadata still passes its validators;
   malformed citations, links and unauthorized actions cannot use this path.
   This does not enable free-form policy prose or remove existing exceptions.

## C–D. Extensions and architecture

Treat the existing public profile, playbook, offerings, FAQs, policy, imported site,
enabled channel actions and session as the Business Intelligence Layer. Compose
these at request time; do not duplicate them into a new authoritative document.

Curated structured prices and policies outrank imported website material; customer
statements remain preferences/context, never new business facts. Exact conflicting
FAQ topics require owner review; broader contradictions need a separate, measured
design. Relevant context must retain price qualifications, required rules, selected
options and changed customer preferences even when reducing prompt size.

For execution, introduce one typed module registry over the existing services.
Each entry names tools, dependencies, configuration/approval requirements, risk,
supported channels and verified result types. Effective permission must be:

`global enabled ∧ plan allowed ∧ tenant grant ∧ owner enabled ∧ integration ready
∧ existing actor/action permission ∧ required customer verification/approval`.

Do not cache these permissions as public knowledge. Recheck on tool discovery,
direct execution and each background job step. Tenant-bound arguments are built by
the server; reject arbitrary tool IDs/URLs and unrecognized operations. A platform
kill switch or owner revocation prevents the next side effect even if an old chat
advertised the action. Do not expose existing owner MCP credentials to visitors.

Reuse native request idempotency and durable records. New workflow execution needs
a tenant-scoped durable state machine: pending approval, authorized, executing,
succeeded, failed, outcome unknown, cancelled. Recheck policy immediately before
each side effect; use provider idempotency where supported. If revocation races an
external request, reconcile the recorded result and stop subsequent steps. Never
claim that a committed external action was undone by disabling its module.

## E. Administrator experience

- Keep existing profile, catalogue, FAQs, website, goals and tone editors.
- Add an on-demand Knowledge review in Agent settings: missing sources, exact FAQ
  conflicts/duplicates, inactive facts and imported-site freshness with links to the
  appropriate editor. Reports advise; they do not auto-edit business facts.
- Later add Modules: explain available/enabled/blocked and the specific unmet
  dependency. Platform admins control global policy and grants; owners control
  only permitted configuration. Staff follow existing explicit permissions.
- Templates remain reviewed starting points. Applying one must not silently
  overwrite current facts or activate tools.
- Knowledge suggestions require owner approval and provenance; never learn
  authoritative prices/policies automatically from visitor messages.

## F–G. Security, cost and performance

Keep existing CSRF/session checks, tenant-scoped RLS, role permissions, accounting,
rate limits, source validation and audit records. Public knowledge excludes private
work, CRM data, credentials and customer messages. Review endpoints are management
only and must not fetch arbitrary URLs, use a model or return raw documents.

First changes use deterministic in-process review/retrieval and existing storage.
No vector database, queue service, continuous crawler or model judge is required.
Run reviews on demand outside the customer critical path. Record dataset bounds
and incomplete review explicitly; a green checklist is not certification.

Measure retrieval, prompt bytes/tokens, model calls, validation and total time with
existing diagnostics. Fewer irrelevant facts can reduce cost but cannot establish
a latency promise without controlled live measurements. The previously authorized
£2 benchmark cap persists; no new paid run is assumed or budget reset here.

## H. Prioritized delivery and acceptance gates

| Stage | Work / dependency | Tests and acceptance | Rollback |
| --- | --- | --- | --- |
| 1a — core relevance | Focus FAQ context and prevent exact conflicting FAQ topics from being treated as reliable facts. Preserve source text, price rules, current choices, multilingual facts and broad-query fallback. | Small/large knowledge sets; answer-only distinctive facts; compound questions; prices/estimates; follow-up/changed mind; contradictory/private/inactive FAQs; existing grounding suite. No extra model calls. | Revert code; no data migration. |
| 1b — knowledge review | Authenticated on-demand report and owner UI over existing documents. Every tier uses the same core service. | Tenant swap, read permissions, no raw private data, empty/malformed sources, duplicates/conflicts, site changed/stale/unknown timestamps; build/type checks. | Remove endpoint/UI; saved data unchanged. |
| 2 — module control | Registry + durable platform/plan/tenant policy, owner controls and audit. Inventory native switches and grandfather enabled actions before enforcing new gates. No global intelligence toggle. | Discovery/execution/direct API/job policy matrix; forged tenant/tool; stale cache/chat; disable mid-flight; revision races; billing unaffected; DB RLS tests. | Preserve explicit legacy grants; staged migration with reversible new policy records. |
| 3 — useful native modules | Wrap existing lead, quote, product assistance and native booking services first; add support-case creation only with tenant-owned schema, confirmation and owner inbox. Depends on stage 2. | Real durable result/receipt, duplicates/concurrent submissions, explicit refusal/approval, tool outage, cancellation, no invented availability/payment/refund. | Disable optional module; retain records for authorized read/recovery. |
| 4 — external adapters | Choose systems per client; consented credentials, minimum scopes, customer ownership checks and typed adapter contract. No arbitrary “anything” executor. | Provider sandbox contract tests; timeouts, rate limits, retries/idempotency, revoked credentials, uncertain outcomes and signed webhooks. | Disconnect/revoke; reconcile in-flight outcomes, do not delete customer records. |
| 5 — approved automation | Durable bounded workflows, per-step approval, scheduling and verified outcome events; approved knowledge-gap suggestions. Requires stages 2–4 and evidence of demand. | Job revocation/restart/replay; no repeated external effects; event deduplication; conversion attribution from verified results only. | Pause new steps/schedules, reconcile committed effects. |

## Progress

- [x] Preserve original brief and inventory existing implementation on a separate branch.
- [x] Establish compatibility, all-tier intelligence and default-off module rules.
- [x] Stage 1a implementation; targeted regression verification passed (full CI pending).
- [x] Stage 1b implementation; tenant/permission tests and synthetic Chrome UI check passed (full CI pending).
- [ ] Stage 2 policy/migration implementation.
- [ ] Stages 3–5; require preceding gates and concrete business/provider configuration.

No new feature from this branch is deployed merely by checking a box here. Add
exact test results, commit and release status as each stage completes.

### First-stage validation record

- Earlier agent/grounding regression group: 500 passed; subsequent retrieval and
  evaluation additions were separately checked in the 76-test expanded group.
- Citation correction/grounding group: 274 passed. Original negative tests for
  uncited business policies and unknown/cross-tenant statements remain unchanged.
- Frontend: 102 tests passed; Svelte check zero errors/warnings; production build
  passed with the existing large-bundle advisory. Chrome checked the card, escaped
  HTML-like FAQ topics and the tenant-specific FAQ editor destination.
- Offline matrix expanded from 67 scenarios/200 turns to 70 scenarios/208 turns.
  The expanded reference replay passes in the test group. This is not live quality.
- Initial live run: 6/7 scenarios; 18/19 executed turns passed, one dependent turn
  was not executed after its preceding failure. Cost USD 0.0131848. The failure
  above was retained and motivated the bounded repair; final live checks follow.
- First committed live checks were also retained: 17/18 executed default turns
  (6/7 scenarios), and 7/8 new focused turns (2/3 scenarios). They exposed a second
  citation omission and the unrelated-policy rendering issue above. The focused
  rendering/grounding regression group passed 201 tests after those fixes.
- The first live rerun of the policy-gap correction showed the model repeating
  the same unrelated pricing evidence after correction. This led to the
  deterministic withholding/verified-unknown path above, covered by 224 tests.
- A local full-suite attempt was interrupted after discovering an optional-source
  diagnostic regression. That issue is fixed and its test passes. Sandbox temp ACL
  failures required the previously authorized normal test environment. Neither
  interrupted runs nor environment failures are counted as passing full suites.
- No new modules, provider integrations, customer actions, subscription changes or
  production deployments are enabled by this first-stage branch.

Implementation note: the [OpenAI structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)
distinguishes schema compliance from factual/semantic correctness. V7 continues to
enforce its own cross-reference, policy, price and action guards after correction.
