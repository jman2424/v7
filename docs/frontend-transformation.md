# Frontend transformation implementation record

Request: complete six-workspace redesign, 2 November 2026. Working branch:
`codex/premium-workspaces`, based on production/main `3050809`.

## Boundaries

Keep existing Flask/Svelte architecture, APIs, role/tenant checks, Stripe rules,
balances, manual business approval, channel approvals and action safeguards.
No schema migration, price change, live automatic-charge activation, customer
message, real payment or paid AI test is needed for this frontend work.
Keep changes isolated until workflows and visual verification are complete.
The official SVG logo remains unchanged. No invented metrics or capabilities.

## Route and capability migration map

| New customer workspace | Internal view | Existing functional surface |
|---|---|---|
| Home | Overview | Activation, real enquiries/lead outcomes, funding alerts, relevant setup/tasks |
| My Business | Profile | profile, website knowledge and saved business details |
| My Business | Products & Services | catalog, categories, prices, stock, service configuration |
| My Business | Offers | offers, archive/reuse, eligibility and signup discounts |
| My Business | Questions & Answers | faqs and knowledge review |
| My Business | Locations & Hours | branches, addresses, schedules |
| My Business | Delivery | delivery rules, exceptions, collection |
| My Business | Assistant Rules | agent playbook, tone, approved paths, advanced model/memory controls |
| Sales & Customers | Messages | conversations, leads/questions history, authorised email/call approvals |
| Sales & Customers | Sales | pipeline, lead stages, follow-up and recorded outcomes |
| Sales & Customers | Insights | statistics, product/performance reports, business intelligence |
| Channels | Website | website/test, appearance, installation/implementation, verification |
| Channels | WhatsApp | whatsapp-qr, provider connection, number and costs |
| Channels | Phone | implemented phone settings, readiness, review/automatic modes, activity |
| Channels | Email | inbox setup, approval, retention, readiness and activity |
| Billing | Overview | plan/payment summary and AI balance, direct contextual actions |
| Billing | Subscription | subscription, changes/cancel, setup, discounts, invoices |
| Billing | AI Budget | budget, funds, optional recharge, alerts and history |
| Billing | AI Spending | understandable usage history and published service rates |
| Settings | Connected Apps | integrations; general channel setup moves to Channels |
| Settings | Team & Permissions | team, existing join/invitation requests, staff grants |
| Settings | Account & Security | account, email/password, MFA, sessions, linked accounts |
| Settings | Privacy & Data | privacy, retention, export/deletion capabilities |
| Settings | Cookies | existing cookie preference dialog |
| Settings | Advanced | authorised diagnostics and developer-facing controls |
| Platform administration | Dedicated navigation | platform, applications, companies, provider-funding, errors, internal usage |
| Application journey | Contextual task | application, eligibility status, approval before purchase |

Legacy URLs retain tenant, plan and relevant view parameters through canonical
mapping. The effective leaf permission is still checked server-side. A customer
cannot obtain platform access by changing workspace/view query parameters.

## Observed problems and implementation decisions

- The shared `Console.svelte` owns most forms and 28 unrelated navigation links.
  Introduce one explicit workspace/view registry and a six-link customer shell;
  retain shared draft lifetime and existing mutation guards.
- Platform operations and customer setup currently share the same sidebar.
  Add an explicit, role-checked workspace switcher and separate platform nav.
- Catalog exposes references/tags/stock fields equally for every business.
  Use searchable editors, progressive disclosure and service-aware stock controls.
- Conversations is a chronological log rather than an inbox. Build searchable,
  channel-filtered message/thread reading with genuine available metadata.
  Do not invent unread/assignment capabilities if no backend exists.
- Website settings duplicate implementation and installation code in Integrations.
  Provide one website workflow and keep platform-specific instructions in it.
- Subscription embeds funding controls while budget is also a separate page.
  Make Billing a joined flow with one funding form and concise overview summaries.
- Phone/email settings and activity are bundled with unrelated global rules.
  Make per-channel views while retaining consent and review actions unchanged.
- Authentication shows disabled Microsoft/Google options. Remove Microsoft from
  normal login/registration presentation without deleting accounts/endpoints.
  Verify recovery for linked-only accounts and report any missing Google setup.
- Public pages use a separate, inconsistent visual layer. Share brand tokens,
  refine their layouts/copy and retain canonical metadata, schema, links and consent.

## Delivery checkpoints

- [x] Read complete brief and inspect route/permission/resource-loading architecture.
- [x] Create isolated branch and route-to-workspace functional map.
- [x] Capture workspace desktop/mobile baseline; record missing public/auth baseline; complete screen inventory.
- [x] Build reusable visual tokens, workspace shell, compact mobile navigation and route compatibility.
- [x] Implement real Home and consolidate customer workflows, preserving drafts/actions.
- [x] Refine editors, inbox, sales/insights, channels and billing; record browser/automated evidence by screen.
- [x] Separate platform tools and review administration, security/privacy and account screens.
- [x] Refine public site/authentication; preserve application/onboarding gates and explicitly pending providers.
- [x] Add navigation/permission/workflow regressions and run frontend/backend/security checks; final head CI pending below.
- [x] Verify Chromium desktop/mobile/tablet/RTL, keyboard and four industries; inspect reduced-motion CSS and document external/device limitations.
- [ ] Produce measured before/after route/task/visual/verification report; release only validated work.

## Verification policy

Use synthetic accounts/data for writes and payment/provider responses. Browser
verification must exercise actual controls, save/cancel/error recovery and narrow
permissions; rendering alone is not completion. Check 390px and 768px layouts,
desktop, keyboard navigation and RTL. Distinguish Chromium viewport checks from
actual Android/Safari device testing. Record unsupported external capabilities
honestly; never advertise a connected Google/phone/email provider without evidence.

## Implemented workflows and evidence so far

- One shared route registry drives the six-workspace Svelte shell and the Flask
  legacy-route redirects. Canonical views retain leaf permissions, tenant checks,
  sign-in hints and the scoped website microphone policy. Platform routes also
  have a separate workspace-level gate, including client-side navigation.
- Home uses actual activation, enquiries, lead outcomes and authorised AI balance
  reads. Empty and unavailable states are explicit; no unread/assignment badges
  or successful business actions are invented.
- Products/services use searchable, collapsible categories and offering cards.
  References, topics and optional inventory remain available as advanced inputs.
  Offers select genuine offering names while retaining unknown legacy references.
  FAQ search keeps original indices and disclosures reduce long editor pages.
  Profile groups contact and business information; optional social links and
  certifications are disclosed. Location keys/map coordinates are advanced.
- Business editors retain in-memory drafts between views. Save responses cannot
  discard newer edits. A shared draft coordinator protects tenant changes and
  departures, including email drafts, channel settings, privacy and AI controls.
  Read-only permissions also disable the relevant edit controls.
- Conversations use real session identity, represented by a secret-keyed,
  tenant/channel-scoped opaque reference. Raw session identifiers are never
  returned. Missing historical identities remain separate records. Search is
  explicitly limited to loaded history; channel filtering and pagination remain.
  Approvals stay distinct from message history and preserve consent/version checks.
- Website combines appearance, testing, origin management, builder instructions
  (including Lovable), installation code and launch checks. The guide reuses saved
  widget data. Connected Apps retains its integration capabilities without a
  duplicate widget install editor. WhatsApp configuration is in Channels, with
  separate provider-billing explanation and a direct link from Subscription.
- Email/phone have focused, truthful Connect/Configure/Test/Activate/Monitor
  paths, connection prerequisites and existing controls. Tests/calls are not
  silently sent, and configured routing is not claimed as delivery verification.
- Billing separates overview, subscription, budget and spending. One funding form
  remains; spending is read-only history. The optional initial budget selection
  still works before activation. Payment/consent/idempotency logic is retained.
- Heavy screen components load on demand. The main route chunk moved from
  1,168.56 kB (311.43 kB gzip) to approximately 197 kB (53 kB gzip); shared assets
  and other screens are additional. This is a build comparison, not a production
  page-load or customer-usability measurement.
- Public templates share the new brand layer, compact native mobile menu and
  keyboard support. Long policy pages gain an on-page contents list without
  changing legal copy. Official SVG assets, SEO metadata and price calculations
  are retained. New homepage content is translated into Spanish, French and
  Arabic, with English source text and existing consent-controlled preferences.
- Normal sign-in offers Google/password/MFA/recovery and removes the Microsoft
  button. Existing linked users/endpoints remain. The owner explicitly chose to
  leave Google awaiting configuration; no working Google connection is claimed.

### Checks completed (2 November 2026; final release review still pending)

- Svelte check: zero errors and zero warnings. Frontend tests: 133 passed (including numeric privacy retention, conflict recovery, read-only/pending-save and delete/add-reference regression checks).
- Focused Python route/conversation/recovery checks: 110 passed. Public/SEO checks:
  121 passed. Console request/loading/search execution harness: 27 passed.
- Ruff across the repository and `git diff --check`: passed.
- Chrome: profile draft survives moving to Products & Services and back; Keep
  editing preserves it; save succeeds and clears its dirty state. Offering search
  works with actual synthetic catalogue data. Mobile navigation/More and the
  public menu/language selector were checked at 390px, including Arabic RTL with
  no horizontal overflow. French and Spanish new homepage copy were also checked.
- Full GitHub CI at `6355316`: **4,133 passed, 92 skipped**, no failures, in
  613 seconds. Skips remain environment-specific; they are not claimed as tested.
  The earlier local auth harness failures were fixed; its focused 73 cases pass.
  The restricted environment socket-pair limitation did not require weakening tests.
- Native PostgreSQL: this machine's installation is missing `share/postgres.bki`,
  so a fresh local cluster could not initialise. A real native conversation/RLS
  test is added to the existing verified-TLS PostgreSQL CI job. That workflow
  passed, including 252 runtime checks and 34 migration/RLS checks. SQLite is
  not presented as PostgreSQL verification.
- No redesign deployment, production data writes, migration, paid model request,
  customer email, phone call or payment has been performed.


### Additional browser findings and corrections

- Fixed numeric privacy retention failing before fetch (Svelte number inputs
  return a number, while the old save path called `.trim()`). Browser retry saved
  30 days, updated the policy state and retained the value after reload.
- Escape now closes the mobile More menu even before the native details toggle
  binding updates. The closed state was verified in Chrome.
- Removed the duplicate WhatsApp walkthrough from Connected Apps; the complete
  provider/number/QR workflow remains under Channels → WhatsApp.
- Corrected the Subscription AI Budget link when its embedded budget form is
  intentionally omitted. Initial funding still anchors to its existing form.
- Installation links now use canonical, tenant-preserving destinations. Its
  combined workflow uses consecutive step numbers; Lovable guidance and copying
  actual installation code were exercised.
- Reused existing mutation locks, and disabled business-editor save controls
  while saving or when read-only. Archived offers display selected offering names.
- Static console build files were unnecessarily `no-store`; only successful files
  in the compiled immutable asset directory now receive private immutable browser
  caching. HTML, API data, missing assets and errors remain `no-store`. General,
  login, chat, analytics and mutation rate limits are unchanged.

### Synthetic browser workflow record

| Surface | Actual interaction and result |
|---|---|
| Profile | Edited, moved to catalogue/back, kept draft, cancelled discard, saved successfully |
| Products/services | Searched chicken and inspected correct offering cards/advanced inventory |
| Offers | Created scoped offer, searched/selected real offering, saved, archived and saved |
| Answers | Filtered Sunday question, changed its answer, saved correct original FAQ index |
| Locations | Changed one branch Sunday hours to Closed, saved successfully |
| Delivery | Updated customer notes, saved while retaining areas/exceptions |
| Assistant rules | Advanced controls initially absent; opened, loaded memory and saved 14 recent messages |
| Website | Changed assistant name, saved appearance; opened Test and Install; chose Lovable; copied real code |
| Messages | Two genuine synthetic threads; selected delivery thread contained its correct two messages |
| Sales | Changed one lead to Won; server-refreshed totals changed; customer search worked |
| Insights | Actual lead outcomes and common-question report opened, without invented revenue |
| Billing | Read actual synthetic complimentary Scale/balance/history; saved £5 low-balance alert; no charge |
| Subscription | Complimentary cancellation state and empty invoice history truthful; no duplicate Add funds |
| Connected Apps | MCP/API setup and revocation controls retained; duplicate WhatsApp removed |
| Team/security | Owner/join controls, MFA/add-phone, linked providers and device states inspected; no credentials changed |
| Privacy | Navigation cancellation preserved draft; repaired numeric retention saved and survived reload |
| Cookies | Opened preferences, selected Essential only, dialog closed |
| Advanced | Actual health/data checks reported 9 passed, 1 unconfigured; no external health claim |
| Email | Saved synthetic support address; correctly stayed awaiting verification/routing and not active |
| Phone | Inspected provider/AI disclosure, disabled activation and retention; changed language in synthetic config |

Browser interactions use loopback-only fixtures. They establish control behaviour,
not real provider connectivity, payment delivery, customer usability feedback or
production load times. Security-sensitive credential enrolment, actual payments,
external sends/calls and provider OAuth are verified by automated contracts where
available, not performed against real accounts here.


### Final review additions

- The complete per-screen capability/verification inventory is in
  [frontend-screen-audit.md](frontend-screen-audit.md). It distinguishes browser
  writes, inspected states and automated contracts rather than claiming every
  provider action was live-tested.
- Short desktop administration keeps the account controls visible while its
  longer navigation scrolls. Sign out completed successfully from desktop and
  mobile after this correction.
- Provider metadata no longer shares cancellable tenant-read controllers. The
  new race regression proves a workspace refresh cannot remove Google's pending
  status. The browser now shows Google disabled with Awaiting setup and no
  Microsoft normal sign-in button. Linked-provider management remains intact.
- Detailing, translation and professional-service fixtures were inspected in
  addition to retail. Detailing saved a filtered vehicle-service price; service
  units and optional inventory stayed intact. A hybrid remote/location service
  no longer implies a delivery section in primary business tabs.
- Final focused auth harness: 47 passed. Route/conversation checks after type
  annotations: 99 passed, 1 native-only check skipped locally (native CI covers
  that path). New presentation services pass strict mypy; broad Flask file checks
  still expose missing-annotation debt and are not reported as clean.
- After screenshots are saved in the task's `outputs/frontend-redesign` folder:
  workspace desktop/mobile/tablet RTL, authentication desktop/mobile, homepage
  desktop/mobile. The live preview uses only clearly labelled synthetic records.

- New categories and locations now receive unique references; deleting an earlier
  entry then adding another cannot collide with a surviving entry. Existing saved
  references remain unchanged. A regression executes the actual editor functions.
