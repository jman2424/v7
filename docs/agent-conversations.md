# Grounded agent conversations

The funded V7 reply combines answering and choosing the next useful customer
step in one accounted provider request. It uses the current business's public
catalogue, policies, FAQs, website knowledge, playbook and approved destinations.
It does not execute a payment, booking or account change by generating text.
Those actions continue through the existing authenticated website/forms.

Business owners tailor the agent using their business model, customer goal,
response guidance and optional qualification questions in the playbook. Keep
prices, cancellation terms, availability and other business facts in the relevant
catalogue/policy/knowledge settings. Add approved website destinations for product,
checkout, booking, quote and support pages. The agent selects their IDs; the
server supplies the configured URLs.

Embedded action links open approved destinations in a separate tab. The script
and generated iframe snippet allow popups to leave the frame sandbox, so checkout
and sign-in pages can work normally. The widget remains sandboxed and cannot
navigate the containing page. Links retain HTTPS validation and
`rel="noopener noreferrer"`.

Within the existing tenant-scoped session lifetime, the agent remembers a short
list of offerings, the selected offering and up to six stated customer
requirements. Requirements must quote the customer's messages or previous
verified session requirements. Contact details, credentials, unrecognised source
IDs and model-created executable actions are excluded from this task memory.
Numerical option selection follows the previous shortlist's order. Current
authoritative platform promotions and selected offerings receive priority when
background knowledge exceeds the bounded provider context.

Current questions also rank matching product, service, FAQ and policy records
ahead of imported website background. Native offerings and rules are ranked
before their preview limits, so a relevant service beyond the first 50 records
can still be found. Old assistant replies do not dominate a new policy lookup.

Explicitly abandoning an option clears the selection. A separate three-item
shortlist survives support interruptions for later numbered references, without
showing sales suggestions during support. Corrected requirements use exact
current customer excerpts and retire superseded constraints in bounded session
memory. Empty optional updates do not erase verified customer needs.

The provider returns a strict JSON schema with known source/destination IDs and
nullable optional updates; the server still checks facts and customer choices.
If the model proposes a known option without a verifiable customer choice,
that optional selection is discarded while a fully validated answer and approved
navigation can remain. An explicitly rejected option, unknown ID or conflicting
explicit selection still fails validation. Selection metadata never authorizes
a payment or other transaction.
Monetary validation handles prefix/suffix currencies and localized GBP/USD/EUR
formats. Explicit customer budgets may be restated only as labelled budgets;
they cannot establish an offering price, tax, discount or checkout total.

When enabled by the owner, web chat can choose an existing consultation, quote
or callback request form from natural language in the same accounted answer.
Only the channel's enabled capabilities are exposed. Forms are rechecked by the
handler and prioritized within the public three-action limit. Opening a form
does not submit it: consent, tenant/origin checks, validation and idempotency
remain in the existing submission endpoint. Cancellation/policy replies do not
open sales forms. Declined or informational requests do not trigger shortcuts.

Support questions, complaints and cancellations do not restart a sales interview.
The sales policy preserves a validated grounded next step instead of replacing it
with a generic purchase or qualification question. When credit or the provider is
unavailable, the existing saved-knowledge fallback remains available; it does not
attempt further chargeable planning for that turn.

Relevant implementation: `service/grounded_conversation.py`,
`service/sales_agent.py`, `handlers/handler_v7.py` and
`service/message_handler.py`.

Regression coverage includes retail recommendations, appointments, professional
service quotations, hospitality cancellation, option changes, approved checkout
links, source/tenant isolation, unsupported completed-action claims and the
single-request usage charge. These mocked tests verify routing and validation;
they do not guarantee that every model response will be correct. Small live
scenario checks remain useful when changing business knowledge or model settings.

Run:

```powershell
python -m pytest tests/test_grounded_conversation.py tests/test_sales_agent.py tests/test_website_destinations.py
```
