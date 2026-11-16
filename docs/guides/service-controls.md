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

Not built yet: disconnecting a channel's provider connection (removing its
credentials or number) and suspending a group of businesses at once.
