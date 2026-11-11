# AI Budget implementation and release record

## Scope and financial holds

Implement the 1 November 2026 AI Budget specification inside V7. Preserve all
existing subscriptions, setup fees, promo codes, balances, immutable usage/payment
history and agreed usage prices. No real payments or paid AI tests are authorised
for this work. Reuse the existing approved deployed inference integration; local
provider tests use synthetic credentials/responses. No new inference key is needed.
Official OpenAI organisation cost monitoring requires a separate authorised admin
key; no such local credential was found. Unsupported funding-balance APIs must not
be invented. OpenAI funding configuration remains a manual official-dashboard action.

The new recharge mechanism is off by default and has a separate production live
switch. Do not enable live off-session charging or change usage pricing until the
owner approves the final financial/configuration review. Each customer must also
explicitly authorise a saved payment method, fixed £5 recharge, threshold and cap.
The existing business-approval/intake hold remains in effect.

## Audit findings

- `usage_wallet` already uses exact integer nano-GBP accounting, immutable entries,
  tenant-scoped transactions, reservation ceilings, settlement, refund/dispute
  reversals and reconciliation holds. Reuse it; do not introduce another balance.
- `usage_payments` already snapshots server prices and verifies Checkout, intent,
  charge, invoice, tax and dispute state before adding funds. Its existing public
  packs are £5/£20/£50. Add £10/£25/£50 while retaining legacy pending-checkout
  reconciliation and retries.
- `api_usage.tracked_completion` centrally meters website/WhatsApp/email/phone
  text generation with per-tenant usage context. Audio paths and optional service
  callers need an explicit coverage inventory and fail-closed tests.
- Customer UI and legacy credit DTOs expose provider pricing/token/reservation
  internals. Add a simple AI Budget projection and keep operating costs and
  funding controls platform-only. Preserve legacy integration contracts.
- Recharge mandates, capped off-session payments, threshold-crossing email/outbox
  notifications and provider funding monitoring are absent.
- Current source defaults the usage markup to 0%; this is not evidence of the
  deployed setting or of profitability. Fees, Climate, FX overhead, reserve and
  margin must be configured/observed explicitly, never assumed to be zero.
- Production schema inspection confirms forced RLS on existing wallet/payment/
  ledger/checkout/contract tables. Baseline observations are retained separately
  in the local release evidence, without customer or production financial data
  in source control.
- The owner subsequently authorised aggregate production financial reads. The
  baseline reconciles and the existing Stripe fee breakdown was inspected. No
  balances, fees, pricing settings or live payment controls were changed.

## Implementation plan

1. Add private tenant settings, immutable authorisation events, saved Stripe setup
   authorisations, capped recharge attempts and notification outbox. Add private
   operator funding settings/health/cost observations. Additive migration only;
   no rewrite or conversion of existing GBP balances.
2. Implement canonical Stripe Setup/PaymentIntent verification, fixed £5 attempts,
   tenant locking, calendar-month UTC caps, idempotent retries within the provider
   retention window, cancellation, authentication/failure handling and ledger reuse.
3. Observe settled balances transactionally; enqueue threshold crossings and
   payment/cap notices once. Reuse the transactional email transport and existing
   service process with durable claims and bounded retry. Never send setup-test mail.
4. Add the owner AI Budget dashboard, initial-funding checkout guidance and simple
   customer transaction/monthly-spending views. Add operator AI Provider Funding
   and financial operations, with official read-only provider monitoring and
   clearly labelled missing/delayed information.
5. Audit all metered channels; add provider funding failure distinction, safe
   request gating/recovery, transparent usage-rate disclosure, reconciliation and
   fee/margin analysis without silently changing existing pricing.
6. Add synthetic payment/refund/dispute/auth/concurrency tests, native PostgreSQL
   RLS/atomicity/migration tests and accessible/mobile/localised frontend tests.
   Run relevant suites, lint/type/build and GitHub security checks.
7. Produce exact migration/configuration/financial-assumption and rollback evidence.
   Request any remaining production migration/live-charge approval only after the
   implementation is concrete and reviewable. Do not claim unverified readiness.

## Progress

- [x] Read full specification and existing account/payment/wallet/provider surfaces.
- [x] Inspect production schema and permitted baseline counts.
- [x] Confirm official provider cost/admin interfaces and Stripe setup/off-session mechanisms.
- [x] Core settings/state machines/additive migration (production apply pending).
- [x] Alerts/outbox/provider monitoring/financial reports.
- [x] Customer and operator UI plus guided separate onboarding checkouts.
- [x] Channel inventory and synthetic payment, provider, concurrency and security coverage.
- [x] Customer alert persistence, owner/operator boundaries and mobile/RTL browser checks.
- [x] Original release: 4,098 backend tests, 247 native runtime tests and 34 migration tests passed; 90 environment-specific full-suite skips.
- [ ] Follow-up native worker-discovery regression and deployment verification.
- [ ] Final financial review and controlled release.

## Implemented boundaries

`usage_wallet` is still the sole balance and immutable financial ledger. Values
remain integer nano-GBP; no legacy units are converted. The ten new private
tables hold preferences, explicit card authorisations, fixed-value payment
attempts, immutable control events, notification deliveries, settlement costs
and operator funding observations. Every tenant table has forced tenant RLS.
The operator report compares wallet balance, held funds and debt with immutable
ledger deltas in a single database snapshot and flags discrepancies without
rewriting money. The four platform tables are denied to public Supabase roles; changes to funding
assumptions additionally require a live, verified operator session.

Manual purchases retain the original canonical Checkout/intent/charge/invoice
verifier and legacy pack IDs. The new screen offers only £10/£25/£50. Refunds
and disputes use the existing cumulative reversal logic. A refund/reversal
revokes recharge authorisation so it cannot immediately trigger a replacement
purchase. Customer credit is never reduced for Stripe fees.

Automatic recharge uses Checkout setup mode and a canonical off-session
SetupIntent/payment method. It stores the exact displayed consent, owner
credential revision, cap and version. A fixed £5 PaymentIntent uses a stable
provider idempotency key. One open attempt per tenant and a locked UTC month
counter include pending/uncertain purchases. Month attribution is the month
dispatch starts; already-created provider intents retain their original month.
The final dispatch lock order is wallet then settings. A manual top-up that
commits first cancels an unnecessary automatic purchase.

Definitive card failures/authentication requests pause purchases until the owner
resolves/cancels the intent and explicitly authorises a new setup. Uncertain
creations retain cap capacity, reuse their exact key at most three times within
23 hours, and then require review. An opt-out commits locally before any Stripe
call. A dispatched payment may complete after opt-out and is still reconciled.
The ledger update is transactional; a crash between credit and final queue state
is recovered by canonical reconciliation without another charge or credit.

The existing business-application permit system also binds PaymentIntent IDs.
It resolves or refuses ambiguous payments before eligibility withdrawal. A new
business cannot fund AI or authorise recharges around its approval gate. Disabled,
deleted or changed authorising credentials prevent new dispatches.

Threshold notifications are appended inside the settled-ledger transaction,
not on temporary inference reservations. Dashboard alerts default on; email
alerts require preference opt-in. Transactional payment/cap notices accompany
the explicit recharge mandate. Outbox claims, bounded retry and stable recipient
keys survive restarts. Uncertain mail older than the provider idempotency window
goes to review. SMTP transports remain at-least-once; Resend supports the stable
idempotency key. No live setup email or real test payment has been sent.

## Metering inventory

Website chat, WhatsApp, email generation and phone text responses enter the
existing handler with tenant/channel `usage_context`, then the central
`api_usage.tracked_completion`. Both Chat Completions and Responses provider
adapters remain behind that meter. Verified-duration audio transcription has its
own reservation/settlement using the same wallet. Browser speech playback uses
local speech synthesis. No independent embeddings/images/cloud-TTS purchase path
was found. Third-party telephony/number/Meta costs are separate; no invented tool
charge is added. Internal application research/platform inference remains
platform-funded and is not deducted from a customer wallet.

Known pre-inference provider funding/limit rejections release reservations and
record only an allowlisted code. A shared durable circuit permits one recovery
probe per cooldown. Healthy state has a short process cache; monitoring failures
cannot discard a paid reply. Uncertain timeouts retain the established hold.
No unmetered retry or generic answer is introduced to disguise a billing outage.

## Owner experience and pricing disclosure

The owner UI offers AI Budget, balance/used/added, meaningful paginated history,
receipts, initial funding preference, independent alerts and capped recharge
authorisation. English/Spanish/French/Arabic are covered, with mobile/keyboard
controls. Model comparisons show V7 GBP service rates for ordinary owners;
technical provider auditing remains platform-only. Existing authorised legacy
API response fields are retained.

Onboarding preserves the existing separate subscription and setup checkouts.
It shows the selected first-month subscription, unpaid setup and chosen initial
AI funds together as a planned total, explicitly explaining the separate secure
payments. Initial funding and optional card setup complete after activation;
funds are not granted merely because a subscription/redirect completed. The
initial funding preference is never an automatic monthly purchase.

`/ai-usage-pricing` publishes the effective service rates from the same price/FX
snapshot used by metering, together with reservations, carry-forward, payment,
refund and automatic-purchase terms. No markup or usage price is changed by this
release. Business insights gain only their authorised tenant's simple budget
summary. Neither insights nor an AI tool can modify mandates or caps.

## Production configuration and release sequence

1. Review the PR and green native PostgreSQL/security/functional checks. Take a
   standard production backup and record wallet/ledger/payment totals immediately
   before and after rollout. Do not include financial records in source control.
2. Apply `20261101171037_ai_budget.sql` before deploying this code. It adds ten
   tables, indexes, FKs, RLS and least-privilege grants; it does not update an
   existing wallet, ledger, subscription, customer, price or payment row.
3. Deploy with `V7_AUTO_RECHARGE_LIVE_ENABLED=false`. Set
   `V7_AI_BUDGET_WORKER=true` for durable notifications, fee collection and
   reconciliation. This uses the existing app process, not another paid service.
4. Keep the existing Stripe live key and signed `/billing/stripe/webhook` endpoint.
   Ensure Checkout completion, PaymentIntent succeeded/processing/payment_failed/
   requires_action/canceled and the existing refund/dispute events are delivered.
   Existing subscription/invoice event subscriptions must remain enabled. No new
   recurring Stripe Price is created for AI funding. No card data is stored in V7.
5. The owner configures the correct OpenAI API organisation's payment method,
   initial funding, provider auto recharge/threshold/amount/monthly limit and
   organisation/project limits in the official billing dashboard. Do not automate
   purchases or transfer Stripe receipts to an API key.
6. Optional read-only monitoring uses a separately authorised `OPENAI_ADMIN_KEY`
   in server secrets, plus safe `OPENAI_ORG_ID`/`OPENAI_PROJECT_ID` metadata/filter.
   It does not replace `OPENAI_API_KEY`. Set `V7_PROVIDER_COST_MONITOR=true` for
   hourly delayed cost/limit observations. Missing access is shown unavailable.
7. Enter reviewed payment/Climate/FX/risk/infrastructure/margin assumptions and
   an owner-reported reserve plus target. These declarations are not verified
   OpenAI balances. Costs, cash, fees and profit with incomplete evidence stay
   unknown. The page can never change customer usage prices.
8. Only after the owner separately approves a sustainable published usage-pricing
   policy and live activation may the server live switch be enabled. Production
   additionally requires complete, reviewed, non-loss-making £5 assumptions.
   Each customer still has to explicitly authorise its card and monthly cap.
   VAT-inclusive automatic purchases retain their own subtotal/tax snapshot;
   VAT status, invoicing arrangements and fee contract require review before a
   future VAT/configuration change. Existing intake/legal holds remain closed.

Official interfaces: [OpenAI costs](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs),
[OpenAI spend limits](https://developers.openai.com/api/reference/cli/resources/admin/subresources/organization/subresources/spend_limit),
[OpenAI billing](https://platform.openai.com/settings/organization/billing/overview),
[Stripe setup](https://docs.stripe.com/payments/setup-intents),
[Stripe off-session intents](https://docs.stripe.com/api/payment_intents/create).
There is no assumed provider prepaid-balance or credit-purchase API.

## Recovery and known operational limits

Production verification found that background jobs cannot call the interactive
administrator inventory. The follow-up `20261102035654_ai_budget_worker_discovery.sql`
adds private queue-ownership metadata, following the existing telemetry pattern.
It backfills financial tenants without modifying wallets, permits own-tenant
enqueue and bounded backend discovery, and leaves the administrator inventory
guard and all financial RLS unchanged. The worker reads at most 25 keys per page
without impersonating a user; a failed tenant cannot prevent other work.

First disable the live recharge switch, then disable the budget worker if needed.
Do not delete new tables, outstanding authorisations/attempts, notices or ledger
history. Reconcile all dispatched/unknown intents before retiring a worker or
replacing consent. Keep the new signed webhook handler deployed while outstanding
automatic payments/refunds can arrive: an old application release cannot reconcile
this new payment kind. Financial settlement fixes take priority over rolling back
UI code. An additive migration is not reversed by an application rollback.

The frozen SQLite-to-Supabase preparation tool also inventories/preserves these
control records and raw TEXT outbox payloads; unknown source tables still fail
closed. Imported mandates are not a substitute for verifying active account
revisions and live-payment configuration after migration.

Stripe fees/Climate vary by payment method and contract. A single observed fee
does not establish future profitability. Official costs are delayed, provider
limits can be unavailable, and an owner reserve declaration is unverified. Actual
Climate, FX, tax allocations, dispute costs and infrastructure must be reconciled
before claiming net accounting profit. Healthy provider API responses establish
service recovery, not that provider auto recharge succeeded. Background batching
is bounded; larger installations can run the same leased consumer on additional
app processes without creating duplicate payments.
