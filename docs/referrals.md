# Business referrals

Owners can share their referral code/link in Account & security or Subscription
→ Refer a business. The homepage advertises the current enabled offer. Shared
links preserve the code through sign-in in session storage; owners explicitly
accept it above the plan/checkout controls before creating checkout.
The current offer gives a new referred business 40% off its first subscription
month and **zero setup fee** (a once-only 100% setup discount). The referrer earns
40% off one subscription month and any unpaid setup fee. New businesses must
accept before their first checkout; the
referrer earns a reward only after V7 retrieves and verifies the referred
business's positive, paid first subscription invoice from Stripe.

The platform administrator can pause new claims in this section. Existing claims
snapshot both subscription and joining-business setup percentages and persist,
as do earned rewards. Accepted offers before the free-setup change retain their
original percentages. Setup fees already
paid are not refunded. Rewards do not stack with the existing campaign discount
or apply to prepaid AI credit or WhatsApp charges. The joining business's free
setup takes precedence over a weaker 50% setup campaign; its subscription
campaign remains unchanged and unused weaker rewards remain saved. Each renewal reward must be
applied by its owner; it discounts one invoice, without proration. Only one
subscription reward can be reserved/applied at a time.

Storage: service/referrals.py, routes/billing_routes.py and the additive private
Postgres migrations 202610140001_referrals.sql and
202610140002_referral_program_lock.sql and
202610140003_referral_joining_setup_free.sql. The last migration only adds offer
snapshot columns and does not rewrite existing rewards or billing contracts.
All tenant records use forced RLS;
the only cross-tenant lookup is an exact 128-bit referral code lookup returning
its sponsor and owner hash to the backend. Programme changes require a live
platform session in both HTTP and the guarded database function. Shared links
contain no owner email or business name. Same-owner and duplicate welcome claims
are rejected. Stripe coupons use duration=once and deterministic idempotency keys.
Zero-total setup invoices are fulfilled only after canonical Stripe verification.
When a free checkout has no invoice/PaymentIntent, its canonical completed session
must match the current plan, checkout generation, zero GBP total and reserved
100% coupon. The reward keeps Stripe's checkout ID as its proof; V7 creates no
fictional cash payment or invoice and awards no referrer reward for free setup.

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
