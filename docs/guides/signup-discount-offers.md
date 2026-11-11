# Optional customer signup discounts

Offers previously supported custom promotions, buy-one-get-one and minimum-spend
deals. A business could describe a signup reward as a custom promotion, but there
was no structured signup-discount option.

## Configure an offer

1. In **Offers**, add an offer and choose **Signup discount** as the deal type.
2. Choose a percentage or fixed GBP saving and enter its value.
3. Fill in **Signup steps and eligibility**: where customers sign up, who qualifies
   and how the reward is redeemed. Set an optional code, dates and eligible
   catalogue references.
4. Turn on **Offer is active** and save when the business is ready to advertise it.

Choosing this type turns the new offer off until explicitly activated. Reusing
an old signup offer also requires activation again. API/MCP offer creation
defaults this type to inactive unless `active: true` is explicitly supplied.
Existing types and existing saved offers retain their behavior.

The assistant reads saved active offers; model retraining is not required. It
preserves the reward, terms, code, dates and eligible items in normal offer
answers and in knowledge supplied for model-based follow-ups. Signup-specific
offer questions select relevant signup promotions instead of unrelated deals.
Expired, future, archived and inactive offers are excluded.

This configures the business's customer promotion, not a V7 subscription discount.
The assistant explains the offer and the business's saved signup process. It
does not create customer accounts, verify signup eligibility, enrol customers
in marketing, generate unique coupons or apply/redeem discounts at checkout.
Those actions require the business's own systems. A customer saying they signed
up does not prove eligibility. No promotion is added to any existing tenant.

## Validation

- 315 unique backend checks passed across offer management, schema validation,
  retrieval, model-input privacy, unsupported-action claims, API/MCP permissions,
  generated API contract, widget runtime and request hardening.
- All 72 frontend checks passed, including save/reload, explicit activation,
  invalid rewards, fixed-amount rewards, reuse and translations in all four locales.
- Svelte/TypeScript: zero errors and warnings. Production frontend build passed.
- Ruff and Git whitespace checks passed.
- An isolated localhost account was tested through sign-in/MFA, creating a disabled
  10% offer, saving/reloading, enabling it, and disabling it again. Its public chat
  suppressed the disabled offer and quoted the enabled reward/code/conditions.

An initial API-contract test found the generated OpenAPI file needed regenerating;
the updated contract and integration checks passed. No production writes, real
customer signups, marketing emails or paid model calls were used in this feature
test. Native PostgreSQL tests and live model evaluations were not rerun for this
change; the shared JSON document schema requires no database migration.
