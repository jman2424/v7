# Business channels and operator hub delivery

User request: finish the current changes, push them, and implement email/phone
handling plus the connected-workflow/control-hub steps discussed on 30 October.
The user selected **both** review-first and automatic routine-answer modes.

## Delivery boundaries

- Existing current changes: pushed as commit `3ed7d44`, PR #8, then merged to main. 389 affected
  regressions pass. Final live quality scorecard is 12/16, with remaining gaps
  documented. No false claim of complete conversational reliability.
- New development branch: `codex/business-channels-hub`.
- Reuse the existing grounded handler, tenant knowledge, memory, wallet accounting,
  permissions, analytics and native conversion requests. No provider/model migration.
- Website, email and phone get one shared business knowledge source. Ordinary
  questions use the existing accounted completion. No new classifier per turn.
- Both new channels are disabled until a platform operator grants access and the
  business enables/configures its chosen mode. Review-first is the initial mode.
- Unknown email senders/callers are customer input, never authenticated account
  holders. No private order/account access or transaction powers are inferred.
- No number purchases, call forwarding, DNS/MX replacement or customer emails
  without the corresponding concrete live setup/authorisation.

## Implemented, awaiting release verification and live connection

1. Tenant-scoped durable operations queue and activity/approval records, with
   SQLite tests and private PostgreSQL RLS migration. Leases and stable event/send
   IDs prevent duplicate processing. Unknown send outcomes require reconciliation.
2. Channel configuration with operator grants, business modes, limits, readiness
   checks and metadata-only diagnostics. Credentials remain server-side.
3. Signed Resend inbound events enqueue text-only messages; retrieve body through
   the fixed provider API. Strip quoted mail, skip loops/attachments and bind
   replies to the actual inbound sender. Review drafts or automatically send
   routine approved-knowledge replies according to business mode.
4. Signed Twilio inbound calls/speech events reuse the same handler. Review mode
   takes a message; automatic mode answers routine questions. Call-scoped memory,
   short responses and durable polling avoid duplicate paid turns/timeouts.
5. Owner business hub for modes, pending drafts/actions, approvals/rejections,
   failures and confirmed outcomes. Keep existing permission boundaries. Native
   booking/quote/callback requests remain subject to their existing configuration
   and confirmation rules; external booking systems need a real connection.
6. Synthetic success, tenant isolation, replay, provider failure, disabled-mode,
   credit exhaustion, malicious-input and UI tests, then push the new changes.

## Live prerequisites found

- Existing Resend domain is verified and sending is enabled. Receiving is
  disabled; no Resend webhooks are registered. Existing mail routing must be
  inspected before enabling receiving; do not replace MX records blindly.
- A business phone number/provider has not yet been supplied.
- Previous GBP 2 benchmark cap remains cumulative; do not reset the ledger.
  Current conservative total after the current-change release check:
  USD 1.58590107 including historical unknown holds; no active reservations.

## Modes and action boundaries

- Owners can select review-first or automatic separately for each channel.
  Review email generates a draft, which consumes AI credit even if it is never
  sent. Review phone takes a message without invoking the text model.
- Automatic delivery requires a validated grounded response. Existing harmless
  salutations and scope boundaries also remain usable; no new canned business
  answers were added. Extractive fallbacks, prices/policies without validated
  grounding, unsupported actions, attachments and failures require review.
- Automatic email additionally requires the receiving provider's DMARC pass.
  Forged `Authentication-Results` or `Reply-To` headers grant nothing. DMARC
  authenticates a domain, not an account holder or a right to private records.
- The hub can use the **existing** enabled native quote, callback and
  consultation tools after an owner reviews the details and explicitly confirms
  customer consent. Requests stay `requested`; only a successfully reserved
  configured V7 slot becomes `confirmed`. This does not book on a client's
  separate website, issue refunds or create arbitrary MCP/third-party powers.
- Actions and email approval are version-bound. Native actions use a stable
  server-generated idempotency key. Interrupted sends/actions become uncertain
  and cannot be automatically retried. Marking a call handled cannot make an
  unverified draft audible to the caller.

## Provider setup runbook

1. Apply `20261030070724_business_channel_operations.sql` using the existing
   migration owner after disposable PostgreSQL CI succeeds. Runtime credentials
   remain a restricted `v7_backend` login; never use an owner/service-role key in
   the web app. The table is private, has forced tenant RLS and no Data API grants.
2. Keep `V7_CHANNEL_WORKER=false` during setup. Configure only server-side values:
   `V7_CHANNEL_RESEND_API_KEY`, `V7_EMAIL_WEBHOOK_SECRET`, `V7_EMAIL_ROUTES_JSON`,
   `V7_PHONE_ACCOUNT_SID`, `V7_PHONE_AUTH_TOKEN`, `V7_PHONE_ROUTES_JSON`.
   Email route keys are exact recipient addresses; phone route keys are E.164
   numbers. Values are exact existing tenant keys. No fallback tenant is used.
3. Standard Resend receiving uses a signed `email.received` webhook at
   `https://<V7 origin>/channels/email/webhook`. Inspect IONOS/Resend mailbox
   forwarding before changing receiving/MX records. This implementation does not
   silently convert the separate Resend Inbox product's events into standard
   receiving events. Confirm the actual delivery product before activation.
4. Twilio inbound voice uses POST `https://<V7 origin>/channels/phone/incoming`.
   V7 signs continuation tokens and validates the provider signature against the
   configured `BASE_URL`, account, number and call ID. No outbound calls or audio
   recordings are created. Number rental, calls, provider speech and email fees
   are separate from V7 AI credit. No numbers or provider plans are purchased.
5. Enable the worker only after a verified route exists. It starts after process
   fork on the first request/Render health check and uses durable leases across
   instances. A bad tenant cannot stop other tenants; polling rotates fairly.
6. In the business hub, the operator grants channels; the owner confirms their
   privacy notice, enables a channel and starts in review mode. Run an explicitly
   authorised real delivery/call test before switching any business to automatic.
   Configuration indicators alone are not evidence of successful delivery.

The current phone adapter is turn-based speech recognition and TTS, not a
full-duplex voice agent. It waits at most 20 poll cycles, then saves follow-up
work and invalidates pending generation. There is no measured voice-latency SLA.
Phone memory is scoped to one call. Each email starts a new conversation; neither
sender address, subject nor forged References is used to join private history.
Secure email-thread continuity is a separate enhancement, not silently enabled.

## Retention, diagnostics and recovery

- Hub message bodies/drafts/envelope content expire at the owner's 1–90 day
  setting while the worker runs. Only hashed event keys and content-free
  tombstones remain for up to 90 days, preventing delayed webhook retries from
  resending after short content retention. Active processing is not purged.
- Shared conversation history, existing native action records, audit records and
  provider-side mail/transcripts have their existing separate retention. The hub
  setting does not claim to delete those. Handle data-subject requests across
  all applicable stores; do not export private records through anonymous calls.
- If the worker is disabled, run `python -m service.channel_worker --purge-only`
  in the configured server environment for retention. `--once` runs a bounded
  queue pass instead. Neither command is a substitute for worker monitoring.
- Request/model stages reuse existing metadata-only diagnostics. Queue errors
  store safe codes, never provider exception bodies, credentials or message text
  in logs. Owners see tenant-scoped source text and drafts in the hub.
- Check provider acceptance references before resolving uncertain sends. An
  accepted email is not a delivery receipt; a prepared spoken reply is not proof
  the caller heard it. Existing action tools remain the source of booking truth.

## Verification

- Affected backend regression run: **304 passed, 9 skipped** locally. The skips
  require native PostgreSQL or other environment-specific setup, not a claim of
  having executed those checks. Further final guards receive a focused rerun.
- Existing frontend suite: **102 passed**. Five new hub tests cover stale reads,
  departing tenants, CSRF/version-bound approvals, duplicate actions and safe
  failure messages. Svelte checks/builds passed during development.
- Final focused backend rerun: **70 passed, 3 skipped**. Full frontend rerun:
  **107 passed**. These runs overlap the earlier groups; counts are not additive.
- A real Chrome session against an isolated localhost fixture saved independent
  channel modes and completed a quote-request workflow through the existing
  action tool. No live client account, provider delivery or paid AI was used.
- Signed provider intake, hostile email headers/HTML, duplicate delivery,
  automatic/review routing, disabled channels/actions, consent and native action
  outcomes are exercised with fake providers. No real customer email, phone
  call, charge or additional paid model benchmark has been performed.

This record distinguishes implementation and synthetic verification from
deployment, provider connection and real delivery verification.
