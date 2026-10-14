# Business referrals

Owners can share their referral code/link in Account & security or Subscription
→ Refer a business. The homepage advertises the current enabled offer. Shared
links preserve the code through sign-in in session storage; owners explicitly
accept it above the plan/checkout controls before creating checkout.
The default offer is 40% off one subscription month and any unpaid setup fee for
each business. New businesses must accept before their first checkout; the
referrer earns a reward only after V7 retrieves and verifies the referred
business's positive, paid first subscription invoice from Stripe.

The platform administrator can pause new claims in this section. Existing claims
snapshot their percentage and persist, as do earned rewards. Setup fees already
paid are not refunded. Rewards do not stack with the existing campaign discount
or apply to prepaid AI credit or WhatsApp charges. Each renewal reward must be
applied by its owner; it discounts one invoice, without proration. Only one
subscription reward can be reserved/applied at a time.

Storage: service/referrals.py, routes/billing_routes.py and the additive private
Postgres migrations 202610140001_referrals.sql and
202610140002_referral_program_lock.sql. All tenant records use forced RLS;
the only cross-tenant lookup is an exact 128-bit referral code lookup returning
its sponsor and owner hash to the backend. Programme changes require a live
platform session in both HTTP and the guarded database function. Shared links
contain no owner email or business name. Same-owner and duplicate welcome claims
are rejected. Stripe coupons use duration=once and deterministic idempotency keys.

Verified refunds/disputes on the qualifying invoice hold unclaimed sponsor
rewards for review. Already reserved/applied discounts are not clawed back; the
operator should review these in Stripe. Reinstatement requires operator review.
Disabling the programme alone never puts earned rewards under review.

Stripe must be configured with live credentials and a signed webhook receiving
invoice.paid, checkout.session.completed, charge.refunded, refund.created,
refund.updated, charge.dispute.created and charge.dispute.funds_withdrawn.
No real customer payment is made by the automated tests.

Checks: pytest tests/test_referrals.py tests/test_subscriptions.py
tests/test_tiered_subscriptions.py; npm run check; npm run build (frontend).
