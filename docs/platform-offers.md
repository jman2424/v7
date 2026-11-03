# Platform offer controls

In the Vertex Seven business workspace, open **My Business → Offers** with a
platform operator account. **Vertex Seven subscription offers** shows SETUP,
MHIGHSTREET and the referral programme, including their confirmed active/paused
status. Each switch saves immediately. Refresh status after an interrupted save.

SETUP waives unpaid one-time setup. MHIGHSTREET also discounts the first
subscription month by 50%. Normal subsequent subscription prices, AI funding,
provider charges, approval requirements and offer stacking restrictions remain
unchanged. Pausing stops new claims. Accepted discounts, pending checkout terms
and earned referral rewards retain their saved terms.

The former page only edited `offers.json`, the business catalogue promotions.
Billing promotions and referrals were separate systems. Catalogue offers still
use the existing API and editor, below the platform controls; customer businesses
cannot see or change the platform controls.

## Implementation and access

- `service/platform_promotions.py` stores two validated boolean switches in the
  configured platform marketing tenant's `platform_promotions.json` document.
  Missing documents preserve existing enabled offers; malformed/unreadable
  configured policy fails closed. No schema migration is required.
- Operator-only `/admin/api/platform-promotions` uses existing tenant access,
  offers permissions, CSRF, revision checks, document locks and audit logging.
  The file is not exposed through generic raw-file editing or public knowledge.
- Referrals use the existing programme API and database safeguards, with an
  explicit `offers.write` requirement. This does not create a new reward system.
- Checkout checks the current switch before accepting a new code. Accepted code
  claims remain idempotent. Only request-local policy reads are cached.
- Public setup promotion visibility and marketing-agent knowledge use the same
  authoritative status. Stale named-code FAQ/website excerpts are withheld when
  a code is paused, and outgoing paused-code claims are corrected. Normal model
  reasoning stays first; the existing no-provider fallback now includes actual
  platform billing offers rather than an empty catalogue response.

## Verification

Synthetic regression coverage includes strict booleans, malformed policy,
authentication, owner denial, cross-tenant denial, CSRF, stale revisions, new-claim
rejection, re-enabling, accepted checkout preservation, public promotion visibility,
stale FAQ chat responses and request-local cache freshness. A native PostgreSQL
test checks document isolation and policy refresh between background jobs.

Frontend tests exercise revision/CSRF payloads, concurrent click prevention,
read-only access, failed/ambiguous saves, tenant disposal and referral controls.
Local browser verification exercises actual SETUP/referral switches and mobile
layout using synthetic data with external providers disabled. No production offer
was toggled as part of this verification.
