# Launch readiness report — 12 November 2026

Scope: the ten-part brief "Final launch readiness, business imports and automatic data
synchronisation". This records what was built, what was tested and how, and what still
stands between V7 and taking on paying customers.

**Verdict: not yet production-ready.** The software for every workstream now exists and
passes its automated tests. Four things outside the code remain: legal sign-off, and
real-world tests of sign-in providers, email/phone providers and store connections,
none of which can be done without accounts, numbers and authorisation that only the
platform owner can supply.

How to read "tested" below:

- **Automated** — run on the development machine against the real application code,
  with outside services (Google, Microsoft, Resend, Twilio, WooCommerce, Shopify)
  replaced by stand-ins that behave as their documentation describes.
- **Browser** — clicked through in a real browser against a local copy of the app.
- **Live** — exercised against the real outside service. **Nothing in this report was
  tested live.**

## 1. What was built in this piece of work

| Area | Change |
|---|---|
| Business Sync Engine | New. Connected sources, durable job queue with retries, per-field source-of-truth rules, conflict review, automatic application of routine changes, history and undo. |
| Connectors | New, read-only: WooCommerce, Shopify, custom JSON feed; signed change notifications for each. |
| Import workflow | New. Upload CSV or a JSON bundle (products/services, FAQs/policies, locations and hours) → validation → duplicate matching → preview → correct or exclude → apply → history with source, tool and authoriser. |
| Console | New page **My Business → Data Sources & Sync**. Six workspaces unchanged. |
| Authorisation record | Every source stores who authorised it, when, for which domain, and the terms version. |
| Sign-in | Microsoft is shown next to Google on the sign-in page (it was hidden). |
| Legal drafts | `docs/legal/`: proposed Acceptable Use Policy, proposed import and synchronisation terms, questions for the solicitor. `/terms` gains a summary of the import terms. |
| Database | New PostgreSQL migration `20261112090000_business_sync.sql` (five private tables, tenant row-level security). SQLite tables create themselves. |
| Documentation | `docs/reference/business-sync.md`, `docs/guides/business-imports.md`. |

Already present before this work and left unchanged: manual business approval, Google
and Microsoft sign-in, the Email and Phone agents, the MCP and REST interfaces.

## 2. Results by workstream

### 2.1 Manual business eligibility — implemented earlier; re-tested

- Every new business needs a decision by a signed-in platform operator. Approve, reject
  and request-information are supported; the applicant can correct and ask again.
- AI research is optional, advisory and has no way to set a decision.
- Checkout refuses a business that is not approved, at entry and again immediately
  before the payment session is created. Sign-in providers cannot create an account, so
  they cannot route around approval (new test).
- Automated: `tests/test_business_applications.py` (25 tests) pass.
- **Not done:** legal review. Intake stays closed in the product until the operator
  records that review as complete. Old unscoped Stripe Payment Links, if any exist, must
  be disabled in Stripe by hand.

### 2.2 Import workflow — new

Supported import methods: CSV file; JSON bundle (the format to ask Claude or Codex to
produce); re-import of an updated file against the same source. Not supported: Excel
files directly (save as CSV), PDFs or images, direct database connections.

Automated (`tests/test_business_imports.py`, 9 tests): authorisation required; nothing
written before approval; existing product matched instead of duplicated; invalid and
repeated rows reported; instruction-like text set aside; reviewer correction; stale
approval refused; re-import respects manual edits; rejection remembered; hand-written
FAQ answers kept; locations and hours imported; undo; other business untouched.

Browser: uploaded a file, reviewed, applied, saw it in the catalogue and in Recent
changes; checked at phone width with no sideways scrolling.

### 2.3 Sync engine — new

Supported synchronisation sources: WooCommerce, Shopify, custom JSON feed (scheduled
checks every 15 minutes to 24 hours, plus optional signed notifications). Manual
refresh for everything else. Automatic monitoring of public web pages was **not**
built; the existing owner-triggered website import is unchanged.

Automated (`tests/test_business_sync.py`, 18 tests), mapped to the brief's list:

| Brief item | Result |
|---|---|
| Initial synchronisation | Previewed; nothing written until approved. Pass. |
| Product creation / price update / deletion | Applied automatically when authorised. Pass. |
| Duplicate webhooks | Second delivery acknowledged, processed once. Pass. |
| Delayed events | Older notification ignored. Pass. |
| Source API failures, lost connections | Retried with growing delays, data untouched, "needs attention" after six tries. Pass. |
| Authentication expiry | Not retried; asks to reconnect; reconnecting resumes. Pass. |
| Conflicting edits, manual overrides | V7 value kept; review raised; choice remembered. Pass. |
| Reconnection | Same store only; a different address is refused. Pass. |
| Data rollback | Undo restores exactly; refused if edited since. Pass. |
| Cross-tenant isolation | Second business cannot read, trigger or receive anything. Pass. |
| AI retrieval after synchronisation | See 2.7. Pass. |
| Source disconnection | Credentials destroyed, jobs cancelled, endpoint closed, data kept. Pass. |
| Empty source response | Nothing removed; review raised. Pass. |
| Forged or altered notifications | Rejected. Pass. |
| Requests steered to internal or other hosts | Refused before connecting. Pass. |

**Not done:** no request has reached a real WooCommerce or Shopify store.

### 2.4 Google and Microsoft sign-in — implemented earlier; Microsoft un-hidden; re-tested

Automated (`tests/test_oidc_login.py` 18 tests, `tests/test_launch_signin.py` 7 new):
linking, returning sign-in (still requires the authenticator code), a matching email
does not link or sign in, a provider identity cannot be claimed by a second account,
expired or future-dated tokens refused, abandoned sign-in expires, cancelled consent,
callback state is single-use and tied to the browser, disabled account refused, and
password sign-in still works after a provider is removed.

Behaviour to be aware of: a provider signs in an account that **already exists** and
has linked it. A brand-new person registers by email first. This is deliberate.

**Not done:** no sign-in against real Google or Microsoft. That needs client IDs and
secrets registered with each provider and the callback addresses in `env.example`.

### 2.5 Email agent — implemented earlier; re-tested

Automated (`test_email_reply_workflow`, `test_business_channel_providers`,
`test_business_channel_security`, `test_business_channel_store`, `test_client_email_setup`,
`test_channel_improvements`; all pass): signed intake, correct
business by recipient address, review and automatic modes, replies only to the real
sender, forged headers ignored, loops and attachments sent to review, daily and
per-sender limits, duplicate delivery, uncertain sends never repeated, AI notice,
billing through the business's own AI balance, hostile email content. New: a queued
email reply uses synchronised prices.

Limits: attachments are not read (the message goes to a person). Each email is
answered on its own; earlier emails in a thread are not used as context.

**Not done:** no real email received or sent. As last recorded (30 October), receiving
was not enabled at the mail provider and no webhook was registered.

### 2.6 Phone agent — implemented earlier; re-tested; incomplete as a "voice agent"

Automated (12 tests in `test_phone_channel_flow` plus provider and security tests):
signed call intake, AI and synthetic-voice notice before anything else, review mode
(takes a message) and automatic mode (answers routine questions), silence retry, keypad
0 to leave a message, turn and call limits, signed continuation bound to the number,
timeouts hand over to the team. New: a queued call answer uses synchronised prices.

Honest limits against the brief's list:

| Brief item | Status |
|---|---|
| Incoming calls, continuity within a call, silence handling | Automated tests pass. |
| Speech understanding, accents | Done by the telephone provider's speech recognition. **Not measured.** |
| Interruptions | **Not supported.** The agent is turn-based: caller speaks, agent answers. |
| Supported languages | Fixed prompts in English, French, Spanish, German. Not tested with speakers. |
| Human handover | Takes a message for the team. **Does not transfer the call to a person.** |
| Concurrent calls, call reliability, provider failures | Queue and timeouts tested in isolation. **No load test; no real calls.** |
| Billing accuracy | AI usage charged through the same accounted path as chat (tested there). Provider call charges are separate and not tracked by V7. |
| Privacy and recording | No audio is recorded or stored. Tested. |

**Not done:** no real call. No phone number or provider account has been supplied.

### 2.7 Synchronised information reaching every channel — new test

`tests/test_sync_channels.py` (3 tests): after a sync changes a price and deletes a
product, the website chat endpoint and the WhatsApp, email and phone handlers all give
the new price and none offers the deleted product; the other business's assistant
knows nothing of it. Every channel calls the same handler over the same catalogue.

### 2.8 MCP — implemented earlier; re-tested with two businesses

Automated (52 tests across `test_mcp`, `test_mcp_security_followup`,
`test_vertex_api`): sign-in and consent, PKCE, code replay, refresh rotation, expiry,
revocation, read-only scope cannot write, all 37 tools reject a caller-supplied
business, per-tool permissions, rate limit, audit, secrets never returned. New: two
owners with their own tokens at once; A sees synchronised data, B sees only its own
and cannot change A's product by naming it; a change made through MCP counts as a
manual edit that sync will not overwrite.

MCP covers: overview, statistics, conversation statistics, popular query categories,
catalogue, offers, offerings, locations, service areas, rules, users and roles (read),
health and usage; and writes for catalogue items, offers and offerings. It does not
expose raw conversation text, revenue, payments or role changes.

**Not done:** no real MCP client (ChatGPT, Claude or another) has been connected. The
tests speak the protocol directly; they are not a client compatibility test.

## 3. Security findings

No new weakness was found in existing code during this work. Controls added:

- Outbound requests go only to the one host the owner authorised, over HTTPS, to a
  verified public address, with no redirects (protects against requests being steered
  to internal systems).
- Store credentials are encrypted, tied to their business, never returned.
- Notifications are accepted only with a valid signature from that source's secret.
- Imported text is stripped of markup; instruction-like text needs a person.
- Only an owner or platform operator can connect, apply or disconnect; staff can view.

Open points: see HIGH-4 and MEDIUM-5 below.

## 4. Performance

- Not load-tested. The deployment still runs one web worker (existing limitation).
- A full comparison downloads the whole product list each time (50–100 per request).
  With the background worker on this is off the request path. With it off, connecting
  or pressing Sync Now runs in the web request and could exceed the 90-second limit for
  a store with thousands of products.

## 5. Remaining issues

### BLOCKER — prevents safe production onboarding

1. **Legal review not done.** Acceptable Use Policy, application terms, import and
   synchronisation terms, privacy retention. Drafts and questions are in `docs/legal/`.
2. **No live test of Google or Microsoft sign-in.** Needs provider credentials.
3. **No live test of the Email agent.** Needs receiving enabled, a webhook, a controlled
   inbox and permission to send to an approved address.
4. **No live test of the Phone agent.** Needs a number, provider credentials and
   permission to place test calls to it.
5. **No live test of a store connection.** Needs a WooCommerce and a Shopify
   development store.
6. **New database tables not yet applied anywhere live.** Apply the migration (if the
   live system has moved to PostgreSQL) before switching the sync worker on.

### HIGH

1. **Phone agent is not a conversational voice agent.** No interruptions, no call
   transfer, no measured accuracy. Decide whether that is acceptable for launch or
   whether Phone is offered as "takes messages" only.
2. **No real MCP client connected.**
3. **Sync worker is off by default.** Without `V7_SYNC_WORKER=true` scheduled updates do
   not run (the page says so).
4. **Notification endpoints share the general per-address rate limit.** A store making
   bulk changes may be told to retry; the providers do retry, and the scheduled check
   catches up, but it has not been observed live.
5. **Full Python test suite was not run on the development machine** (about 40
   minutes). CI runs it on push, including the PostgreSQL tests.

### MEDIUM

1. Connectors cover products, prices, categories and availability only. Hours, FAQs,
   offers and delivery rules come from an import or the console.
2. One item per store product at its lowest variant price; no descriptions.
3. Excel must be saved as CSV; no PDF or image import.
4. Sign-in providers do not create accounts (deliberate; see 2.4).
5. If `SECRET_KEY` is rotated without `V7_SYNC_ENCRYPTION_KEY` set, stored store
   credentials become unreadable and each source asks to reconnect.
6. Email: no attachment reading, no thread memory.
7. The older "sheet" catalogue layout cannot be synchronised or imported into.
8. Moving a live SQLite deployment to PostgreSQL does not yet copy the new sync tables.

### LOW

1. Console is English-only (existing).
2. WooCommerce currency is not checked against the V7 price list.
3. No email is sent to the owner when a review is waiting; it shows in the console.

## 6. Customer authorisation requirements

Before any source is read: a signed-in owner (or platform operator) ticks the
authorisation statement shown on the page. Stored with the source: the statement, the
account, the time, the authorised domain, the data categories and
`data-import-sync-terms-2026-11-draft-1`. A different store address needs a new
connection and a new authorisation.

## 7. Legal documents requiring review

1. `docs/legal/acceptable-use-policy-draft.md`
2. `docs/legal/data-import-and-sync-terms-draft.md`
3. The public `/terms` and `/acceptable-use` pages (already marked as drafts)
4. The privacy policy's retention schedule, against the import history kept

## 8. Checks run

See the end of this file for the exact commands and counts.

### Commands and counts (development machine, 12–13 November 2026)

| Check | Result |
|---|---|
| `ruff check .` | Passed. |
| `mypy .` | Passed, 200 source files. |
| `cd frontend && npm run check` | 0 errors, 0 warnings. |
| `cd frontend && npm test` | 145 passed. |
| New tests: `test_business_sync`, `test_business_imports`, `test_sync_channels`, `test_launch_signin` | All passed. |
| Regression set of 48 test files (sync, imports, sign-in, approval, billing, AI Budget, channels, MCP, REST, security boundaries, public site) | 1144 passed, 5 skipped, 0 failed. The skips need a PostgreSQL test database. |
| Full `pytest` and the PostgreSQL tests | Not run locally. They run in CI after the push. |
| Browser | Data Sources & Sync: upload, review, apply, history; desktop and phone width. |
| Live providers | None. |
