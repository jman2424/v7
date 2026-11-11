# Prepaid AI usage billing

V7 subscriptions pay for platform access and setup. They include no AI credit.
Customer use of the central OpenAI account consumes a separate prepaid GBP
balance. Existing subscription terms and previously approved invoices are
retained. New legacy monthly API charge approvals are blocked.

## Ownership and storage

`service/usage_wallet.py` uses the existing private database. All five new tables
in `20261011042205_ai_usage_wallet.sql` force tenant RLS; public, anonymous and
client API roles have no access. The restricted backend cannot update or delete
financial ledger entries. SQLite development uses the same nonnegative
constraints and immutable-entry triggers.

Authenticated management requests resolve the caller's authorized company.
Public chat uses the existing signed session and approved-origin controls.
WhatsApp uses verified webhook recipients. Provider callers receive that exact
server-resolved company through `usage_context`; a missing or malformed context
prevents a central API request. No user-supplied claim of ChatGPT coverage or
external billing changes that policy. OpenAI keys remain server-only.

## Top-ups and payment verification

Owners and platform administrators use `/billing/usage-credit/checkout` with a
server pack ID and a stable request ID. Packs currently grant £5, £20 or £50
credit. With `V7_VAT_REGISTERED=false` (the default), those packs cost £5, £20
or £50: no VAT is charged. Only set this flag to `true` after VAT registration
is effective; then configure a verified exclusive 20% Stripe tax rate and the
packs cost £6, £24 or £60. Tax is excluded from usable credit. Existing payment
snapshots keep their recorded tax treatment. There is no automatic recharge. A top-up does not activate an unpaid
subscription, and an internal platform-owned agent has no customer checkout.

Before calling Stripe, V7 persists the tenant, reference, exact amounts, tax
rate, environment and pack. Network retries reuse that binding and Stripe's
idempotency key. Redirects and browser success messages never grant credit.
Only the existing raw-body signature-verified Stripe webhook fulfills payment.
The handler retrieves canonical Checkout, payment, charge, invoice and tax data
and matches the saved binding. Unpaid/asynchronous, mismatched or test/live
payments cannot credit a balance. Actual payment identity prevents duplicate
credit across different webhook event IDs. Subscription payments never create
usage credit.

Production usage-credit checkout and fulfillment require Stripe live mode.
Test-mode payments remain available in development/tests and cannot fund a
production wallet. The live dashboard disables credit checkout until live
Stripe payments are configured; legacy subscription setup remains separate.

Refunds and disputes retrieve canonical cumulative state and reconcile the
original payment. Repeated or older events cannot restore a refunded payment.
Credit already spent or reserved is represented as separate debt/review state;
the usable balance never becomes negative. Disputes pause paid requests, and a
confirmed winning outcome restores only the previously reversed amount.

Configure the existing Stripe endpoint to deliver Checkout completion and
asynchronous outcomes, invoice events, charge refunds and dispute lifecycle
events. See `service/usage_payments.py` for the supported event set. Monitor
failed webhook deliveries and use Stripe's replay mechanism after correcting
configuration. Never fulfill a top-up from a browser return URL.

## Request reservation and settlement

`service/api_usage.py` and `service/speech_transcription.py` reserve a
conservative cost ceiling before any provider side effect. PostgreSQL locks
the company's wallet row; SQLite uses `BEGIN IMMEDIATE`. Concurrent reservations
therefore share one available balance. Unknown pricing, stale FX, insufficient
credit, financial debt or reconciliation holds prevent paid work; existing
saved-knowledge fallbacks remain usable.

Accounting uses integer USD nanodollars and GBP nanounits, with Decimal
conversion and rounding upward once to a GBP nanounit. Cached input is excluded
from ordinary input, cache writes are priced separately, and provider output
tokens include reasoning where applicable. The ledger stores actual/requested
model, input/output/cache counts, channel, purpose, timestamp, provider cost,
exact price snapshot/version, FX and markup. It never stores prompts or replies.
The charge uses the reservation's database snapshots even if settings change.
An analytics write failure does not turn a paid request into free usage.

Known actual costs settle once and release unused reserved funds. A verified
zero cost or explicit provider authentication/quota/model rejection before
inference releases the full reservation. Failed calls with unknown spend,
missing usage, unknown actual models, or costs exceeding the held ceiling retain
funds and set a review hold. No timeout automatically releases an uncertain
payment obligation. Provider retries are disabled for accounted calls.

A pending reservation older than 30 minutes also pauses further paid work until
verified usage resolves it. A process crash never silently returns uncertain
credit to the available balance.

Paid transcription verifies a canonical PCM recording of at most 60 seconds
before reserving its duration-based ceiling. Browser recordings are converted
to WAV locally. WhatsApp compressed recordings use the deployment's trusted
FFmpeg decoder with fixed arguments, pipe-only input, bounded output, a timeout
and no inherited application secrets. Missing or failed decoding asks the
customer to send text; it never bypasses verification or credit checks.

For reconciliation, establish the actual usage from the provider, locate the
exact tenant/reservation reference, and call `settle_usage` with the verified
cost. Repeating settlement is harmless. Do not guess zero, delete reservations,
or bypass a hold. Costs exceeding the ceiling require operator investigation;
do not charge beyond available credit automatically. Administrative credit
adjustments require a reason, actor and stable request ID, and append a ledger
entry without erasing history.

## Pricing and funding

The central provider account must be funded by Vertex Seven. Customer Stripe
top-ups do not automatically transfer money to OpenAI. Provider failures remain
possible even when a customer has V7 credit. Do not offer funded AI service until
the central account, model access and webhook delivery are ready.

The default markup is **0%**. `V7_USAGE_MARKUP_PERCENT` changes it only after
commercial agreement and disclosure; the current value appears in the credit
dashboard. `V7_MODEL_PRICING_JSON` overrides integer nanodollar rates by exact
model ID, with `input`, `cached`, `output`, optional `cache_write` and optional
`long_context`. Explicit dated response model IDs need explicit prices too.
`V7_AUDIO_PRICING_JSON` supports `second` or paired `input`/`output` rates.
Invalid configuration fails closed.

The existing ECB/Frankfurter USD/GBP reference is the default. An operator can
set `V7_USAGE_USD_GBP_RATE` and `V7_USAGE_RATE_DATE`; invalid, future-dated or
more-than-four-day-old references block paid work. FX and markup are frozen per
reservation. Changes apply only to later requests. Review provider price changes
against the official pricing documentation before updating production rates.

MCP and REST business-management tools currently make no central OpenAI call.
Inference performed and billed independently by ChatGPT or another provider is
therefore not charged again by V7. A ChatGPT subscription does not pay for V7's
central API requests. V7 does not currently accept a tenant's provider key or
an unverified request-level billing exemption.

## Viewing and notifications

`view_costs` permits only authorized company history, token counts, charges,
receipts and balances at `/billing/usage-credit`. Owners can manually top up.
Only platform administrators can use the paginated company overview or audited
adjustment endpoint. Operational warnings disclose no amounts to staff without
cost permissions. Subscription and WhatsApp screens and a workspace warning
show low, exhausted and review-required credit states. The low threshold is
`V7_USAGE_LOW_BALANCE_PENCE` (default £2). These are in-app notifications.

## Validation

Mocked provider and Stripe tests cover wrong tenant access, missing contexts,
payment signatures, canonical amount/currency/tax mismatches, duplicate
payments/events, simultaneous reservations, immutable entries, exact cached
token prices, frozen FX/markup, refunds/disputes and unknown failed requests.
Run the matching prepaid tests plus existing subscription, model, WhatsApp, MCP
and authentication regressions. Native PostgreSQL tests require an explicitly
named local disposable database; never aim those fixtures at production.
