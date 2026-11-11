# AI identification and inbound call handling

The delivery layer identifies V7 as an AI service independently of tenant names,
greetings, model instructions and edited drafts. This is a transparency feature,
not a certification of compliance with every jurisdiction's requirements.

- Website chat keeps an AI assistant badge in its header, an AI/error notice by
  the composer, and disclosure metadata in JSON and the final SSE event.
- Console test conversations identify AI replies; appearance previews explicitly
  identify their illustrative conversation.
- WhatsApp replies carry an AI label, including voice-input error responses and
  cached Twilio retries. Existing inbound deduplication and tenant routing remain.
- Email delivery appends a fixed AI-assisted notice after the approved text.
  Operators see this rule in the hub before approving a send. Recipient binding,
  sender verification, approvals and send idempotency are unchanged. Transactional
  sign-in, password and billing templates are not AI-generated and are unaffected.
- Calls play AI and synthetic-voice identification before starting Gather. Fixed
  prompts use the configured English, French, Spanish or German call language.

Calls accept speech or a single DTMF digit. Pressing 0 collects a team message;
it does not dial/transfer to a person or promise a callback. The signed
continuation fixes that turn to review mode, including if an operator later
switches the business to automatic mode. Review messages never invoke the model.
One retry is allowed after silence; repeated silence ends without creating a
fictional enquiry. Automatic calls still speak only validated, completed replies.
Polls bind the job to its stored call and turn; model timeouts keep the existing
bounded team-review fallback. No audio recordings or outbound calls are added.

The Business hub displays the incoming-call webhook and connection steps. A
voice-capable Twilio number, protected provider credentials, exact tenant route,
operator grant, business enablement and privacy confirmation are still required.
No number is purchased and no live phone route is enabled by this code change.

Verification uses synthetic provider signatures, fake delivery and isolated
storage: notice order and languages, silence retries, DTMF review, intake-mode
preservation, conflicting input rejection, call/turn isolation, email envelope
and idempotency, WhatsApp deduplication, custom branding and JSON/SSE disclosure.
Real email and telephone delivery require separately authorised live tests.
