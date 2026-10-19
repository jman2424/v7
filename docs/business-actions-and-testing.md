# Business actions and reliability coverage

## Native appointment management

Enable consultation slots in the existing Website widget sales-action settings,
then explicitly enable customer changes/cancellation if it matches your business
policy. The new permission defaults off for existing configurations. Disabling
self-service changes stops further mutations even for an existing receipt.
Only a confirmed appointment against a V7-managed slot receives a private
management link. Customers can view it, select another available slot, or cancel.
This modifies the actual V7 booking record and releases the old slot atomically.
It does not change an external calendar, process a payment or issue a refund.

The confirmation link contains a separately signed, tenant-and-reference-bound
receipt in its URL fragment. The fragment is removed from the address bar before
network requests. The page can copy the original private link on customer action;
it does not put receipts in prompts, analytics, query strings or browser storage.
Links expire 30 days after the booking was created. A receipt remains an authority
to manage that appointment: customers must keep it private.

New public action idempotency fingerprints include the verified conversation ID.
Replaying another chat's form details/key cannot issue its receipt. Existing
unbound requests from older releases cannot gain management authority through a
retry; the business must assist with those bookings. General conversation tokens
are not booking receipts. CSRF, active-tenant checks, approved origins, global
and mutation rate limits apply. No management-account permission is granted.

Changes require explicit confirmation and the currently observed slot ID.
Concurrent reservations use SQLite write transactions or PostgreSQL tenant locks,
plus the existing unique slot constraint. Retrying a successful move or cancellation
does not create another reservation. A cancelled appointment cannot be reactivated
with its receipt. Past appointments cannot be changed. Disabled new booking
availability does not prevent cancellation of an existing confirmed appointment.
Mutation audits omit receipt tokens and contact details. Optional availability or
audit failures do not discard a committed cancellation result.

## External systems

Customer order tracking, external booking updates and refunds are not connected
by this release. Each business must identify and authorize its order/calendar/
payment system and provide a way to verify the customer's ownership. V7 platform
subscription billing is not authority to refund a client business's customer.
Do not present an opened form or an unconnected integration as a completed action.

## Expanded evaluations

The original seven scenarios/20 turns remain the default regression benchmark.
`--extended` adds 60 scenarios/180 turns covering price phrasings, comparison,
contextual capacity questions, inventory uncertainty, approved navigation,
unrelated tasks and customer-defined meanings. Total: 67 scenarios/200 turns.

Offline reference replay runs the real response validator and synthetic ledger;
it is not evidence of model quality. Paid tests retain the existing 20-provider-
request cap per run. `python -m evals.batch_eval --live --env-file .env.local
--model gpt-6-sol --max-total-usd 1.50 --output output/extended-live-UNIQUE`
runs supervised batches under a total cost ceiling and time limit. Every output
records the exact source revision, dirty state, code fingerprint and check results.
Failures and incomplete batches remain failures; there is no retry-until-pass.

The Business reliability workflow adds two disposable PostgreSQL jobs: runtime
and migration tests run on separate empty databases. The runtime uses a restricted
non-owner backend login and verified TLS, preserving production connection rules.
A Windows job exercises junction and filesystem boundaries. Remaining OS/optional
dependency skips must be reported; adding an environment does not turn skips into
passing tests. No production database, booking, email or payment is used by these jobs.
