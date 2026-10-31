# Business applications: implementation and rollout

## Architecture and invariants

Email verification creates the existing account and workspace; it is not commercial
approval. Staff join requests keep their existing, separate owner-review workflow.
New businesses submit one tenant-bound application, initially PENDING_REVIEW. Only
an authenticated, MFA-established platform operator can decide it. Customer JSON,
AI research and website text cannot set commercial eligibility.

Use the existing management sessions, Stripe checkout, price catalogue, invoice
verification, prepaid wallet, SMTP/Resend transport and console. Do not introduce
another account or billing system. Preserve existing paid/complimentary customers,
internal workspaces, renewals and balances. Material changes reopen review and
block new purchases without automatically cancelling existing services.

Persist checkout authorizations before creating Stripe sessions. Bind them to the
tenant, billing reference and application revision. Unresolved authorizations block
material edits/revocation until the canonical Stripe session is safely expired or
settled. Network uncertainty must fail closed, not silently revoke permission while
an applicant can still pay an open checkout. Existing Stripe reference validation,
idempotency, webhook signature checks and payment proof remain mandatory.

Store private reviewer notes/research separately from the public response fields.
Decisions, changes and notification outbox records commit together. Retry delivery
with stable event identifiers; no sensitive mail payloads in logs. Research is
optional, bounded, public-source-only and advisory; failure never decides status.

## Incremental work

1. Private application/settings/history/payment-authorization/outbox schema and
   SQLite equivalent; controlled transitions, optimistic concurrency, retention.
2. Short verified signup, signed-in applicant status/update/reconsideration, AUP.
3. Platform-only mobile-friendly review/search/settings and durable notifications.
4. Gate all first-purchase and activation paths; preserve established services.
5. Bounded optional research with source evidence and no decision capabilities.
6. Synthetic integration/security tests, PostgreSQL RLS tests and frontend checks.

## Before production rollout

The activity-based AUP and rejection/reconsideration procedure are **drafts for UK
legal review before deployment**. This engineering work is not legal clearance.
Review the final policy, customer terms, privacy retention and existing contractual
obligations. Do not infer protected characteristics or religious identity. Mixed
activities require individual human review; business eligibility is distinct from
the existing per-agent action grants and permissions.

Keep application intake disabled until the platform owner has configured and
reviewed the policy and notification recipient. Apply the reviewed migration before
deploying application code. Snapshot/back up first. Do not automatically cancel
existing subscriptions or retroactively revoke prepaid credit. Audit unmanaged
legacy workspaces and external Stripe Payment Links: disable unscoped external
payment links in Stripe; they cannot be secured by hiding a website button.

No production schema change, live research charge, real notification test or rollout
has been performed as part of preparing this document.

## Configuration and operation

- `/console/applications` is platform-only. Configure the activity policy, legal
  review acknowledgement, owner notification email and intake switch there.
- `/console/application` is the signed-in applicant status/correction page.
  Pricing links retain the chosen server-owned plan and open the short application.
- `V7_APPLICATION_WORKER=true` runs the durable notification/research/retention
  loop in the existing service. It defaults to `V7_CHANNEL_WORKER` when unset;
  no additional Render service is required. Multiple processes claim work with
  leases/row locks. All provider calls run outside state-change transactions.
- Reuse the existing `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`,
  optional `SMTP_REPLY_TO` and TLS configuration. No key is exposed in the console.
  Resend retries reuse one persistent event key. SMTP is at-least-once delivery;
  a crash after SMTP acceptance can duplicate a notice. Ambiguous mail older than
  23 hours or eight failed attempts is retained for operator review, not blindly
  retried beyond Resend's idempotency window. No customer support auto-send mode
  or inbox deletion preference is changed by application notifications.
- Research defaults off. It uses the existing platform-internal accounted model,
  never the unapproved applicant's wallet. It reviews at most three pages and
  12,000 characters per revision, with a global 20-job daily ceiling. Website
  requests keep DNS pinning, public-address checks, TLS, redirects disabled and
  bounded content/deadlines. The only model output accepted is exact excerpts
  tied to reviewed source indices; no decision/action tools are supplied.
- Five submissions/corrections per verified contact in 24 hours and a 30-second
  per-application correction interval supplement the existing request/signup
  limits. Applicant email addresses come from verified account state, not JSON.
- Material name/website/established-description or playbook activity changes for
  enrolled businesses reopen review through the shared document writers, including
  imports. Initial matching setup, prices, stock and tone do not themselves revoke
  approval. Existing legacy businesses can enter controlled review through their
  application page; they are not automatically migrated into a rejected state.
- PostgreSQL document changes and review reopening share one transaction. In
  development SQLite/file mode, review is invalidated before replacing a material
  document, so a filesystem failure can leave a conservative pending review but
  cannot leave changed business details eligible for payment.
- Terminal, non-paying application data is minimised after 180 days by default
  (configurable 30–730). Existing-service and pending records are not silently
  erased. Minimal decision metadata remains, private notes are redacted and sent
  notification payloads are removed after 30 days. Run the maintenance worker.

## Payment reconciliation and rollout checks

Approval is checked at payment entry, and again when a durable reference permit
is reserved immediately before Stripe session creation. A provider timeout after
reservation deliberately keeps the permit unresolved. Retry the original checkout
with its existing idempotency key to recover its session; do not invent another
reference or clear the permit manually. The application page/review screen can
resolve known unpaid sessions by checking and expiring them through Stripe. A
completed session requires verified webhook reconciliation; an unknown session
requires operator/provider investigation. Failed/unknown responses never activate
a business. Ordinary renewal verification recognises historical paid/complimentary
records and previously authorised references without a new monthly application.

Before rollout, reconcile old unpaid checkouts/Payment Links and inventory existing
paid/complimentary/internal workspaces. Do not classify every missing application
as approval: a new managed business with no application is blocked. Existing
unmanaged legacy workspaces remain available; only trusted migration/onboarding
code may create that legacy state. New tenant creation always reserves a managed
record. Keep the Render auto-deploy setting off until legal/policy review, native
database CI, the migration and owner-notification configuration are complete.
