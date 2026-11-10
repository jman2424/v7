# Shared business intelligence, channel-specific delivery

Every channel continues to use the tenant's configured model, current business
knowledge, bounded conversation context, grounded answer checks and usage-credit
enforcement. Channel guidance changes presentation and follow-up style; it grants
no new tools or access to private accounts.

| Channel | Delivery workflow |
| --- | --- |
| Website widget | Guided exploration, comparisons and approved navigation buttons |
| Email | Complete support enquiries in plain-text paragraphs, with necessary terms, approved links and review-first drafts |
| Phone | Natural spoken answers, one focused question at a time, complete material terms and honest team-message handoff |
| WhatsApp | Short mobile paragraphs, remembered choices and approved tappable page links |

## Defects corrected

The sales policy intentionally strips its internal grounding marker before
returning public agent metadata. Email and phone previously checked that stripped
field, so a genuinely validated model answer could be withheld as unverified.
The shared message handler now supplies a separate internal delivery signal only
when V7 validated the answer and its final text still matches the expected safe
formatting. The worker requires this signal. Raw agent flags, customer metadata,
remembered state, route names and saved-knowledge fallbacks cannot certify an
answer. Consequential intents and all existing approval gates still apply.

Email and phone also rejected every inline URL, including an exact approved URL
rendered from a complete saved policy or FAQ. Validated answers now reuse the
widget's approved-link canonicalizer. Email restores the current approved URL
as a labelled link; phone uses the page label in speech. Unknown, disabled or
mixed unapproved links still block delivery, as do all links in unvalidated
answers. No model URL becomes an approved destination through this repair.

WhatsApp sends a message body rather than a widget action tray. Valid navigation
IDs could therefore disappear at delivery. Its finalization now resolves those
IDs against the current tenant's enabled public destinations and appends at most
three links in selection order. Unknown/disabled IDs are ignored; model-written
URLs are never adopted as approved destinations. Existing URLs are not duplicated.
Links are appended only when the body plus the mandatory AI notice fits Twilio's
[1,600-character messaging limit](https://www.twilio.com/docs/api/errors/21617).
Verified answers are never truncated to fit a link. Already oversized answers
are left unchanged; this change does not introduce multi-message sends.

Delivery profiles are fixed server-owned guidance in the shared system prompt,
including correction attempts. They do not add a model call or select a different
model. Prices, policies, qualifications, source validation and action permissions
remain shared with the widget.

## Verification and limits

Synthetic provider tests run through the actual shared handler, sales policy,
memory, validation, worker and phone poll response. They cover the same model and
business evidence across all four channels, follow-up context, real routine-email
approval, spoken phone output, WhatsApp navigation, unsupported prices, modified
answers and forged validation flags. Existing broader regressions cover memory,
business-specific sales flows, permissions, tenant isolation and accounting.

Local checks: 190 delivery/channel/security tests passed; 626 reasoning, memory, grounding
and permission tests passed, with one environment-specific test skipped. Repository
Ruff, Python compilation and strict typing of the new channel helper passed.
These establish wiring and deterministic safeguards, not a measured improvement
in live model accuracy. No paid model requests, real email sends or calls were run.

Conversation context stays within its existing channel/session boundary. Email
uses the validated enquiry supplied at intake; unrelated emails and identities
are not joined into an inferred customer profile. Review mode remains review
mode. Phone still needs its approved provider/number setup before activation.

## Email replies, phone delivery and campaigns

Inbound email and phone use the same tenant handler as the widget and WhatsApp.
Delivery turns its verified answer into labelled links in email or concise speech
with approved page names on the phone. Email accepts a new question in the subject
and removes quoted replies and hidden HTML from the current enquiry. Automatic
email replies require a provider-authenticated sender domain and an eligible
answer. Connected Inbox replies require review. Changing email to review mode
returns automatically approved drafts to the review queue before submission.

Live calls have a separate processing lane and a 22-second answer window. A late
or unverified answer goes to the team's queue. Callers can press 0 to leave a
message and press 9 to end the call. The phone provider and number must be
configured before a live test.

In **Channels → Email → Email campaigns**, a business owner can draft copy using
the same public business facts and metered model, edit the subject and message,
confirm marketing consent, review the recipient count, and explicitly submit a
broadcast. The provider inserts the unsubscribe link and handles opted-out
contacts. V7 adds the sender's business mailing address and AI-assisted notice.
Submission status means provider acceptance. An uncertain outcome requires
reconciliation before further action.

The operator connects campaigns with the server-only
`V7_EMAIL_CAMPAIGN_ROUTES_JSON` mapping. Each exact tenant key needs its own
`segment_id`, verified `sender`, `business_name`, `mailing_address`, and dedicated
`api_key`. Maintain an opted-in marketing segment in Resend and keep support
enquiries outside that audience. Review expires after 30 minutes and must be
repeated if the sender configuration or audience changes. A segment can contain
up to 100 contacts, and a business can store up to 50 campaigns.
