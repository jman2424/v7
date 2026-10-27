# Response performance

The existing chat pipeline retains its tenant, origin, conversation-token,
permission, credit and answer-validation checks. No provider output is trusted
merely because it arrived quickly.

## Reads and prompts

Each turn checks the current versions of a bounded list of public business
documents. PostgreSQL checks all versions in one RLS-scoped query, returning JSON
only for changed rows. Filesystem storage checks file identities. The bounded
process cache is keyed by storage location and canonical tenant, returns copies,
and is invalidated on writes. Per-turn snapshots reuse each document across
retrieval helpers. Deleted or malformed documents cannot revive old prices.

Accounts, permissions, action enablement, model settings and billing authority
are excluded from that cache. Request-specific retrieval stores are refreshed
from current public documents, including updates made by another worker.

Catalogue matches and remembered choices precede a broader discovery fallback.
Relevant FAQs and pricing conditions accompany those matches. Exact duplicates
in approved statements and core offerings become references to the same complete
source, while server-side validation retains the original facts and conditions.
Recent history keeps its configured budget. At most two relevant older customer
quotations (512 UTF-8 bytes total) supplement it under the same session, tenant,
retention, generation and memory-enabled checks. No summary model call is added.

## Connections and persistence

`V7_POSTGRES_POOL_ENABLED=true` enables a lazy pool of at most four connections
per worker. It defaults on under Render. Gunicorn's preloaded master never owns
pool sockets. TLS verification, restricted-role checks and forced tenant RLS
remain in place on each transaction; tenant scope and search path are local to
that transaction. Independent role probes share a network flush. Existing
tenant-specific OpenAI clients retain their HTTP connection reuse.

Scope initialization now uses one catalog-only query for fresh role, membership,
RLS and ownership checks plus transaction-local settings. No caller or business
query can run before every returned invariant is validated. A rejected scope
rolls back. Lead/contact and current-session metadata share one atomic scoped
upsert instead of two transactions; custom analytics adapters retain the existing
two-method fallback. History, money and audit commits remain synchronous.

After retrieval and its context cap, provider object keys have stable ordering.
Authoritative facts and verified customer selections remain first; list order,
fact values and validators are unchanged. Dynamic destinations/history follow
the stable public facts. This can improve exact-prefix provider cache reuse;
it never caches/replays answers or replaces tenant validation. No extended
provider retention or new API parameter is enabled. See the
[official OpenAI prompt-caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

`V7_ASYNC_TELEMETRY=true` batches only `pipeline_in`, `pipeline_out` and
`pipeline_turn` into one durable commit, then fans them out on a bounded worker
inside the existing web service. It defaults on under Render. Apply migration
`20261027152910_telemetry_pending_tenants.sql` before enabling this path.
The private ownership index contains only tenant keys. Event payloads retain
their original tenant RLS. Shared transaction locks prevent enqueue/cleanup
races, deterministic event IDs cover ambiguous commits, and startup/periodic
recovery replays pending jobs without new customer traffic. Invalid jobs are
dead-lettered. Unavailable queue persistence falls back to original synchronous
telemetry. No separate paid Render service is required.

Conversation memory, inbound/outbound messages, CRM, usage reservations,
settlement and important audit records keep their existing persistence paths.
Worker shutdown leaves durable jobs available for the next worker.

## Transport and measurements

The default `/chat_api` response remains JSON. Clients may opt into
`Accept: text/event-stream`. The server emits `reply_chunk` events only after
the complete reply has passed validation and critical persistence, then a
`complete` event with the usual response payload. Raw provider deltas are never
exposed. A truncated/mismatched stream is removed from the widget, does not
become saved history/buttons, and never automatically repeats a paid request.
This transport does **not** claim to reduce model generation time.

Content-free diagnostics measure authentication, limits, retrieval, cache reuse,
prompt construction/bytes, provider tokens/time, validation, credit reservation
and settlement, memory, CRM, transport persistence and HTTP total time.
`GET /admin/api/performance?tenant=...` requires the existing `analytics.read`
permission and tenant authorization. It reports p50/p95 over a bounded current
worker window (at most 256 samples per metric), not a durable fleet-wide SLO.
Browser first-paint/total timings use a tenant-bound signed conversation token
and origin checks at `/chat/performance`. Only finite numeric timings are accepted.

## Reproducible comparisons

`evals/performance_suite.py` supplies the same 50 synthetic conversations and
129 turns to a frozen checkout and a candidate checkout. `--rich-business`
exercises larger public knowledge. `--http-pipeline` exercises the real Flask
request, token, credit, memory, retrieval and persistence paths with disposable
fictional SQLite tenants. This excludes production PostgreSQL, network and
browser paint overhead. Report these scopes separately.

Offline reference replay verifies deterministic behavior but cannot establish
live answer quality, provider latency, token use or actual API cost. Live mode
requires an explicitly authorized test key and dollar budget, retains unknown
request cost ceilings, stops on provider failure, and never substitutes a
reference answer for a failed live request. Compare actual model-backed turns
as well as all turns so greetings cannot hide slow model calls.
