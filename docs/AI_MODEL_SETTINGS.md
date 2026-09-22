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

The initial allowlist contains GPT-4o Mini and GPT-4o, compatible with the existing
Chat Completions request settings and pricing table. It does not enable an inactive
provider or promise access on every OpenAI account. No keys are changed and no live
provider request is made by the settings flow. Owners should use Test agent afterward.

Warnings explain that wording, accuracy, speed, token usage and API charges can change.
Shown rates are per-million-token USD estimates; they do not promise a per-message
price or alter the platform subscription. Official model rates checked September 22,
2026: [GPT-4o Mini](https://developers.openai.com/api/docs/models/gpt-4o-mini) and
[GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o).

Checks: `pytest tests/test_model_settings.py tests/test_api_usage.py -o addopts='' -q`,
plus `npm --prefix frontend run check` and `npm --prefix frontend run build`.
