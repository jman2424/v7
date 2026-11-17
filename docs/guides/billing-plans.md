# V7 plans

`service/plan_catalog.py` is the authoritative GBP catalog, before VAT. Starter
is £99/month, Business £199 and Scale £349, billed monthly. Each plan lists the channels it
includes: Starter website chat, Business adds email, Scale adds WhatsApp and
calls. Optional setup assistance costs £100 once on every plan. Existing Stripe contracts retain their financial terms. A new plan
is selected by an authenticated business owner or platform administrator.

## Billing and activation

Yearly billing is switched off (`YEARLY_OFFERED = False` in `plan_catalog`): new
checkouts and moves to yearly return `yearly_billing_unavailable`, and no screen,
public page or sales answer mentions it. The code below is kept so a subscription
already billed yearly would keep renewing and changing plan; none exist. When it
is switched on, new subscriptions choose **Pay monthly** or **Pay yearly** (ten
months' price, shown as "2 months free"). The yearly checkout
uses the server's yearly price and a yearly Stripe interval, and its reference is
bound to that interval in `billing_interval_choices` (no row means monthly, so
every existing subscription stays monthly). One-off
first-month offers and referral month credits are refused on yearly billing, so
a month-sized percentage can never discount a whole year. The 50% recurring code
applies to either. Allowances and AI credit work the same either way.

The monthly subscription and the optional one-time assistance have separate
Stripe checkouts and invoices.
Checkout amounts come from the server catalog, never a submitted amount. Each
checkout reference is bound to its plan in `billing_plan_choices`. Verified
Stripe reads must match that binding. A return URL never activates access.
Activation requires a paid monthly invoice and an active subscription. One-time
assistance is never required to activate. Existing discounts remain in use. New prices charge no VAT by default
because Vertex Seven is not VAT-registered. Set `V7_VAT_REGISTERED=true` only after
registration is effective, with a verified exclusive 20% Stripe tax rate.
Public and dashboard prices show the final payable total. Discounts apply before
any configured VAT; recorded invoices keep their original financial amounts.

Owners can use **Change plan or cancel** in Billing for eligible active tiered
subscriptions. A move to a higher plan or from monthly to yearly opens a Stripe
confirmation for the exact existing subscription item and server-catalog price;
Stripe shows and invoices the prorated amount immediately. A plan change keeps the
billing date; a move to yearly starts a new yearly period today.

A move to a lower plan or from yearly to monthly is scheduled for the renewal date
with a Stripe subscription schedule (`from_subscription`, two phases, released at
the end; tax rates and discounts carry over). Nothing is charged today and the
current plan stays until renewal. The owner confirms the date in the console and
can choose **Keep my current plan** before then, which releases the schedule. The
change is recorded as a `scheduled` row in `billing_plan_changes` before Stripe is
touched. When Stripe moves the subscription to that price at renewal, a lower or
equal plan applies without payment evidence (entitlements only go down); a higher
plan still needs its paid invoice. A finished V7 schedule is released on the next
billing action. Schedules use `iterations`, as the pinned Stripe-Version
`2025-06-30.basil` requires; newer versions use `duration` instead.

For an immediate change the dashboard changes entitlements only after a fresh
provider read verifies the requested price and its paid invoice against a
tenant-bound, expiring `billing_plan_changes` authorization. The original checkout
binding and any paid assistance remain intact; switching plans does not require
or charge assistance.
An unpaid change cannot replace the last verified active plan.

Cancellation opens Stripe's hosted review and takes effect at the end of the
current paid period. Returning to the dashboard does not itself change access;
verified subscription events update the cancellation status and effective date.
Until that date the owner can choose **Keep my subscription**, which clears the
scheduled cancellation in Stripe; nothing is charged.

When Stripe reports the subscription ended, the end date is recorded in
`business_retention` and the owner sees "Your subscription has ended" with the
date until which their data and AI credit are kept. For 30 days nothing changes
except that the assistants are off; subscribing again removes the record. After
30 days the business appears under **Ended subscriptions → Awaiting your review**
for platform administrators, who can mark it to keep. No business data is ever
deleted automatically, and deletion itself is not automated yet.
This does not cancel separately billed legacy WhatsApp contracts. Legacy plans,
scheduled or pending changes, and unsupported subscription shapes require review.
The Stripe key must permit reading subscriptions/invoices and creating prices,
portal configurations and portal sessions. Portal configurations are isolated to
the requested operation; the browser cannot submit a price or subscription ID.

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
Apply `20261017192010_conversation_memory_and_plan_changes.sql` before deploying
conversation memory and hosted plan-management controls.
Apply `20261115110000_billing_intervals.sql` for yearly billing. Until it is
applied, monthly billing works as before and yearly checkout returns
`yearly_billing_unavailable`.
All tables use forced tenant RLS in `v7_private` and grant only the
restricted backend role access. Startup checks reject a missing migration.
Backup preparation includes plan state, immutable choices, counters, wallet
balances, financial entries, checkout snapshots and reservations.

Target checks: subscription and tiered billing tests, resource/usage cap tests,
PostgreSQL plan runtime tests, public SEO tests, and frontend check/build.
# Complimentary owner access

Platform administrators can grant or revoke complimentary Scale through the
subscription page. This uses a distinct `complimentary_scale` contract and an
audit entry with a reason. It creates no Stripe subscription, payment or invoice,
and refuses to replace an existing Stripe subscription. Revocation returns the
workspace to its underlying subscription state. Tenant isolation and role checks
still apply; complimentary access does not include prepaid AI credit.

Platform administrators can inspect and adjust the internal workspace's credit
ledger. Its existing internal AI exemption remains active, so that ledger balance
is informational rather than a charge for internal AI requests. Provider funding
remains separate. Manual adjustments must include a reason and are not cash
refunds or Stripe payment confirmations.

