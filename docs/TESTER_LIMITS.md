# Free tester allowance

Unpaid authenticated accounts share 10 accepted message attempts each UTC day
across the account tester and the configured `PUBLIC_WIDGET_TENANT` demo.
Anonymous visitors to that demo share 10 attempts per trusted network address.
This means visitors on a shared network may share an allowance. Changing browser,
conversation ID or a caller-supplied identity does not reset it.

The allowance is reserved before agent calls, conversation usage and lead writes.
Accepted attempts count even when the provider fails; malformed messages and
invalid conversation tokens do not. Audio transcription checks for exhaustion
without consuming a second message; its existing separate burst limits remain.

Other tenants' installed customer widgets are outside this tester policy. Existing
subscription, API credit, tenant permissions and burst limits remain in force.

Paid exemptions require a verified, revocable management session and an active
platform subscription with a recorded paid platform invoice for an assigned or
owned business. A public tenant's subscription or caller-supplied plan cannot
exempt an anonymous visitor. Platform operators are exempt for administration.

Storage uses the shared private atomic reservation primitive, with a separate
HMAC namespace and UTC date. This uses the existing auth reservation table without
sharing login keys or altering login rules. SQLite transactions and PostgreSQL
advisory locks serialize reservations across workers. Only keyed hashes, random
reservation IDs and timestamps are stored, never raw addresses or chat content.
Storage/payment entitlement errors fail closed before any model call.

An exhausted allowance returns HTTP 429 with `tester_daily_limit`, `limit`,
`resets_at`, `retry_after` and `Retry-After`. Clients show the daily reset rather
than suggesting a brief wait. Changing the application signing secret invalidates
the current day's buckets along with existing signed sessions.

Blocked requests incur no model/token cost. These limits constrain free demo
spending, while paid customers continue to pay according to their existing AI
credit and model/token usage. The quota lookup itself is a database operation.
