# Agent conversation benchmark

This small benchmark makes changes to the sales agent measurable. Seven fictional
retail/service conversations exercise 20 turns: budget replacement and checkout;
a returns interruption followed by numbered selection; unknown stock and prompt
injection; quote-only pricing and a quote form; refusal/cancellation; and an
unsupported paid booking followed by a callback form.

The fixtures in `evals/scenarios.py` contain public, invented businesses and
`example.com` destinations. No real tenant, customer, CRM record or website is
loaded. Both modes call `service.grounded_conversation.answer`, its current
structured output contract, grounding/state validators and the existing
`tracked_completion` accounting code. This is a component benchmark of the
grounded answer path; it does not exercise HTTP channels, retrieval construction,
the handler's later sales guidance, durable sessions, form submission or a real
purchase funnel.

## Offline verification

From the repository root with the normal project dependencies installed:

```powershell
python -m evals.agent_eval --output output/agent-eval-offline.json
python -m pytest tests/test_agent_eval_harness.py
```

Add `--supervised` to the offline command to exercise the same child-process
transport and wall deadline used live, while still making no API requests.

The default command never reads a key or sends an API request. It replays full
reference model outputs through the real validator, carries the resulting state
and recent history between turns, and checks the same expectations used live.
Reports label this `offline_reference_replay` and usage `synthetic_not_billable`.
A passing offline run proves fixture/harness consistency; **it does not prove the
model can produce those outputs**. Offline tests also verify rejected prices,
request/budget limits, unknown costs and storage isolation.

## Explicit, bounded live run

Use a separately approved evaluation key in an ignored local dotenv file. Do not
paste a key into a command, fixture or report. The runner reads only
`OPENAI_API_KEY` from the explicitly supplied file; it does not import other
dotenv settings. A key already exported in the process environment can be used
by omitting `--env-file`.

```powershell
python -m evals.agent_eval --live --env-file .env.local --model gpt-4.1-mini --output output/agent-eval-live.json
```

To retest one conversation:

```powershell
python -m evals.agent_eval --live --env-file .env.local --scenario retail_support_interruption --output output/agent-eval-support.json
```

Default limits are 20 provider requests, 1024 output tokens per request, a
20-second provider timeout, a 180-second total wall-clock deadline and a USD 0.50
budget. There are 14 planned calls and no judge-model calls or SDK retries.
`--max-requests`, `--max-output-tokens`, `--timeout-seconds`, `--max-seconds` and
`--max-budget-usd` can lower these limits. Hard argument ceilings are 20 requests,
2048 output tokens, 30 seconds per provider request, 600 seconds overall and USD 5.
The live command uses a supervised child process; the parent terminates it if the
overall deadline expires, including a hung network request.
Settings travel through standard input and incremental JSON report snapshots
through standard output; no multiprocessing queue or named IPC is needed. Child
stderr is captured and discarded rather than exposing provider error content.

Before each request, the runner uses the shared conservative
`completion_ceiling` calculation and the repository's immutable pricing snapshot.
If the remaining budget cannot cover that request's ceiling, it stops **before
sending the request**. Known provider usage is priced using the returned model,
not a guessed replacement model. Unknown usage or a provider error stops the run;
the report retains an unknown-cost request and its reserved ceiling rather than
claiming zero cost. A forced deadline can also leave an in-flight request with
unknown cost. This is an application-side spending guard based on the checked-in
rate snapshot, not a provider billing guarantee; confirm rates when updating the
model list.

## Isolation, accounting and reports

The harness refuses to run inside an existing Flask application context. It
creates a temporary directory, redirects tenant documents, security/wallet SQLite
and analytics SQLite there, and forces the SQLite backend even if production
PostgreSQL settings are present. It creates only `EVAL_RETAIL`/`EVAL_SERVICES`
model-setting documents and synthetic prepaid credits. Existing reservation,
settlement and usage-recording code stays enabled. A fixed local FX reference is
used solely for this disposable ledger, so the only possible live network calls
are the explicitly enabled OpenAI model requests. The temporary data is removed
after a normal run; production wallets and CRM are never used. The supervisor's
forced termination can leave a temporary directory for OS/user cleanup.

The optional JSON report records mode, commit, tracked working-tree dirty status,
individual runtime file hashes and their combined hash, fixture/prompt hashes, model,
configured bounds, exact completed/passed counts, checked answers and verified
agent state, validator rejection codes, per-request latency, token usage and
known/unknown cost. It includes no API key, dotenv values or raw provider error
body. The prompts and replies come only from these fictional fixtures. Keep
reports under the ignored `output/` directory. A returned deterministic fallback
or reference answer can never count as a successful live response: a rejected or
missing grounded answer fails that turn and ends its conversation.

For a failed turn, the report also retains a bounded `candidate` from the model's
final JSON answer: at most 4000 answer characters, approved fixture source and
navigation and statement IDs, and allowlisted agent-state fields. This helps
distinguish unsupported answers and unsafe selections from overly strict
validation. Only known statement IDs are retained. It captures no reasoning, response headers,
provider error body or arbitrary extra fields; key-shaped text is redacted. These
synthetic benchmark candidates remain separate from the runtime's text-free
diagnostics. Passing turns do not duplicate their answer in a candidate field.

Exit status is `0` only when all selected conversations pass, `1` for benchmark
failure or an enforced stop, and `2` for a local setup/argument error. A run with
no live calls or incomplete conversations cannot be presented as a live pass.

## Using results

Run an unchanged baseline and candidate with the same model, settings, fixtures
and repeated attempts before accepting a claimed quality improvement. Compare
failure reasons, successful scenario count, response time and cost together.
Retain failures as new fixture cases after removing private data.

The deterministic checks cover supplied facts, state, selection, approved
navigation and form intent. They do not establish full factual entailment of
every sentence, fluency, helpfulness, customer satisfaction or sales conversion.
Known workflow inventions found in manual review have explicit exclusion checks,
including invented return-window start events and stock-confirmation timing.
These are narrow regression checks, not a general entailment validator.
The runtime additionally renders protected policy/process replies from complete
request-local source units. Regressions inject the old unsupported workflow
phrases and assert that the final displayed answer contains the complete valid
policy instead. A repaired displayed answer may pass even when the discarded
model prose was incorrect. Safe diagnostics identify `mode=source_statements`;
the benchmark evaluates the final answer, preserving its existing criteria.
The form exclusion distinguishes a false claim about completing a form from
the true statement that merely opening it submits nothing. Enabled capability
facts are derived from the same channel action allowlist as production.
Review the synthetic live answers against those qualities, then expand with
owner-approved cases and human labels. This six-case benchmark is an initial
regression gate, not a statistically representative evaluation or production SLA.

An offering mentioned to explain why it exceeds a budget may still appear in
`offering_ids`, which describes discussed options rather than a basket or a list
of only recommended purchases. The budget-correction case therefore requires
the affordable option to be present without forbidding an explained alternative.
The returns-policy interruption may use `policy` or the general `answer` intent; it must still
use the assist stage, hide sales suggestions, retain the shortlist and answer the
policy correctly. These checks follow the existing runtime metadata contract.

The SDK timeout/retry behavior follows the [official OpenAI Python library
reference](https://developers.openai.com/api/reference/python); shared V7 API
adaptation and provider storage settings remain in `service/openai_completion.py`.
