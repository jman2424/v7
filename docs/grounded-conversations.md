# Funded answers and saved-knowledge fallback

V7 attempts one grounded conversation answer before catalogue, FAQ and delivery
shortcuts. Public knowledge comes from the current tenant's profile, catalogue,
FAQs, business core, delivery rules, branches, active offers and imported website.
No business-specific answers or prices are embedded in shared code.

The call uses the selected model and existing `tracked_completion` accounting:
atomic wallet reservation, actual token settlement, tenant isolation and the
existing internal-workspace exemption. Empty credit or unavailable provider
funding returns to the existing automatic responses. Further AI calls are paused
for that request after a failure or rejected answer; a new request may retry.

Context is capped at 32,000 characters. The existing tenant/session memory retains
six bounded conversation messages under its existing TTL, so option numbers and
follow-ups retain context. Private catalogue fields are excluded. Prompts and
answers are not added to the usage ledger. Normal existing conversation retention
still applies.

Generated business answers must cite supplied source IDs. Unknown source IDs,
new monetary amounts/currencies, new URLs and transaction-completion claims are
rejected. These controls reduce unsupported claims; they do not guarantee AI
accuracy. Conversion actions still use the existing authorised workflows.

Regression tests: `pytest tests/test_grounded_conversation.py tests/test_api_usage.py
tests/test_usage_wallet.py`. PostgreSQL-specific cases need the existing database
test environment. V5/V6 response strategies are unchanged.
