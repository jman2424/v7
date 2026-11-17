# Service controls: pausing AI and the platform kill switch

`service/service_controls.py` decides, on the server, whether customers of a
business get AI replies on a channel (`web`, `whatsapp`, `email`, `phone`).
Billing activation is separate and unchanged: a paused business can still sign
in, manage settings, buy AI credit and use its owner tools.

## Who can do what

- **Business owners** (and staff given **Pause and resume AI**, permission
  `service.pause`) can pause or resume all AI, or one channel, for their own
  business in **Operations → Service controls**. Pausing everything asks for
  confirmation.
- **Platform administrators** (`platform.read` and `business_settings.write`)
  can suspend the whole platform, one channel for every business, one business,
  or one channel of one business. A reason of 5–500 characters is required and
  stored with the suspension. A business cannot lift a platform suspension.

Every change is audited (`business.ai_paused`, `business.ai_resumed`,
`platform.service_suspended`, `platform.service_restored`).

## What customers see

While paused or suspended, the website widget script is empty (the widget
disappears), direct chat returns the contact notice, WhatsApp senders get the
notice at most once a day, callers hear it and the call ends, and the email and
phone workers do not answer. The notice is the same as for an unpaid business:
"This assistant is currently unavailable. Please contact {business} by email at
{address}." No data is deleted.

The owner's own MCP connection ignores a business pause (it is a management
tool) but stops under any platform suspension of that business.

## Behaviour

- Controls live in the platform-level `service_controls` table, one row per
  active pause; resuming deletes the row.
- Each server re-reads them at least every 5 seconds, and a change applies at
  once on the server that made it.
- If the controls cannot be read, AI is treated as paused (the kill switch never
  fails open). Before the migration is applied nothing can be paused and the
  screen says so.

Apply `supabase/migrations/20261115120000_service_controls.sql` before relying
on these controls in production.

Platform administrators can also sign out one business, or every business
account, from the same screen (*Emergency sign-out*): sessions, remembered
devices and MCP connections end; platform administrators are never signed out
this way. See the [incident response runbook](../operations/incident-response.md).

## Customer message limits

`service/customer_message_limits.py` caps how many messages one customer can
send per day (UTC) by website chat and by WhatsApp. Each business sets the
two limits separately with a slider (5–200) or chooses **Unlimited**, under
**Channels → Website → Website installation** and **Channels → WhatsApp**.
Changing them needs `business_settings.write`; every change is audited
(`business.message_limit_changed`). With no saved choice the limit is 40.

- A website visitor is counted by chat and by internet connection. Restarting
  the chat does not reset the count; one connection (an office, a mobile
  network) may send up to five customers' worth.
- A WhatsApp customer is counted by phone number.
- The check runs before any AI or plan allowance is used. Over the limit, the
  website shows "You've reached today's message limit for this chat. Please try
  again tomorrow." with the business's contact email; a WhatsApp customer is
  told once a day and later messages get no reply.
- Counts store only keyed digests, never raw addresses or phone numbers, and
  are deleted after two days. If the counts cannot be read, messages are
  allowed (this is a cost control, unlike the kill switch).

Apply `supabase/migrations/20261117090000_customer_message_limits.sql` before
relying on limits in production; until then the default of 40 is not enforced
on PostgreSQL and the screen says the setting is unavailable when saving.

Not built yet: disconnecting a channel's provider connection (removing its
credentials or number) and suspending a group of businesses at once.
