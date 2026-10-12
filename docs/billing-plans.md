# Monthly V7 plans

`service/plan_catalog.py` is the authoritative GBP catalog, before VAT. Starter
is £99/month plus £149 setup; Business £199 plus £299 setup; Scale £349 plus
£599 setup. Existing Stripe contracts retain their financial terms. A new plan
is selected by an authenticated business owner or platform administrator.

## Billing and activation

The monthly subscription and setup have separate Stripe checkouts and invoices.
Checkout amounts come from the server catalog, never a submitted amount. Each
checkout reference is bound to its plan in `billing_plan_choices`. Verified
Stripe reads must match that binding. A return URL never activates access.
Activation requires a paid monthly invoice, an active subscription and matching
paid setup. Existing discounts remain in use. New prices charge no VAT by default
because Vertex Seven is not VAT-registered. Set `V7_VAT_REGISTERED=true` only after
registration is effective, with a verified exclusive 20% Stripe tax rate.
Public and dashboard prices show the final payable total. Discounts apply before
any configured VAT; recorded invoices keep their original financial amounts.

Changing an active subscription or a paid setup plan needs administrator review.
Before changing an unpaid selection, cancel its pending checkout through the
dashboard. Completed payments cannot be cancelled this way. Historical invoice
callbacks remain in the ledger and cannot grant a retired plan's entitlements.

WhatsApp software access is included in new plans, with a per-company enable/pause control.
Phone numbers are not supplied or included. Number rental/purchase and provider
messaging fees are separate from the V7 subscription, setup and prepaid AI credit.
Provider configuration and existing recipient/signature/origin checks still
apply. Legacy WhatsApp subscriptions are not silently cancelled or repriced.
The previously approved internal website workspace retains its existing exemption.

## Website capacity and prepaid AI

Website and WhatsApp activity counters reset by UTC calendar month, but do not
cap messages or conversations. All plans use `message_usage_model=ai_cost` and
`ai_credit_model=prepaid`, with **no included AI credit**. The number of paid
messages a balance supports depends on the selected model's token prices and
actual input, cached-input and output usage, including conversation context.
One customer message may require multiple provider calls. No exact message
quantity per top-up is promised. Existing anti-abuse rate limits remain active.

Owners manually purchase £5, £20 or £50 credit through Stripe; current totals
are £6, £24 or £60 including 20% VAT. VAT is excluded from usable credit.
Purchased credit carries forward; there is no automatic recharge or overage.
Historical numeric allowance fields remain for API compatibility with explicit
`enforced=false` metadata. No usage data or previous invoices are erased.

The Subscription page lists the platform's allowed models and configured input,
cached-input and output prices through authenticated GET `/admin/api/ai-model`.
Owners may compare models before activation; changes require an active business
and the existing `business_settings.write` permission. Platform administrators
use `models.write`. The existing review, confirm and save endpoints bind the
change to the actor, company, expiring confirmation and settings revision.
Staff cannot change models. Subscription selection affects both planning and
reply rewriting; existing charges keep their original pricing snapshots.

Every central paid AI call uses the prepaid wallet, including businesses with
legacy subscription contracts. Existing previously approved invoices remain
payable; new monthly API charge approvals are disabled to avoid double billing.
See [Prepaid usage billing](prepaid-usage-billing.md) for the financial ledger,
verified payments, refunds/disputes, pricing and reconciliation procedure.

Pauses are durable and appear as in-app alerts to owners and platform admins in
Subscription, the company overview and the workspace warning. They are in-app
notifications; no email or push delivery is claimed.
Review uncertain calls before restoring paid usage; do not assume unknown spend
is zero or erase accounting reservations to force a request through.

Customer-paid transcription currently requires server-verified PCM WAV of
up to 60 seconds with the duration-priced `gpt-transcribe` model. Compressed
recordings whose cost cannot be bounded return a send-text fallback. Existing
approved internal transcription and browser-native dictation remain available.

Active staff consumes seats; owners and disabled staff do not. Both saved branch
records and core location/service-area records consume location slots, including
inactive locations. Checks run under the tenant write lock and apply to imports.
Over-limit businesses can still remove records and edit without expanding usage.
Analytics/API service labels do not change existing permission scopes.

## Durable storage and validation

Apply `20261010015021_tiered_subscription_plans.sql` before deploying the new
runtime, followed by `20261011042205_ai_usage_wallet.sql` for prepaid accounting.
All tables use forced tenant RLS in `v7_private` and grant only the
restricted backend role access. Startup checks reject a missing migration.
Backup preparation includes plan state, immutable choices, counters, wallet
balances, financial entries, checkout snapshots and reservations.

Target checks: subscription and tiered billing tests, resource/usage cap tests,
PostgreSQL plan runtime tests, public SEO tests, and frontend check/build.
