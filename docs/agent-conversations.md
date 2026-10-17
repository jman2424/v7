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

Subscription destinations may include a known plan ID for review. Anonymous
sign-in preserves only a valid subscription plan hint; the dashboard can highlight
it without changing the saved plan or starting checkout. The customer still
chooses the plan and approves payment through the normal billing workflow.

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
showing sales suggestions during support. Price and checkout follow-ups preserve
that numbering when discussing just one remembered option; a new recommendation
or comparison establishes a new shortlist. Corrected requirements use exact
current customer excerpts and retire superseded constraints in bounded session
memory. Empty optional updates do not erase verified customer needs.

Saved-knowledge and provider-fallback replies preserve the same verified task
memory. Explicitly abandoning a known option also clears it during fallback;
support cancellation and declining qualification do not discard a shopping
choice. A positive compound choice such as "I'll take the second option; where
can I buy it?" follows the remembered shortlist. Questions about an option and
quantities such as "I'll take two bottles" do not establish an option choice.

Fallback qualification records bounded customer evidence for each configured
question. Unknown answers pause the interview; declined answers stop it without
marking qualification complete. Concrete later answers can resume a paused
interview. Superseded requirements also retire matching qualification evidence,
so an old budget cannot return through a previously completed question. This
remains session memory with the existing lifetime, not durable cross-device
customer identity.

Grounded catalogue facts include bounded public tags, name/value options and
valid stock quantities. Unknown availability is represented explicitly; zero
quantity overrides an old in-stock flag. Product-level quantities and listed
options do not prove that a particular size or variant is available. Arbitrary
nested metadata and private/inactive options are excluded.

The provider returns a strict JSON schema with known source/destination IDs and
nullable optional updates; the server still checks facts and customer choices.
If the model proposes a known option without a verifiable customer choice,
that optional selection is discarded while a fully validated answer and approved
navigation can remain. An explicitly rejected newly proposed option, unknown ID
or conflicting explicit selection still fails validation. Selection metadata never authorizes
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
`service/grounded_statements.py`,
`service/sales_agent.py`, `handlers/handler_v7.py` and
`service/message_handler.py`.

Regression coverage includes retail recommendations, appointments, professional
service quotations, hospitality cancellation, option changes, approved checkout
links, source/tenant isolation, unsupported completed-action claims and the
single-request usage charge. These mocked tests verify routing and validation;
they do not guarantee that every model response will be correct. Small live
scenario checks remain useful when changing business knowledge or model settings.
The optional grounded-answer diagnostics distinguish provider completion from
validation acceptance using safe reason codes, timing and validated source IDs;
they contain no customer messages or generated prose. See the bounded synthetic
[agent benchmark](AGENT_EVALUATION.md) for offline replay and explicit live checks.

Protected policy/process replies now render complete curated source statements
instead of the model's policy prose. The bounded `statement_ids` selection must
belong to this request and cite its sources. Eligible units are complete public
FAQ answers, native business rules, delivery statements and server-owned enabled
form facts. Imported website windows and arbitrary about text cannot establish
policy conditions. Oversized or already truncated FAQ answers are ineligible;
exceptions are never removed to fit the output limit. Missing evidence produces
an explicit unknown response and keeps approved navigation available.

Mixed replies retain server-rendered product facts, units, exact prices, stock
uncertainty and the previous numerical reference order. Opening a form does not
submit it; subsequent confirmation follows the existing submission endpoint and
any applicable published business policy. All rendered text still passes the
money and completed-action checks, and raw links must be approved public HTTPS
destinations. This uses the same single accounted model call.
For a single current, unqualified customer budget, fixed listed prices receive
within/above-budget labels. Qualified, historical, strict or ambiguous budgets,
different currencies and recurring, per-unit, from or quote prices are excluded
from this comparison; the label does not establish an order total.

The protected route uses the customer request, consequential terms in proposed
prose, task metadata and selected curated evidence. It is a conservative routing
boundary, not a universal semantic classifier. Ordinary generated conversation
can still require factual review. Published statements retain their original
language; accurate, localized owner policies improve multilingual replies.

Run:

```powershell
python -m pytest tests/test_grounded_conversation.py tests/test_sales_agent.py tests/test_website_destinations.py
```
