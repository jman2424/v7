# Private business subscription discount

The Subscription page has an optional code-entry form. The actual redemption code
is not advertised, bundled in the frontend, returned by APIs or written to audit
logs. The server stores a SHA-256 verifier and saves the approved campaign against
the authorized tenant in `billing_discounts`.

The saved campaign discounts:

- Platform subscription: 50% on new checkouts and all renewals, using a Stripe
  coupon with `duration=forever`. At current prices: GBP 200 + GBP 40 VAT monthly.
- Implementation: 50% on its separate one-time checkout. At current prices:
  GBP 100 + GBP 20 VAT. Implementation does not become a recurring charge.

WhatsApp and API usage remain full price. One entry covers both eligible charges,
regardless of which is purchased first. Re-subscribing for the same business also
uses the saved campaign. Entered code text is never needed for renewals.

`POST /billing/discount` requires the existing owner/platform permissions, tenant
authorization and CSRF protection. For an existing platform subscription, it
applies the coupon without proration before saving the campaign. Future invoices
receive the discount; existing invoices are not refunded or rewritten. The
campaign replaces any existing subscription discount; discounts are not stacked.

New checkout sessions inherit the saved discount. When the application encounters
an open checkout with different discount metadata, it expires and replaces it.
Already-open external checkout tabs should be closed and restarted from V7 after
redemption. Stripe remains authoritative for invoice totals and tax.

The coupon is created server-side through the configured Stripe integration on
first discounted checkout/redemption for an existing subscription; no manual
coupon setup is needed. Coupon percentage, duration and validity are checked
before checkout. Existing idempotency keys prevent duplicate submissions.

Stripe credentials and webhook setup are still required. Local tests mock Stripe;
no live subscription or payment was modified during implementation.

For a future Supabase import, apply the additive
`202609220001_billing_discounts.sql` migration after the base migration. The
updated importer preserves discount records and enforces schema version 2.

Checks: `pytest tests/test_subscriptions.py tests/test_supabase_preparation.py -o addopts='' -q`.
Reference: [Stripe coupon duration](https://docs.stripe.com/api/coupons/create).
