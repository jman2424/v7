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

Within the existing tenant-scoped session lifetime, the agent remembers a short
list of offerings, the selected offering and up to six stated customer
requirements. Requirements must quote the customer's messages or previous
verified session requirements. Contact details, credentials, unrecognised source
IDs and model-created executable actions are excluded from this task memory.
Numerical option selection follows the previous shortlist's order. Current
authoritative platform promotions and selected offerings receive priority when
background knowledge exceeds the bounded provider context.

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
