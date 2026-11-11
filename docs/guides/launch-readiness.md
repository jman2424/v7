# Customer launch readiness

## Business onboarding

1. Create the business workspace, verify the owner's email and complete account
   security setup. Use the assigned company key; do not share operator access.
2. Choose Starter, Business or Scale in Subscription. Review the monthly and
   separate one-time setup prices before paying. Only confirmed Stripe payments
   activate a managed company.
3. Add current products or services, prices, FAQs, policies, contact paths,
   opening hours and the intended response style. Save changes before testing.
4. Select an available model and review its token prices. Buy separate prepaid
   AI credit if paid AI is needed. Lower token costs can stretch credit further;
   there is no guaranteed or fixed message count per top-up.
5. Configure the website widget, approve the intended website origin, copy the
   embed code and test it on desktop and mobile. Check a known fact, an unknown
   question, a follow-up and a handoff to the business.
6. For WhatsApp, open the connection panel in Subscription. An eligible number,
   provider approval and protected credentials are required. Meta/provider
   invoices and number costs are separate from V7 and AI credit.

Low-credit and paused-AI alerts appear in the signed-in console. Owners can view
balances, token charges and history; the platform operator can review companies.
There is no automatic recharge. Email alerts are not promised by this guide.
Saved-knowledge replies can remain available when paid AI is paused.

## Operator setup before taking real AI credit payments

- Connect the existing live Stripe account. Set `STRIPE_API_KEY` and the matching
  live `STRIPE_WEBHOOK_SECRET` in Render's protected environment settings.
- Configure the existing `/billing/stripe/webhook` destination for subscription,
  invoice, credit checkout, refund and dispute events. A browser return page
  must never grant credit. Use signed-event verification and canonical payment
  checks, then verify delivery in Stripe.
- Vertex Seven currently reports no VAT registration. Leave
  `V7_VAT_REGISTERED=false`; no Stripe tax rate is needed. Do not enable VAT
  solely to make checkout work. Registration changes affect new prices and
  do not rewrite existing invoices or immutable payment snapshots.
- Fund the central OpenAI account separately when enabling paid AI. Stripe
  top-ups do not automatically buy OpenAI credits. Verify model access and
  confirmed usage before offering funded AI service.
- Connect only verified tenant senders for WhatsApp. With no business number,
  production WhatsApp remains pending. A provider's test sender is not a
  customer-ready number.

## Acceptance checks

Check owner registration and verification, account security, subscription and
setup activation, model confirmation, credit checkout and signed fulfillment,
duplicate-event handling, refund/dispute holds, tenant isolation, insufficient
credit and usage history. Browser checks must also cover English, Spanish,
French, Arabic and mobile layout. Automated mocks validate payment logic but
do not prove that live Stripe or Meta credentials work. An actual paid transaction
or live WhatsApp message test requires the configured provider and user action.
