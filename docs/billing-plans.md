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
paid setup. Existing discounts and the configured exclusive 20% VAT rate remain
in use; VAT is shown before payment.

Changing an active subscription or a paid setup plan needs administrator review.
Before changing an unpaid selection, cancel its pending checkout through the
dashboard. Completed payments cannot be cancelled this way. Historical invoice
callbacks remain in the ledger and cannot grant a retired plan's entitlements.

WhatsApp is included in new plans, with a per-company enable/pause control.
Provider configuration and existing recipient/signature/origin checks still
apply. Legacy WhatsApp subscriptions are not silently cancelled or repriced.
The previously approved internal website workspace retains its existing exemption.

## Included usage and alerts

Allowances reset by UTC calendar month. One website conversation is a distinct
signed chat session seen during that month, counted once. Existing counted
sessions can continue when the new-session limit is reached. WhatsApp counts
authenticated inbound customer messages, once per provider message ID. Duplicate
webhook delivery does not consume another allowance.

Paid AI requests reserve a conservative estimated GBP ceiling before calling the
provider, using existing known model rates and a fresh reference exchange rate.
Known provider spend settles the reservation. Missing cost metadata, unavailable
currency conversion or insufficient allowance pauses paid requests; saved
business knowledge remains available. Unknown/crashed calls retain their
reservation. There are no automatic extra charges or new-plan API charge approvals.

Pauses are durable and appear as in-app alerts to owners and platform admins in
Subscription and the company overview. They are not email or push notifications.
Review uncertain calls before restoring paid usage; do not assume unknown spend
is zero or erase accounting reservations to force a request through.

Paid transcription for new plans currently requires server-verified PCM WAV of
up to 60 seconds with the duration-priced `gpt-transcribe` model. Compressed
recordings whose cost cannot be bounded return a send-text fallback. Existing
legacy/internal transcription and browser-native dictation keep their behavior.

Active staff consumes seats; owners and disabled staff do not. Both saved branch
records and core location/service-area records consume location slots, including
inactive locations. Checks run under the tenant write lock and apply to imports.
Over-limit businesses can still remove records and edit without expanding usage.
Analytics/API service labels do not change existing permission scopes.

## Durable storage and validation

Apply `20261010015021_tiered_subscription_plans.sql` before deploying the new
runtime. All five tables use forced tenant RLS in `v7_private` and grant only the
restricted backend role access. Startup checks reject a missing migration.
Backup preparation includes plan state, immutable choices, counters and reservations.

Target checks: subscription and tiered billing tests, resource/usage cap tests,
PostgreSQL plan runtime tests, public SEO tests, and frontend check/build.
