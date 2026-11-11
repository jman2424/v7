# Business response evaluation

On 14 October 2026, eight small live planning requests used fictional business
data with the existing OpenAI key and `gpt-4o-mini`. No customer records were sent.
These are planning smoke checks, not end-to-end customer response evaluations.

The initial custom-website quote produced a clarification paired with
`DO_NOTHING`. The planner now converts that combination to `ASK_SLOT` so the
runtime can execute it. Instructions also prioritise a named offering's pricing
policy, preserve the customer's language for clarifications, and put complaints
and human assistance ahead of selling.

After the instruction change, named quote and retail price cases returned
`PRICE_CHECK`; English and French team requests returned `HUMAN_HANDOFF`; a
cross-tenant/key disclosure injection returned `DO_NOTHING`. Model output still
passes through runtime validation, tenant-scoped retrieval and prepaid billing.

Regression checks:

- `pytest tests/test_business_conversation_policy.py tests/test_generic_business_responses.py tests/test_business_playbook.py` — 84 passed.
- `pytest tests/test_prepaid_ai_usage.py -k 'tenant or frozen'` — 3 passed.

This does not fine-tune the underlying model or prove every industry, language,
action integration or live deployment configuration. Repeat evaluations when
models or business knowledge change; verify important answers against supplied
facts and retain a working human handoff.
