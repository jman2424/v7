# Phone and email improvements — 3 November 2026

The existing shared agent, provider connectors, durable queue and permissions are
preserved. This change improves recovery, setup and operator review without
buying a phone number, expanding credentials or enabling automatic replies.

## Findings and changes

- Phone intake ignored Twilio's optional transcription confidence. A bounded,
  finite score below 0.5 now requests one clearer repetition. A second unclear
  transcript is saved for human review without a model call or spoken business
  answer. A clear repeat can continue normally. The retry count is signed and
  bound to the original tenant/call; missing scores remain supported. All five
  configured call locales have a recovery prompt. AI identification still plays
  before input collection, and keypad 0 still takes a team message.
- The email editor did not show the final delivery-owned AI footer. The preview
  now shows the original recipient, actual reply subject and unchanged draft
  spacing with the notice supplied by the backend. It uses escaped text, never
  renders inbound HTML, and cannot change recipients or sender authority.
- Activity had no search or status filters and hid useful failure reasons behind
  generic labels. Search now covers the latest loaded 50 items, with status
  filtering and a pending-review count. Expected validation failures retain only
  predefined safe codes. Unexpected exceptions still expose neither provider
  bodies nor customer content. Uncertain sends remain blocked from auto-retry.
- Setup showed routing and grants but not module policy, business activation or
  privacy confirmation together. Additive configuration checks now expose these
  blockers with worker state. These checks do not claim live delivery, queue
  health, available AI credit or provider funding. The existing activation and
  approval gates remain authoritative.
- Email setup has provider-specific forwarding guidance, copyable verified
  forwarding addresses and a connection refresh. Unsaved address edits no longer
  display the previous mailbox's forwarding target as belonging to the new one.
  Phone setup has a copyable signed-provider webhook destination. No secret is
  included in the copied URLs.
- Both channel screens now bound API waits to 20 seconds. An interrupted write
  tells the operator to refresh and inspect its outcome rather than automatically
  repeating a potentially completed approval or change. Unsaved forms remain.

## Verification

- Focused Python regression suite: 225 passed; four additional clear-repeat and
  signed retry-state cases passed (229 total). Covers authentication, owner and
  operator permissions, cross-tenant access, CSRF, webhook signatures, replay,
  idempotency, consent, approval, uncertain sends, retention and provider failures.
- Frontend: 137 tests passed, including final-body preview, search/status filters,
  bounded waits, no automatic retry, stale responses and scoped request bodies.
- Svelte type checks: zero errors and warnings. Production console build passed.
- Repository Ruff and Python compilation checks passed.
- Strict mypy was run on the four affected Python modules: it reports 32
  missing-annotation errors and four undeclared Flask `container` attributes.
  It is not a clean type-check pass; no typing rule was disabled to hide this debt.
- Synthetic Chrome review checked final email spacing/disclosure, sender search,
  empty filtered results and the phone webhook copy control. No customer email,
  live call or paid model request was used.

## Limits

Twilio does not guarantee a confidence score or its accuracy; it is a recovery
signal, not an authorization check or a measure of answer correctness. Number
provisioning and real carrier/audio checks still require a connected number.
Existing review-first email handling and retention choices are unchanged. Native
Google/Microsoft mailbox OAuth and cross-email identity/thread matching are not
introduced. Production provider delivery was not tested because the user chose
connection without a live test. GitHub CI and CodeQL must pass before release;
local tests alone do not establish a clean remote scan.
