# WhatsApp setup

Open **WhatsApp** in the console (`/console/whatsapp-qr`) with the intended
company selected. The route is unchanged. Setup is also available in Integrations.
The page guides the owner through provider choice, number preparation, callbacks,
costs and a manual reply test. Refresh inspects server configuration only; it
does not verify provider approval, account credit or message delivery.

## Connect the correct business

Choose Meta Cloud API or Twilio. Provider registration and number verification
happen in that provider's account. V7 does not purchase or register a number.
Use the provider's migration instructions before moving an existing WhatsApp
number; do not delete a working account to follow a generic setup checklist.

For Meta, the recipient assignment is the **Phone Number ID**, not the customer
facing telephone number or WhatsApp Business Account ID. For Twilio, it is the
registered sender telephone number with its country code. The number helper
prepares a value for handoff; it does not prove ownership or save routing.

The operator stores credentials in the deployment's protected environment:

| Provider | Credentials | Per-company recipient assignment |
| --- | --- | --- |
| Meta | `WHATSAPP_APP_SECRET`, `WHATSAPP_TOKEN`, `WHATSAPP_VERIFY_TOKEN` | `WHATSAPP_META_TENANT_MAP_JSON` maps Phone Number IDs to company keys |
| Twilio | `TWILIO_AUTH_TOKEN` | `TWILIO_WHATSAPP_TENANT_MAP_JSON` maps sender numbers to company keys |

Keep existing companies' entries when updating a map. A dedicated empty map
disables routing for that provider; a populated dedicated map takes priority over
legacy/default routing. `WHATSAPP_PROVIDER_MODE` must allow the chosen provider.
Never put credentials in a website, customer chat or copied setup note.

Use the callback URLs shown by V7, derived from the configured HTTPS `BASE_URL`:
incoming messages use `/whatsapp/webhook`; Twilio status callbacks use
`/whatsapp/status` with POST. Meta verifies its webhook with the separately stored
verify token and subscribes to message events. Signature checks remain required.
Status callbacks are acknowledged; they do not create a delivery report in V7.

Twilio offers a test Sandbox and production sender onboarding. Sandbox testers
must join the chosen Sandbox; it is not the business's production number.
Consult the [Sandbox guide](https://www.twilio.com/docs/whatsapp/sandbox) and
[sender registration guide](https://www.twilio.com/docs/whatsapp/self-sign-up).
If onboarding customers into a provider account as an ISV, follow the provider's
Tech Provider requirements; this release does not implement embedded sign-up.

## Understand the bill

Starter, Business and Scale include the agent software but no monthly AI credit.
Owners purchase separate prepaid AI credit in £5, £20 or £50 packs before VAT
(£6, £24 or £60 including 20% VAT, where applicable). The usable GBP balance is
shared across website and WhatsApp; VAT is not added to that balance. WhatsApp
is not limited by a fixed number of incoming messages. These are V7 processing
credits, not Meta/Twilio messaging credits. There is no automatic recharge.
The page uses the shared plan catalogue and recorded usage, rather than separate
pricing constants. Internal and legacy workspaces are labelled separately.

WhatsApp phone numbers are not included. Meta/Twilio messaging charges, number
rental and taxes are separate from V7's
subscription and setup fee. Incoming customer messages and outgoing agent replies
can be different billing units at the provider. The prepaid AI balance covers
AI usage, not the provider's WhatsApp bill. V7 pauses paid AI processing when
the available prepaid credit cannot safely cover a request or its cost is unknown,
and alerts admins in the dashboard. Saved business knowledge remains available;
V7 does not add automatic overage charges. Provider fees can still accrue even
when V7 has paused paid AI processing.

Consult the [Meta rate card](https://business.whatsapp.com/products/platform-pricing)
and [Twilio calculator](https://www.twilio.com/en-us/whatsapp/pricing) for the
account's current country, currency and message-category rates. Reviewed on
10 October 2026: the providers' public pages give conflicting descriptions of
service-message charging. V7 therefore does not promise that provider replies
are free or bake a changing rate into the dashboard.

## Launch check

1. Confirm the business is active, WhatsApp access is enabled, and the saved
   provider and recipient assignment have no blockers.
2. Confirm the provider has approved the number and its account can send replies.
3. From a separate WhatsApp account, send a simple product or opening-hours
   question to the business number. This is a real message and may incur fees.
4. Check the reply, the correct company's Conversations page and Errors & health.
   Check delivery details in the provider's own console.
5. Generate an optional QR code using the actual telephone number. Scan and
   confirm its destination before sharing it. The QR opens a chat; it does not
   pair the number or activate the agent.

V7 currently replies to inbound text and supported audio with text. It does not
provide outbound campaigns, an approved-template editor or generated voice
replies. Voice transcription also needs a configured, funded AI provider and
supported audio; text remains the fallback. Paid voice processing uses the
duration-priced `gpt-transcribe` model. Recordings are limited to 60 seconds.
The Docker image installs Debian's FFmpeg to decode OGG, WebM, MP3 and M4A
into bounded WAV before reserving credit. If decoding is unavailable or cannot
verify the recording safely, V7 requests text instead of making an unbounded
provider call. Decoder input/output use pipes only, with a ten-second timeout.

## Verification

Run `python -m pytest tests/test_whatsapp_configuration.py
tests/test_whatsapp_qr.py tests/test_whatsapp_security.py` and `npm run check` in
`frontend/`. Review tenant filtering, permission-gated billing data, secret
redaction and invalid callback origins before publishing changes.
