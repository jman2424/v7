# Client readiness review — 21 October 2026

## Scope and release status

Reviewed the existing V7 implementation used by production, not a replacement
system. Production was confirmed live at `bcc6174beae123db1346f3b66b0212b398edb512`.
The local starting point, `8b90fb2`, also includes the isolated test-sandbox
launcher and the unpublished development-workflow documentation. This review is
on `codex/client-readiness`; its changes have not been pushed or deployed.

## Findings and fixes

1. **Frontend tests were omitted from CI.** The console compiled successfully
   while its standalone localization test failed. Added `npm test` and included
   it in the existing CI console checks.
2. **Billing translations were incomplete.** Updated the changed pricing sentence
   and added missing cancellation, plan-change and daily tester-limit messages
   in English, Spanish, French and Arabic. This preserves the existing billing
   behavior and makes those controls understandable in every supported locale.
3. **An installed transitive dependency had a published security advisory.**
   The local environment contained `certifi 2026.7.22`, affected by
   `PYSEC-2026-4320` / `GHSA-6q48-6c7w-9gw2`. Added an explicit
   `certifi==2026.10.19` runtime pin and installed the patch locally. The
   subsequent installed-package audit reported no known vulnerabilities.
   This does not establish which certifi version is inside the running image.
   Sources: https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2
   and https://pypi.org/project/certifi/2026.10.19/.
4. **Greetings recited operator planning text.** The live greeting inserted
   `business_focus` after “I can help with”, producing “I can help with Help
   businesses…” and doubled punctuation. Greetings now introduce the named
   assistant and ask the configured opening question. Saved business context
   remains available to the planner, discovery, recommendations and handoff.
   Added a regression proving that greetings do not call the model or recite
   long planning descriptions.

## Verification performed

| Check | Result |
| --- | --- |
| Backend tests, combined by unique test identity | 2,914 passed; 67 skipped; zero unresolved failures |
| Conversation checks after the greeting change | 152 passed |
| Frontend standalone tests | 62 passed |
| Widget SDK security tests | 4 passed |
| Svelte/TypeScript check | Zero errors and zero warnings |
| Production frontend build | Passed |
| Ruff on all tracked Python files | Passed |
| Frontend npm dependency audit | Zero vulnerabilities reported |
| Python installed-package audit after patch | No known vulnerabilities reported |
| HTTPS request using the patched certificate bundle | HTTP 200 |
| Git whitespace/diff checks | Passed |

Backend tests were run in isolated batches. The restricted Windows execution
token denied hard-link/junction creation in five filesystem tests. A focused
rerun with normal filesystem permissions passed 40 tests, with one skip; the
aggregate above replaces the five initial environmental failures with those
successful reruns. The batch stopped at four such failures was resumed for its
remaining files. The final greeting changes were verified with the focused
152-test conversation run rather than another full-suite rerun.

The 67 skips comprise 63 checks requiring a disposable PostgreSQL database,
two unavailable symlink-permission checks, one case-sensitive filesystem check
and one check requiring the trusted Docker FFmpeg runtime. Those checks were
not newly verified in this environment. No production database was used for
testing. Docker-image building and the Docker-based secret scanner were not
run locally. The installed-package audit is not an audit of the deployed image.

## Live website checks

`/health`, `/`, `/auth/session`, `/sitemap.xml` and `/robots.txt` returned 200.
A single six-turn public conversation returned 200 on every turn:

- Greeting.
- “How'd your day go”.
- “Green means good”.
- What the business sells.
- Recall of “green means good” after the intervening business question.
- Starter versus Business, with accurate catalogue prices and a navigation action.

Observed chat response times ranged from 3.72 to 13.49 seconds; none timed out.
Production diagnostics showed near-instant dispatch for small talk and memory
recall, with additional storage/CRM work around it. The business-knowledge answer
had about 1.19 seconds of retrieval and 9.74 seconds total dispatch. These are
measurements from a small warm-service sample, not a load-test guarantee. No
production error-level application entries were returned by the query for
21 October up to the review time. The live checks preceded the local greeting
fix, which is not yet on production.

## Billing evidence and limits

The earlier separate Stripe test environment verified a declined card, paid
subscription plus separate setup fee, activation only after both payments,
scheduled cancellation, webhook delivery and duplicate-event protection. Those
are previous results, not newly repeated production-payment tests in this review.

An additional real test-portal plan-change attempt could not proceed: the
disposable sandbox no longer had the previous billing contract and correctly
returned `subscription_required`. This remains an unverified external plan-change
path, even though its automated tests ran. The test subscription's scheduled
cancellation was restored. No real customer payments, refunds or cancellations
were performed.

## Before the first client

The automated checks support a controlled first-client pilot after release;
they do not prove every external integration works with a new client's setup.
Release these reviewed changes before relying on the local fixes. Run the native
database/runtime CI checks on that release, and complete a fresh isolated Stripe
plan-change test. Production remains on Render's free instance, so cold starts
remain a reliability limitation; the warm checks above do not test a wake-up.
The console also retains a roughly 906 kB minified initial JavaScript chunk.

For the client's tenant, verify their real catalogue/FAQs/policies, approved
website origin, owner/staff permissions, AI-credit setup, embed and only the
business actions/integrations they will actually use. Have the client approve
the resulting business answers and handoff path before public launch.

## Files changed

- `.github/workflows/ci.yml`
- `frontend/package.json`
- `dashboard/static/i18n/subscription.json`
- `requirements.txt`
- `handlers/handler_v7.py`
- `tests/test_sales_agent.py`
- This report.

Raw test XML, sanitized live checks and dependency-audit JSON are stored in the
ignored local `output/` directory. Credentials remain in ignored private storage.
