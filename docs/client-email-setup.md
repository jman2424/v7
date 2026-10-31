# Client support email setup and retention

Status: implemented on `codex/client-email-setup`, pending release verification.
Production database changes remain declined. Do not provision, enable a worker,
change live mailbox routing or send a setup email under this implementation task.
The existing private operations-table migration is still a prerequisite for live
PostgreSQL operation. This change does not introduce another schema migration.

## What clients configure

Open **Business operations → Set up your company’s support email**. An owner saves
an authorised support address and selects its mailbox provider. This records a
revision-bound setup request, not proof of ownership or mailbox access. A client
cannot choose a tenant, sending identity, webhook secret or provider credential.

The operator separately verifies the sending domain/address, the business's
authority and the exact inbound route. Hosted email, Google Workspace and
Microsoft 365 use verified forwarding into Resend receiving or a configured
Resend Inbox. **Native Google/Microsoft OAuth, IMAP mailbox synchronisation and
deletion from those original mailboxes are not implemented.** Forward the
original message preserving its sender, not a newly composed forward from an
employee; otherwise the employee becomes the reply target. Configure and test
provider forwarding semantics before enabling customer replies.

Operator-only environment configuration (synthetic example):

```json
V7_EMAIL_ROUTES_JSON={"client-inbound@receiving.example":"CLIENT"}
V7_EMAIL_SENDERS_JSON={"client-inbound@receiving.example":"support@client.example"}
```

The sender must actually be verified with the delivery provider. Entering it in
an environment variable does not complete provider verification. If sender
mapping is omitted, existing directly routed addresses remain their own sender.
Invalid maps, conflicting cross-tenant identities and changed sender mappings
fail closed. Replies go to the immutable original sender, ignoring Reply-To and
model-supplied addresses. Signed webhook intake and private tenant queue policies
remain required; see [channel setup](business-channels-delivery.md).

Owners choose **review first** (default) or automatic routine answers, daily
limits, language and content retention. Automatic email still requires grounded
validation, provider-authenticated DMARC pass and an attachment-free message.
The current Resend Inbox API does not supply an authenticated DMARC result, so
Inbox replies remain review-first even when automatic is selected. Unsupported,
important, private-account and transactional requests require review and the
existing verification/permission/consent checks. Sender identity never grants
account access or tool authority. No arbitrary email-driven tools are added.

## Retention and deletion

- Default: remove V7 queue bodies, drafts, envelope addresses, provider identifiers
  and email model memory after the owner's **1–90 day** setting. New email bodies
  are not duplicated into CRM message history. Existing CRM records, customer
  metadata, action requests, security/audit logs and backups have separate
  retention; this setting does not claim to erase them.
- Keep content-free delivery hashes and cleanup outcomes for up to 90 days to
  prevent delayed webhook replay and recognise V7-cleaned threads. No raw thread,
  inbox or customer address remains in expired queue payloads.
- Optional, explicit owner confirmation: move only old, handled conversations in
  an operator-bound **Resend Inbox** to Trash. This is a whole-thread operation,
  including recognised V7 replies. Recent activity, incomplete provider listings,
  unknown/manual mail, pending requests and consequential action records cause a
  skip. No wholesale inbox deletion or model-selected deletion is available.
- The provider is checked before and after Trash. New activity triggers restore;
  signed new inbound events can reopen a thread marked as cleaned by V7. Keep the
  route/worker active during the retention window for that recovery. A failed or
  interrupted cleanup is recorded for operator review and is not blindly retried.
- Resend schedules permanent deletion **30 days after Trash**, unless restored.
  V7 does not call a permanent-delete API. Original Gmail, Microsoft or other
  mailbox copies need their provider's retention rules. See the
  [Resend delete-thread contract](https://resend.com/docs/api-reference/inboxes/delete-thread).

Retention runs on a separate bounded worker loop every five minutes, keeping
provider cleanup off the reply-processing loop. Leases and version checks guard
concurrent decisions and cleanup. Provider failures do not require keeping V7
email content beyond its configured period. Monitor worker health and the hub's
aggregate cleanup outcomes. These are provider acceptance outcomes, not proof
that every backup or original mailbox copy is deleted.

`python -m service.channel_worker --purge-only` performs V7-only retention; it
never modifies a provider mailbox. After removing a route, schedule that command
with `--tenant <existing-key>` for the former tenant until its retained content
and tombstones expire. `--retention-once` additionally allows opted-in provider
cleanup. Do not run either against production without operational authority.

## Costs and release checks

Draft generation uses the same business knowledge, validated handler, model and
prepaid AI credit as website chat, even when the owner never sends the draft.
Email provider delivery/receiving/storage charges are separate. Retention makes
no model calls; provider cleanup uses bounded API reads/updates and may contribute
to provider rate limits or charges. No service, mailbox or number is bought here.

Before activating a business, confirm its verified sender and exact route, approve
its private queue provisioning, establish its privacy/retention instructions and
monitoring, then run a separately authorised delivery check. Current verification
uses invented mail, fake providers and disposable storage only; no live client
email, model credit or real provider deletion is used.
