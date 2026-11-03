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

WhatsApp sends a message body rather than a widget action tray. Valid navigation
IDs could therefore disappear at delivery. Its finalization now resolves those
IDs against the current tenant's enabled public destinations and appends at most
three links in selection order. Unknown/disabled IDs are ignored; model-written
URLs are never adopted as approved destinations. Existing URLs are not duplicated.

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

Local checks: 89 delivery/channel tests passed; 626 reasoning, memory, grounding
and permission tests passed, with one environment-specific test skipped. Repository
Ruff, Python compilation and strict typing of the new channel helper passed.
These establish wiring and deterministic safeguards, not a measured improvement
in live model accuracy. No paid model requests, real email sends or calls were run.

Conversation context stays within its existing channel/session boundary. Email
uses the validated enquiry supplied at intake; unrelated emails and identities
are not joined into an inferred customer profile. Review mode remains review
mode. Phone still needs its approved provider/number setup before activation.
