# Setup offers and implementation support

- `SETUP` waives unpaid one-time V7 business/agent setup, on all three plans.
  It leaves monthly subscription prices unchanged.
- `MHIGHSTREET` waives the same setup and discounts only the first subscription
  month's invoice by 50%. Later months retain the normal plan price.
- Enter either code in the authenticated Subscription screen before checkout.
  The public pricing pages promote free setup with `SETUP`; the partner code is
  not advertised in the pricing banner.
- Both offers require business approval and verified Stripe checkout/invoice
  completion. Entering a code does not mark setup paid or activate service.
- No offer applies to AI credit, WhatsApp/provider charges or historical invoices.
  Paid setup is not refunded. Offers are not stacked; existing private recurring
  campaign terms are preserved. An unused SETUP offer can be upgraded to MHIGHSTREET
  before the first subscription. Re-entering a code never resets its usage.

V7 supplies business/agent setup, the embed snippet and implementation support.
The business's team or website developer installs the widget. Website edits,
custom development and third-party integrations are separate work, not included
done-for-you implementation.

The existing tenant-isolated `billing_discounts.campaign` TEXT column stores either
the original legacy campaign string or a JSON promotion record. The JSON record
retains tenant/reference-specific coupon bindings and a first-subscription-started
flag. No schema migration or new service is required. Coupon amounts/durations
are server-owned; zero-cost setup uses a 100% `once` coupon, verified against the
canonical Stripe session and persisted binding. The monthly coupon is 50% `once`,
not `forever`. Checkout remains behind the existing eligibility, CSRF, owner-role,
Stripe-signature, billing-reference, plan and live-mode checks.
