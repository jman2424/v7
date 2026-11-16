# Incident response runbook

For a suspected breach, abuse of an assistant, leaked credentials or a provider
compromise. Work through the steps in order and write down the time of each one.
Every console action below is audited with its reason.

## 1. Contain (minutes)

1. **Stop the AI where it is affected.** Console → Operations → Service controls →
   *Platform kill switch*. Choose the narrowest scope that covers the problem:
   one channel of one business, one business, one channel everywhere, or the
   whole platform. Customers get the business's contact notice; no data is
   deleted. It takes effect within about 5 seconds on every server.
2. **Sign people out.** Same screen → *Emergency sign-out*, for one business or
   every business account. This ends sign-in sessions, remembered devices and MCP
   connections. Platform administrators stay signed in. Passwords and
   authenticators are unchanged.
3. **If a platform administrator account may be compromised,** rotate
   `SECRET_KEY` (signs everyone out, including administrators) and the
   administrator's password and authenticator (`ADMIN_PASSWORD_HASH`,
   `ADMIN_TOTP_SECRET`), then redeploy.

## 2. Rotate what may have leaked

Rotate at the provider first, then update the environment and redeploy. Only
rotate what the incident touches.

| Secret | Where to rotate |
|---|---|
| `OPENAI_API_KEY` | OpenAI dashboard → API keys |
| `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET` | Stripe → Developers → API keys / Webhooks |
| `TWILIO_AUTH_TOKEN`, `TWILIO_API_KEY`, `TWILIO_API_SECRET` | Twilio console → API keys & tokens |
| `WHATSAPP_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | Meta for Developers → the WhatsApp app |
| `SMTP_PASSWORD` | Your email provider |
| `V7_POSTGRES_DSN` password | Supabase → Database settings |

Keep the old values out of chat, tickets and screenshots.

## 3. Investigate

- Audit log: kill switch, sign-out, permission and settings changes, with who,
  when and the written reason.
- Business operations and error logs in the console (Health, Errors).
- Provider dashboards (Stripe events, Twilio and Meta logs, OpenAI usage) for
  activity you do not recognise.
- Note which businesses, customers and data types were affected and for how long.

## 4. Recover in stages

1. Fix the cause and confirm the rotated secrets work (send a test chat message
   to an internal business first).
2. Restore one business or channel at a time from the kill switch list
   (*Restore*), watching errors and usage after each.
3. Tell affected business owners what happened, what was done, and what they
   should do (for example, sign in again or review recent conversations).

## 5. Notify

If personal data was affected, decide within 72 hours of becoming aware whether
the UK ICO must be notified, and whether affected people must be told without
undue delay. Record the decision and the reasons either way. Businesses whose
customers were affected need the facts promptly so they can meet their own
obligations.

## 6. Afterwards

Write a short review: timeline, cause, impact, what worked, and follow-up work.
Lift any remaining suspensions only when the cause is fixed.
