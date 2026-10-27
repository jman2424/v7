# V7 release validation — 27 October 2026

## Changes

- Share completed chat messages, approved buttons and clicked state between open tabs for the same business and website. Keep drafts local, enforce transcript expiry/size limits and merge delayed concurrent replies.
- Read one fresh catalogue snapshot per answer instead of rereading it for each SKU/search/currency operation. The next message loads current data.
- Send exact long policy text once, retain complete evidence on the server, stabilize schema enums, and choose model evidence/state before generating customer prose.
- Preserve a valid informational answer when the model labels its next step as opening a form but requests no form. No form opens; an explicit enabled-form request with a missing action still fails closed.
- Exclude account authority from business snapshots and reject legacy archives/proposed restore changes containing it.
- Serialize subscription refreshes and retrieve canonical provider state under the persistence lock even without plan-change history.
- Canonicalize unambiguous historical MFA tenant aliases during migration and preserve both used-code records and the maximum TOTP replay high-water mark.
- Update SvelteKit to 3.1.0, Svelte to 5.57.2 and supporting static-console tooling. Use Node 22 for the console build.

## Verification

The file-isolated local regression run passed 3,523 tests, with 67 environment-specific skips and zero failures, before the final latency/MFA high-water additions. Final affected verification passed 219 conversation/latency tests, 35 migration/latency tests with two skips, 77 snapshot/billing/widget tests with two skips, 93 frontend tests and four SDK security tests. Counts overlap and must not be summed as a full-suite total. The intermediate combined run had 27 temporary-directory permission failures; rerunning migration tests with a writable workspace TEMP passed. No product guard was weakened for that environment problem.

Svelte check reported zero errors/warnings; the static production build and Ruff passed. npm audit and pip-audit reported no known vulnerabilities in the checked dependencies. Semgrep source triage covered 72 matches, with no new meaningful boundary candidate; 14 parser/timeout errors and a size exclusion remain explicit scanner limits.

## Live synthetic performance evaluation

The user authorized up to GBP 1. Five sequential bounded runs used synthetic businesses and temporary ledgers, with total provider-reported cost **USD 0.04855105**, no unknown-cost requests and no unsettled reservations. No production account's selected model was changed.

| Run | Model | Passed / executed turns | Provider median | Provider p95 | Model-backed turn p95 | Cost USD |
| --- | --- | --- | --- | --- | --- | --- |
| Frozen baseline | gpt-4o-mini | 16 / 19 | 2.734s | 6.016s | 6.221s | 0.009120 |
| Compact context | gpt-4o-mini | 12 / 15 | 2.914s | 5.141s | 8.060s | 0.006663 |
| Evidence-first schema | gpt-4o-mini | 16 / 18 | 2.243s | 4.688s | 5.937s | 0.007430 |
| Model comparison | gpt-4.1-mini | 18 / 19 | 1.609s | 4.453s | 4.837s | 0.013930 |
| Final informational-step fix | gpt-4.1-mini | **20 / 20** | **1.446s** | **3.625s** | **4.046s** | 0.011408 |

The final run passed all seven scenarios: budget correction, comparison/returns/follow-up selection, stock uncertainty and instruction injection, quote-only pricing and enabled form, stop/cancellation, booking limitations/callback, and customer recall/small talk/out-of-scope handling. Fourteen model calls served twenty turns; local small-talk/recall paths needed no provider call. The failed earlier runs are retained in the evaluation record and are not hidden by fallback answers.

These small sequential runs differ in completion, model and cache warmness; they do not establish a controlled percentage speedup or a production end-to-end SLA. Final model-backed turns had 1.511s median and 4.046s p95, including local validation and possible correction, but exclude production database, HTTP and browser overhead. The test fixture averages around 4,700 input tokens per call; recent production calls often used 10,000–17,000. Benchmark results cannot guarantee every customer reply in 3–5 seconds. gpt-4o-mini still failed some live contract checks. Keep monitoring request phase timings and evaluate model choice per business rather than silently changing paid models globally.

## Security audit limits

The full Cloudflare skill's source workflow reviewed 83 coverage units with two clean final critics. Three baseline leads have independent candidate and final record verification, and corresponding source fixes are included. No lead is labelled a confirmed exploit: native PostgreSQL/end-to-end observations, strict sandbox/artifact retention and native Windows validator file-open protections remain unavailable. Structural validator APIs passed. The audit is explicitly partial, with exact needs-validation plans in the external audit report. Ordinary engineering tests are not strict audit exploit evidence.

Native PostgreSQL lifecycle checks run in the existing Business reliability CI workflow. Actual real-browser cross-tab interaction was not successfully exercised locally; automated browser-message/session tests passed. Authentication, tenant isolation, billing signatures, MCP/API authorization and business-action validation remain enforced.
