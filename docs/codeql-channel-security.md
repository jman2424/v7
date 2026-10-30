# CodeQL business-channel regression verification

Scope: the five findings reported on PR #9, plus three adjacent validation
responses in the admin API. This is not a claim that every historical repository
security alert has been resolved. No deployed endpoint, customer data, mailbox,
production database or paid model was used for these checks.

## Source investigation

GitHub identifies the requested findings as #90–94. Its PR-scoped API marked all
five **fixed**, with no dismissal, before this follow-up began. Source history
confirms the underlying remediation was already made in `969fdf8` and merged in
`cc04e63`. The current PR #10 base for this work was `8c919a9`.

| Alert | Original function | Root cause and existing remediation |
| --- | --- | --- |
| #90, `py/polynomial-redos` | `business_channels.address` | The former email regex combined ambiguous quantified domain-label patterns on user input. The old 254-character guard limited the practical exposure; this review does not claim to have demonstrated a production denial of service. The regex was replaced by bounded character-set and label checks with predictable linear work. |
| #91, `py/stack-trace-exposure` | `api_business_channels_put` | A caught `ValueError` was formatted directly into a response. The fixed response is `invalid_channel_settings` (400). |
| #92, same rule | `api_business_channel_grants_put` | Direct exception formatting trusted lower-level validation internals to remain safe. The fixed response is `invalid_channel_grants` (400). |
| #93, same rule | `api_business_operations_decision` | Direct exception formatting could expose unexpected parser/storage details. State conflicts return the fixed `operation_changed` code (409). |
| #94, same rule | `api_business_operations_action` | The pre-execution exception path returned the underlying message. State conflicts return the fixed `operation_changed` code (409). |

The information-exposure alerts describe unsafe response construction, not proof
that a credential or another tenant's record was actually disclosed. Regression
tests inject invented sensitive exception text to verify the trust boundary.

## Follow-up implementation

- `business_channels.address`: named 254-character bound, checked before counting
  or splitting. ASCII dot-atom local parts, plus addressing, normal DNS labels,
  case normalisation and valid boundary lengths remain supported. No email regex
  or backtracking engine is used. Unsupported quoted/Unicode email addresses
  have not been newly enabled.
- `admin_api_routes._validation_failure`: fixed response codes and metadata-only
  logging. The four reported handlers never return exception messages. Nearby
  website-destination, website-import and sales-action handlers return only
  reviewed literal public messages for backwards compatibility; unexpected
  messages become fixed machine-readable codes. Neither logs nor responses format
  the unexpected exception text, traceback or request payload.
- Decision/action request handlers reject malformed IDs, unsupported JSON fields,
  invalid decision/action names, non-integer/boolean versions and invalid reply
  shapes before mutation. Invalid requests return 400, authorization failures
  retain 403, absent operations retain 404, and stale/conflicting state retains
  409. Existing website-import validation keeps its 422 contract.
- Approval instructions are audited before changing queue state. Failure to
  persist that audit leaves the operation unapproved. Approval version checks,
  immutable envelope fields, queue leases, send idempotency and native action
  consent/permission checks remain intact.
- All existing operator-only grants, tenant resolution, authentication, role
  permissions, CSRF, billing/credit enforcement and provider signatures remain
  enabled. No pricing, provider configuration, schema or feature was changed.

## Automated verification

`tests/test_business_channel_security.py` exercises valid addresses (including
254 characters), repeated `!`, excessive dots, oversized input, malformed domain
labels, controls and Unicode. It checks that oversized strings are rejected
before scanning and runs 3,000 adversarial validations in a credential-free child
with a hard ten-second timeout. No availability test runs against a live service.

API regressions inject invented passwords/tokens/paths/tenant strings into all
four reported handlers and three adjacent handlers, then check both responses
and captured logs. Other cases exercise malformed settings/grants/decisions,
consent, authentication, owner/staff/operator permissions, CSRF, cross-tenant
requests, missing operations, duplicate approvals, exclusive execution leases,
audit failure and normal successful grants/actions. Existing provider, queue,
memory, booking, admin API and email setup tests are also retained.

Run records are reported with actual results in PR #10. Test groups overlap;
their counts must not be added together. Ruff and the configured frontend
Svelte/TypeScript checks are run. The local environment has no CodeQL CLI or
installed mypy module; CodeQL verification uses the unchanged GitHub workflow.
No `nosec`, `noqa`, CodeQL suppression, rule exclusion, alert dismissal or disabled
security workflow is introduced.

The first follow-up CodeQL analysis surfaced historical alert **#66** in the
shared `account_service._EMAIL_RE` validator. Its domain character classes also
consumed the dot separator, allowing ambiguous backtracking on a failing suffix.
The follow-up makes domain labels exclude that separator. Its shared `fullmatch`
API, ASCII/plus-address support and existing long-local-part account policy stay
compatible with registration, password recovery and account-email flows. Empty
domain labels are rejected. No account, credential or permission is migrated.
Additional account-management, signup, reset and email-change regressions cover
this correction; the five requested alerts remain fixed without dismissal.

Local verification for this follow-up: final affected Python suite **176 passed,
2 skipped**; initial overlapping parser/provider/memory suite **167 passed**;
frontend **111 passed**; repository-wide Ruff passed; Svelte/TypeScript reported
**zero errors and zero warnings**. The final suite includes the new audit,
permission and malformed-request cases. Skipped checks are not counted as passes.

This is a source/fixture verification. Live production behavior and unrelated
historical alerts remain outside its scope. Production deployment and database
changes remain disabled under the user's existing instruction.
