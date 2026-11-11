# Conversation quality and clear-chat investigation — 30 October 2026

**Status: incremental implementation verified; broader quality work remains.** The last completed live
scorecard improved from 2/16 to 12/16 passing turns. That is a useful improvement,
not a release pass. The final retrieval follow-up and six updated regression
fixtures still need execution. Automatic approval review could not authorise the
final test command because the account reached a usage limit; the review made
no safety determination. That temporary block has cleared: the final affected
suite passes **389 tests**, including the six updated assertions/fixtures. A
further unchanged live scorecard again passed **12/16**, using 16 provider calls
and costing US$0.0204044. The four failures were translation setup, the first and
third clothing-continuity turns, and outage-policy uncertainty. This remains an
incremental improvement, not a declaration that every requested quality goal passed.

Branch: `codex/conversation-quality-clear-chat`. Baseline main revision:
`5e25d1996cab11df6813ad6ab5364370d313688e`.

The [original brief](conversation-quality-brief.md) is preserved. The
[recorded scorecards](evaluations/conversation-quality-2026-10-30.json) retain
all four live iterations, including failures, fixture/prompt/runtime hashes,
synthetic answers and costs. This report distinguishes completed measurements
from the latest code that has not yet been rechecked.

## Existing architecture and evidence

The web route authenticates conversation tokens, checks tenant/origin and tester
limits, enforces resource allowances, and dispatches through `message_handler`.
The same V7 handler is shared with existing API/WhatsApp entry points. It builds
tenant business identity, public catalogue facts, business rules, FAQs, relevant
website passages, approved destinations and enabled request actions. Tenant-aware
read snapshots and invalidation already exist; this task does not replace them.

`grounded_conversation.answer` ranks and bounds that knowledge, supplies bounded
recent history and validated task memory, and makes the accounted structured
completion. Selection, customer requirements, monetary amounts, percentages,
URLs and action claims have server validation. Consequential replies are rendered
from complete approved source units. Buttons resolve approved destination IDs;
request-form execution remains a separate authorised, idempotent server workflow.

Read-only inspection of the live Vertex identity, FAQ and catalogue confirmed
that its basic service description and prices existed. The company-description
failure was not evidence that those records were absent. No live tenant knowledge,
wallet, credentials, subscription or business action was changed for this task.

Three focused offline reproducers failed against the initial implementation:

1. A supported assistant description mentioning approved booking pages became
   “That detail is not established in the available business policy.”
2. Handling a customer's delivery/returns enquiries became a pricing FAQ.
3. A comparison lost its useful qualifying question and repeated a monthly price.

## Verified causes and changes

| Cause | Targeted change |
| --- | --- |
| Broad process keywords treated navigation nouns and customer enquiry topics as formal business policies. | Narrow topic normalization plus a descriptive business-guidance path. Actual policy, money and action claims retain their protected boundaries. |
| A cited FAQ containing commercial terms could override a noncommercial explanation. | Separate noncommercial business guidance from complete commercial source units. |
| The protected renderer discarded suitability explanations and qualifying questions, including when prices shared their paragraph. | Retain independently safe noncommercial sentences alongside the unchanged full terms; validate the resulting answer again. |
| Catalogue amounts and a full pricing FAQ repeated the same price. | Suppress only an exactly matching catalogue amount when name, amount, currency and billing unit match a selected complete source unit. Keep descriptions, qualifications and full policy text. Distinct prices, currencies, names and billing periods are not merged. |
| A deterministic tariff shortcut intercepted personalised advice. | Recommendation requests use the existing grounded call. Narrow factual tariff requests retain the existing fallback. |
| Plan names/prices alone did not establish real entitlements. | Supply an allowlist of current server billing entitlements for the internal platform business. Do not advertise obsolete unenforced message counters. No new intelligence tier gate. |
| Monetary validation recognised cited amounts but did not universally bind an amount to an offering name. | Force structured catalogue monetary answers through the known-price renderer. A negative price-swapping test caught this before deployment. New entitlement context deliberately contains no monetary amounts. |
| Small knowledge bases previewed unrelated records after a weak/no match. | Scope the preview for customer-setup problems, retaining identity, rules and relevant records. The latest follow-up also removes nested plan tables from setup prompts without mutating the tenant source; explicit plan turns retain them. This latest follow-up is not yet rechecked. |
| Nonempty new model requirements replaced previous verified requirements. | Merge bounded verified requirements unless an evidence-bound correction/removal changes them. Keep explicit rejection and retired-requirement checks. |
| Missing policy details could become a different policy or a transaction disclaimer. | Extend the existing explicit-gap handling and render honest uncertainty. Compensation is protected. Do not infer compensation terms from a no-sales-guarantee policy. |
| Generic support buttons accompanied a more specific destination. | Remove redundant support navigation unless the customer asks for contact/support; preserve approved link validation. |

The existing single completion derives intent and next step. A small local task
hint guides customer-problem application or qualification; it creates neither
business facts nor permissions. Instructions now distinguish proposed setup,
personalised advice, costs, unknown policies and purchase readiness. No model
classifier, judge, new provider, multi-agent product pipeline or new transaction
tool was added.

An unsupported percentage echoed in a denial is narrowly removed only when it
repeats the customer's figure and selects a known no-guarantee policy. Every
original guard then runs again, and the complete verified policy is rendered.
Positive guarantees, extra percentages, unsafe URLs and action-completion claims
remain rejection cases. This avoids paying for an otherwise unnecessary retry.

## Clear conversation

The shared customer widget now has a **Clear conversation** button with an inline
confirmation and **Keep chatting** option. Escape dismisses the confirmation.
Controls remain outside the logo/header and use the existing theme.

Confirming clears the visible transcript, draft, queued peer rows and browser
conversation identity, stops voice, aborts pending chat delivery, and obtains a
fresh signed conversation identity. Generation checks prevent late JSON/stream
chunks or old action-option responses from restoring the previous chat.

The reset propagates only to the matching conversation in the existing
tenant-and-parent-site browser channel. Bounded token tombstones and a birth-time
fence reject delayed/replayed old transcripts. Missing, expired or future reset
timestamps are rejected. No cross-tenant storage is cleared; no new persistent
localStorage store is introduced.

Local clearing is disabled while submitting a business request. A reset from a
peer does not cancel an already submitted request, change its idempotency key or
erase its eventual receipt. Old server records follow existing retention; this
is a fresh-chat control, not a data-erasure request or a billing/quota reset.

Chrome verification with fictional localhost data completed:

- Start a conversation, remember “green means good”, cancel the clear prompt.
- Open another tab and observe the same conversation.
- Confirm clearing; both tabs return to the greeting.
- Reload a peer: previous messages stay absent.
- Ask about green again: the new conversation has no saved meaning.
- Inspect the confirmation at desktop and real 390px embedded width.

Proof files are in the workspace `outputs/` directory:
`v7-clear-conversation-preview.jpg` and `v7-clear-conversation-mobile.jpg`.

## Repeatable evaluation and results

Run `python -m evals.agent_eval --quality` for offline reference replay. It uses
the real validator and isolated temporary SQLite accounting. Offline references
prove fixture/guard behavior, not model quality. `--live` is an explicit paid
gate with request, runtime and worst-case spending limits; it must stay inside
the cumulative user-authorised budget. There are no reference-answer substitutes
for failed live responses.

The fixed scorecard contains 16 turns in 12 scenarios: company understanding,
qualification, budget/entitlements, translation setup, clothing enquiry workload,
multi-turn continuity, honest guarantees, complete costs, unknown policy,
restaurant suitability, translation assessment, disabled actions, product
recommendation and conflicting refund evidence. Expected checks were frozen
before the paid runs. Every iteration has the same fixture hash.

The before run used an archive of baseline main. Application files were compared
byte-for-byte with `git show`; only the identical evaluation harness was overlaid.
These are synthetic **component** measurements, not production HTTP/browser
latencies, 50 production conversations, or statistical proof of universal quality.

| Measurement | Before | Latest completed live iteration |
| --- | ---: | ---: |
| Turns meeting every objective check | 2/16 | 12/16 |
| Complete scenarios passing | 2/12 | 10/12 |
| Provider requests | 16 | 17 |
| Input tokens | 76,047 | 89,733 |
| Output tokens | 3,172 | 3,186 |
| Cached input tokens | 63,232 | 68,992 |
| Model p50 / p95 | 1.91s / 5.33s | 1.66s / 3.00s |
| Validated component p50 / p95 | 1.95s / 5.38s | 1.74s / 3.81s |
| Provider-reported priced cost | US$0.0165244 | US$0.0202932 |
| Unknown-cost requests | 0 | 0 |

The interim iterations passed 3/16 and 6/16. All four runs cost US$0.0763528
combined. The cumulative ledger, including earlier tasks, records known costs
US$1.46351907 plus conservative unknown holds for a total US$1.56549667. At the
ledger's deliberately conservative £1/US$ plus 20% buffer this is £1.878596004,
within the user's £2 limit. No active quality-test reservations remain.

The final affected suite ran after all source changes; it passed 389/389 in
70.93 seconds. The final live results are recorded as `release` in the scorecard.
Total spending for this quality task is US$0.0967572; the cumulative conservative
ledger total is US$1.58590107 (GBP1.903081284 under its £1/US$ plus 20% buffer).
The user-authorised £2 cap remains unchanged, with no active reservations.

Input tokens and this run's API cost increased. Do not market the change as a
proven production speed/cost improvement. The final nested-plan/context follow-up
was included in the final `release` measurement. It has not produced a full
quality pass or a proven production speed/cost improvement.

### Scorecard and review rubric

Objective checks cover approved sources/actions/navigation, exact configured
facts, minimum useful content, validated requirements, no known bad fallback,
bounded length, required qualifying questions and per-price duplicate counts.

For each output, also review the recorded answer against these 0–2 dimensions:

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Relevance/application | Wrong task or canned deferral | Relevant but generic | Applies supported facts to the actual problem |
| Recommendation | Unsupported, premature or absent | Correct option with weak explanation | Suitable option and supported reason/trade-off |
| Continuity | Drops or contradicts context | Retains only some useful context | Uses current requirements and corrections |
| Efficiency | Repetitive/distracting | Usable with avoidable material | Concise, well structured, complete necessary terms |
| Uncertainty/actions | Invented entitlement or completion | Safe but vague | Clear supported boundary and useful next step |

Any invented price, entitlement, action completion or tenant disclosure is a
release failure regardless of the total score. No paid model graded itself.
Engineering inspection of recorded outputs is supplementary; this is not a claim
that an independent human panel has reviewed them.

Manual inspection identified weaknesses that the objective pass count misses:
the final clothing recommendation became a tariff list without a direct named
recommendation; some plan replies still add irrelevant no-guarantee/transaction
units; translation setup remains generic. Consequently 12/16 is **not** an
accuracy percentage or release approval. Four objectively failing turns are
translation setup and the first three clothing-continuity turns.

## Regression verification

- Full Python run before the final follow-ups: **3,672 passed, 6 failed,
  76 skipped**, 1,561.95 seconds. The failures were three exact old-price-wording
  assertions and three new peer-reset fixtures without the now-required timestamp.
  Assertions were updated to retain consent/source checks and verify the known
  rendered prices; reset fixtures now carry valid timestamps. **Rerun pending.**
- Intermediate affected groups passed 309, 255 and 175 tests respectively.
  These are overlapping runs, not additive totals and not a final-head claim.
- The new offline quality references passed all 16 turns before the final
  nested-plan/customer-history follow-up. Final reference replay is pending.
- Frontend: **102 tests passed**; Svelte check **0 errors, 0 warnings**; build
  succeeded. No owner-console source was changed afterward.
- Latest Ruff check and JavaScript syntax checks passed; final static rerun is
  recorded separately if further edits occur.

Existing tenant/cache freshness, role/origin/token, credit/ledger, API, MCP,
WhatsApp, disabled-action and injected-content regressions remain part of the
full suite. The 76 environment-dependent skips were not executed by this run;
in particular it is not a fresh production PostgreSQL/integration certification.
No live refund, booking, payment, email or client-credit test was performed.

## Security and remaining release work

No auth, role, CSRF, tenant identifiers, origin allowlists, credit enforcement,
billing ledger, integration credentials or tool-execution permissions were
relaxed. No migration is needed. Descriptive guidance still relies on model
grounding for general semantic correctness; the deterministic guards are not a
universal entailment engine. English task/topic patterns have broader paraphrase
and multilingual coverage work remaining; existing languages are not claimed
fully evaluated by these English scenarios.

Before release:

1. Re-run all affected regressions, especially the six updated fixtures, the new
   nested-plan/customer-history tests, and default/extended/quality references.
2. Recheck the four failing live turns and inspect actual recommendations and
   relevant policy selection. Reserve any spend in the cumulative ledger first.
3. Preserve the unchanged fixed scorecard; add unseen cases rather than changing
   expectations to turn failures into passes. Broaden to more languages and
   realistic tenant configurations after these gaps are resolved.
4. Run the CI environment-specific database/integration jobs, create a reviewable
   change, and deploy only after verification. No merge, push or deployment of
   this unfinished branch has been performed.
