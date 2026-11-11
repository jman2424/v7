# Conversation reliability and account section search

This change extends the existing Flask/Svelte implementation. It does not change
tenant authorization, financial verification, MCP scopes or API credentials.

## Findings and fixes

- Earlier incident logs show accepted model responses, not provider failures, for
  the supplied Python/small-talk transcript. A later extractive response stage
  could replace a clarification/refusal with a cited onboarding FAQ. Such
  conversational replies now bypass that unrelated extraction; consequential
  policy questions still retain their complete approved conditions.
- Fuzzy FAQ lookup could score sentence filler against FAQ wording. Filler-only
  requests now require an exact FAQ question, and additional filler words do not
  select onboarding instructions. Valid business FAQs still take priority.
- Signed conversation identity and shared tenant-scoped memory already existed.
  However, input-guard replies skipped transcript persistence. Guarded turns now
  enter the same bounded history. Six validated, non-secret customer definitions
  can survive recent-message eviction in that same conversation's existing
  private memory payload. Owner disable/clear, generation and retention controls
  apply; this is not cross-conversation identity matching. Definitions are local
  customer quotations, never authoritative business policies or commands.
- Ordinary CRM writes could raise after an answer completed and discard the
  answer. Those failures now preserve ordinary replies. A failed contact capture
  explicitly reports failure and does not preserve a false success in history.
- The widget aborts chat after 45 seconds, while model settings permit a 60-second
  SDK timeout. Web turns now share a 30-second provider budget, with at most
  20 seconds per model call. Expired budgets do not start another provider call.
  A known local skip after reservation settles zero; a real provider timeout
  retains the existing uncertain-cost accounting protections. SDK retries remain
  disabled. These bounds are not a guarantee against database/network outages.
- Render's free service was observed displaying its waking-up interstitial.
  [Render documents](https://render.com/docs/free) spin-down after 15 idle minutes
  and roughly a minute to restart. This happens before application handling and
  can exceed the widget deadline. The plan was not changed. The widget now
  distinguishes non-JSON service-unavailable responses and offers a manual retry;
  it does not automatically repeat potentially paid work. Successful initial
  action-option loading can establish the signed conversation identity before
  the first paid reply, so a lost first response need not lose the conversation.
- Optional action availability has a 10-second browser timeout. Its failure does
  not prevent chat. Consultation, quote and callback routes retain their existing
  consent, signature, origin, idempotency and tenant checks.

Historical logs do not prove the cause of every reported timeout. The observed
cold start, reproducible deadline mismatch and fault-injection results are
distinguished from unproven historical incidents.

## Diagnostics

Content-free JSON events correlate the server-issued request ID with a hashed
conversation ID. Events cover memory read/write, activation, dispatch, retrieval,
CRM, routing, whole-handler/HTTP durations, provider count/model/timeout/token
counts, fixed credit/pricing skip reasons and exception class names. They omit
messages, contact data, prompts, response bodies, credentials and arbitrary
exception strings. Error responses with a valid request ID show a reference in
the widget. Existing usage ledgers remain authoritative for actual costs.

Greetings, known social check-ins, simple definition recall and clear unrelated
task refusals do not invoke the model or retrieve the business catalogue. Other
business questions use the existing accounted grounded answer; rejected/failed
calls pause further paid planning/rewriting attempts within that turn. Imported
website retrieval searches saved content, not the live internet on every turn.

## Account search

The authenticated account header includes **Find account sections**. Search covers
section labels, descriptions and terms such as memory, billing, cancel, models
and staff. It reuses the navigation's live `mayOpenScreen` permission rules,
preserves the selected tenant in URLs and supports Enter, Tab and Escape. Search
does not fetch another client's records or grant access to a hidden section.

## Validation

`test_chat_reliability.py` injects CRM failures, timeouts and exhausted budgets;
checks private-data-safe correlated logs, guarded history, retained definitions
and clear/session boundaries; and checks appropriate saved-knowledge fallback.
`test_customer_business_actions.py` submits real isolated action requests using a
chat-issued identity, then checks deduplication, conflicting submissions, consent,
disabled actions, origin and tenant rejection. MCP scope/isolation and prepaid
usage suites run separately. Widget runtime tests cover cold-start HTML, error
references, first-response timeout identity and optional action failure. Search
tests cover aliases, accents, tenant URLs and current staff/owner permissions.

Paid model quality evaluation remains explicitly enabled through the existing
bounded harness and authorized test key, using synthetic isolated tenant ledgers.
No real customer bookings, emails or payments are created by these tests.
