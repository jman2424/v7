# Per-business model selection

Business owners and platform operators can change the AI model in **API usage & cost**.
Staff with cost-viewing permissions remain read-only.

The flow is: select model → review → acknowledge costs/responses and confirm →
confirm again and save. Nothing is persisted during the first two steps. The server
requires the two acknowledgements in sequence, bound to the authenticated actor,
tenant, selected model and original file revision. Reviews expire after ten minutes;
stale edits and reused save requests are rejected. CSRF and activation checks remain.

`ai_model.json` stores only the model and a unique change generation inside the tenant's
existing versioned storage. It is deliberately excluded from the raw-file editor's
allowlist, so that editor cannot bypass confirmations. Changes are audited before
writing. Existing environment defaults are retained until a tenant saves a choice.
The Supabase preparation importer already copies tenant JSON; no new table is needed.

The shared completion wrapper resolves the tenant setting on each new provider call,
including planning and reply rewriting, and records the actual requested/returned
models in usage accounting. This works across workers sharing the existing data volume.
Already-running calls are not interrupted. Saved-data replies may use no provider call.

The allowlist includes GPT-4o, GPT-4.1, GPT-5.6, and GPT-6 text models. The
completion wrapper removes temperature for reasoning models, which reject that
setting at their default reasoning effort. It does not enable an inactive
provider or promise access on every OpenAI account. No keys are changed and no live
provider request is made by the settings flow. Owners should use Test AI & widget afterward.

Warnings explain that wording, accuracy, speed, token usage and API charges can change.
The built-in cost estimator has rates for GPT-4o Mini and GPT-4o only. Newer
models remain unpriced in this dashboard: calls and tokens are recorded, but
owners must check provider billing for their actual cost. See the
[OpenAI model catalog](https://developers.openai.com/api/docs/models) for
current model availability and rates.

Checks: `pytest tests/test_model_settings.py tests/test_api_usage.py -o addopts='' -q`,
plus `npm --prefix frontend run check` and `npm --prefix frontend run build`.
