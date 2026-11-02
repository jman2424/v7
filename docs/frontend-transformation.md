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
- [ ] Capture baseline desktop/mobile/auth/public screenshots and full component inventory.
- [x] Build reusable visual tokens, workspace shell, compact mobile navigation and route compatibility.
- [x] Implement real Home and consolidate customer workflows, preserving drafts/actions.
- [ ] Refine each editor, inbox, sales/insights, channel and billing interaction.
- [ ] Separate platform tools and refine administration, security/privacy and account screens.
- [ ] Refine public site, authentication, application and onboarding.
- [ ] Add navigation/permission/workflow tests; run existing frontend/backend/security checks.
- [ ] Verify desktop/mobile/RTL, keyboard/reduced-motion, realistic industry flows and real production limitations.
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

- Svelte check: zero errors and zero warnings. Frontend tests: 129 passed.
- Focused Python route/conversation/recovery checks: 110 passed. Public/SEO checks:
  121 passed. Console request/loading/search execution harness: 27 passed.
- Ruff across the repository and `git diff --check`: passed.
- Chrome: profile draft survives moving to Products & Services and back; Keep
  editing preserves it; save succeeds and clears its dirty state. Offering search
  works with actual synthetic catalogue data. Mobile navigation/More and the
  public menu/language selector were checked at 390px, including Arabic RTL with
  no horizontal overflow. French and Spanish new homepage copy were also checked.
- Full Python regression run is in progress in the normal local environment.
  The restricted sandbox hangs in an existing socket-pair watchdog test, so that
  test has not been weakened or skipped to bypass the environment limitation.
- Native PostgreSQL: this machine's installation is missing `share/postgres.bki`,
  so a fresh local cluster could not initialise. A real native conversation/RLS
  test is added to the existing verified-TLS PostgreSQL CI job. Its result is
  pending; SQLite checks are not presented as PostgreSQL verification.
- No redesign deployment, production data writes, migration, paid model request,
  customer email, phone call or payment has been performed.
