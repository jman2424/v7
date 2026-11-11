# V7 frontend screen audit

Working branch: `codex/premium-workspaces`, PR #16. Synthetic browser checks on
2 November 2026. Production and customer records were not changed.

This is a screen/capability inventory, not a claim that every external provider
or every possible user action was exercised live. Browser saves used isolated
loopback data; automated suites cover authentication, payments, permissions and
operation contracts without taking real payments or contacting customers.

## Shared experience

- Six permission-filtered customer workspaces; separate platform navigation.
- Canonical route registry shared with Flask and old deep links retained.
- Official SVG logo, solid racing green, restrained cards, visible focus,
  responsive header/tabs and bottom navigation. Navigation scrolls on short
  desktop screens while account controls stay visible.
- Search uses authorised destinations, keyboard selection and dismiss controls.
- Business drafts stay in memory between views. Departures/tenant changes use
  coordinated confirmation; newer edits survive an older save response.
- Noncritical screens are imported on demand. Only successful immutable build
  files use private browser caching; HTML and private APIs stay `no-store`.

## Customer screens

| Screen / components | Audit decision and preservation | Verification |
|---|---|---|
| Home / WorkspaceHome, BillingOverview | Real activation, reports, enquiries, setup actions and authorised balance. Loading/unavailable states do not become fabricated zeros. | Desktop/mobile browser, actual synthetic leads/balance; source execution tests |
| Profile / Console | About/contact groups; optional social/certification disclosure; website import instructions retained. | Edit, navigate away/back, Keep editing, save |
| Products & Services / Console | Searchable category disclosures and offering cards. Prices/units/availability primary; references, topics and stock advanced. | Retail search; detailing price save; translation page/hour and professional appointment/session inspection |
| Offers / Console, OfferingPicker | Named offering selection, optional signup discount, dates/types, archive/reuse preserved. | Filter/select real offering, create/save/archive; existing promotion tests |
| Questions & Answers / Console | Searchable editable disclosures retain original indices and tags. | Filter Sunday answer, edit/save; existing knowledge tests |
| Locations & Hours / Console | Name/address/hours primary, key/GPS advanced; supports Closed/by appointment. | One branch hours changed and saved; backend validation tests |
| Delivery / Console | Customer notes, postcode/area rules, collection and exception editors retained. Hidden from irrelevant service navigation; searchable/direct route still accessible when authorised. | Notes saved with existing areas/exceptions retained |
| Assistant Rules / Console | Business model starter and tailored playbook retained. Optional action permissions and technical controls disclosed. | Industry-specific settings read; existing playbook tests |
| Modules / AgentModules | Grant/enable distinction and operator-only grants preserved. Contextual setup destinations corrected. | Owner disabled/uninitialised state and operator controls inspected; grant/consent/permission tests |
| AI parameters / AiParameters | Existing revision validation, preview, save and owner/operator permissions retained in Advanced. | Browser load and type checks; existing parameter tests |
| Memory / MemorySettings | Advanced memory reachable by owner; revision/clear controls retained, read-only fields disabled, draft guard added. | Lazy mount, settings load/save 14 messages; backend memory/RLS tests |
| Knowledge review / KnowledgeReview | Actionable saved-knowledge review retained inside Assistant Rules. | Source/automated endpoint contracts; no paid AI review |
| Messages / Conversations, conversationInbox | Genuine two-pane threads from opaque tenant/channel/session references. Legacy rows not merged; loaded-history search, channels and pagination retained. | Actual synthetic thread selection and mobile back; grouping and native PostgreSQL tenant tests |
| Sales / Console | Latest 50 leads, name/phone/stage search, export and stage changes. Re-fetches authoritative totals after save. | Open→Won refreshed row/totals; customer search |
| Insights / Statistics, StatisticsOverview, PerformanceStatistics | Real report views/filters/charts retained. Links preserve tenant. Common-question report consolidated here. | Actual lead outcomes/common questions inspected; existing report tests |
| Product reporting / ProductStatistics | Interest, recorded sales and optional inventory reporting retained. No automatic stock deduction or verified-revenue claim introduced. | Existing reporting/sales tests; source review; no real transaction |
| Website appearance / WidgetDesigner | All appearance styles/colours/assets retained; preview explicitly illustrative. | Assistant name saved; preview/saved distinction |
| Agent testing / AgentTest | Genuine testing, new-conversation, speech and disclosure controls retained; no synthetic default answer substituted. | Interface/controls inspected; chat pipeline tests; no paid model request |
| Website knowledge / WebsiteKnowledge | Existing reviewed public-site import/revision workflow retained in Test. | Existing import/SSRF tests; no new external import |
| Conversion paths / ConversionSettings | Existing booking/quote/callback/payment paths retained in Website. Permissions and confirmation requirements unchanged. | Existing action/booking/security tests; no external action |
| Installation / Implementation | Appearance/Test/Install joined; origins, builder guide, floating/panel/link code, troubleshooting retained. Lovable added; links preserve tenant. | Selected Lovable, copied actual code; existing embed/origin/SDK tests |
| WhatsApp / WhatsAppConnection, WhatsAppQr | Single provider setup location; subscription/AI/provider costs distinct. Share link is not falsely described as pairing. | Unconfigured state inspected; QR generated locally for reserved test number; no message sent |
| Email / BusinessHub, BusinessEmailSetup | Connect/configure/test/activate/monitor; review/automatic modes, consent, retention and safe cleanup retained. | Synthetic mailbox request saved and stayed awaiting verification/routing; existing provider/operation/security tests |
| Phone / BusinessHub | Explicit number/provider prerequisite, AI disclosure, language/mode/retention and follow-up behaviour retained. | Unconnected/disabled activation inspected; synthetic language preference saved; existing call tests |
| Approvals / BusinessHub | Separate contextual owner task; original version checks, consent, approval and action queue retained. | Owner/operator view inspected; replay/double-execution/cross-tenant automated tests |
| Billing Overview / BillingOverview | Real plan and AI balance summaries with direct actions, no duplicate funding form. | Complimentary Scale and real synthetic balance read |
| Subscription / Subscription, Referrals, ModelPicker | Plan/cancel/change, codes/referrals, invoices and model review retained. Initial funding only before activation. | Complimentary cancellation and empty invoices truthful; existing payment/discount/cancellation tests |
| AI Budget / AIBudget, UsageCredits | Single funding/configuration flow, explicit recharge consent/gates, alerts and history retained. | Saved £5 low-balance alert; existing balance/idempotency/recharge tests; no purchase or recharge activation |
| AI Spending / AIBudget history | Read-only spending/history, no Add funds form. | Synthetic ledger table and absence of duplicate funding verified |
| Connected Apps / ConnectionSettings | MCP/REST OAuth and revocation retained. Duplicate widget and WhatsApp setup removed. | Unconfigured and connected-app empty state inspected; existing OAuth/PKCE/scope tests |
| Team / Console, JoinRequests | Owner/staff boundaries, pending verified join requests and granular cost/subscription access preserved. | Existing owner shown, no pending requests; role/tenant/account tests; no live credential creation |
| Account & Security / AccountSecurity, AuthenticatorManagement, PasswordManagement, EmailManagement | Existing MFA/add-phone, password/email, provider links and trusted devices retained. Sensitive flows not bypassed. | Inspected current states and sign-out; existing MFA/recovery/device/provider tests |
| Privacy / PrivacySettings | Legal identity/contact/retention/export retained; draft state truthful. Numeric retention bug repaired. | Cancel navigation retained draft; 30 days saved and policy updated; conflict/read-only/pending-save tests |
| Cookies / CookiePreferences | Same consent controls, optional preferences/analytics separated. | Opened dialog and chose Essential only; existing analytics-consent tests |
| Advanced / ErrorsHealth | Real errors/fallbacks and business-data checks retained; no invented uptime. | Synthetic stored-data results inspected; diagnostic/security tests |
| Your businesses / Console | Contextual account task with authorised search/switch/create, not a seventh primary workspace. Clear reference label and approval/payment wording. | Search/switch and server permission tests; no real business created |
| Application / BusinessApplication | Contextual Home task; approval before purchase preserved. Closed intake and legal-review hold retained. | Source/automated application/payment-guard tests; local registration prerequisite state inspected |

## Platform administration

| Screen | Audit decision | Verification |
|---|---|---|
| Overview / PlatformOverview | Dedicated platform shell, real directory/activity, search and contextual owner/staff/channel actions. Add-business stays in platform context. | Directory filtered to retail; Channel permissions opened platform/channel-access for PREVIEW |
| Applications / BusinessApplications | Manual eligibility/reconsideration/payment holds and restricted policy settings retained. | Actual empty queue/filter state inspected; existing application tests |
| Businesses / Console | Directory/create and contextual grant entry preserved; no accidental platform privilege for owners. | Authorised four-business directory inspected; customer denial/tenant tampering tests |
| Billing Operations / Subscription | Operator-only billing/customer context retained, customer budget flow not duplicated. | Route/context inspected; existing billing suite; no financial change |
| Provider Funding / ProviderFunding | Separate customer balances, Stripe receipts and provider funding; actual unknown/unconfigured status. | Browser inspected; no provider setup or funding action |
| System Health / ErrorsHealth | Same diagnostics in an operator-only context. | Browser interface/run check inspected; diagnostic tests |
| Usage Audit / ApiUsage | Detailed mode/model/token/cost tools retained exclusively for operators. | Empty synthetic provider usage and saved memory read; API access tests |
| Account security | Personal security retained; no new administrator access granted. | Browser inspected and sign-out completed; existing security tests |
| Channel access / BusinessHub | Operator module and channel grants, customer configuration and approvals preserved. | Contextual route/selected tenant and grant controls inspected; automated enforcement/replay tests |

## Public, authentication and shared surfaces

| Surface | Audit decision | Verification |
|---|---|---|
| Homepage | New business workflow hero and shared brand layer; actual customer widget remains, no fake dashboard. Existing prices/schema/SEO/consent retained. | Desktop/390px; new English/Spanish/French/Arabic copy; real unavailable local widget state |
| Solution/detail/guide/FAQ/about pages / solution template | Shared spacing/type/cards/mobile menu and footer; factual page-specific content and internal links retained. | One actual solution page on mobile; public route/SEO/language suites |
| AI usage pricing | Shared visual layer, original rate/payment calculations and caveats retained. | Public pricing tests; no pricing change |
| Terms/acceptable-use/application policy | Shared legal layout and on-page contents; original legal-review and intake holds retained. | Actual Terms contents/mobile fit; policy tests; not legal approval |
| Platform/client privacy and cookies | Shared legal presentation/contents, genuine configured/draft notices and consent retained. | Privacy/Terms/cookie navigation and fit; existing privacy/consent tests |
| Booking page | Existing focused appointment/receipt/verification actions retained; shared public styling only. | Existing booking lifecycle/verification tests; no booking made |
| Customer widget/chatbot | Tenant-designed component and business behaviour retained. Homepage uses the real installed component. | Appearance/SDK/format/origin/chat regression tests; no paid live conversation |
| MCP consent | Existing OAuth scopes/PKCE/consent flow preserved; shared public typography only. | Existing consent/auth tests; no third-party grant |
| Sign in/MFA | Solid branded two-column desktop and single-column mobile. Password, challenge, remember-device and recovery retained. Microsoft removed from normal buttons; Google explicitly awaiting setup. | Desktop/mobile, Show password, recovery entry, sign-out, Google disabled/Microsoft absent; 47 executed auth scenarios |
| Registration / Registration | Existing separate join/new-account, verified email and MFA flow retained; no bypass of unavailable verified sender or closed application intake. | Local unavailable-sender state; registration/auth/application automated tests |
| Logo/icons/charts/dialogs/search | Official SVG unchanged. Icons remain accessible; real charts retained; native confirmation with safe default/focus, coordinated drafts/search. | Draft cancel/discard/save, search ArrowDown/Enter and mobile Escape exercised |

## Limits and release status

- Latest executable code must pass final GitHub checks before release; the PR is
  isolated from main and no redesign deployment is included in this work.
- Google awaits configuration by the user's explicit choice. Existing password,
  MFA and provider-linked account recovery remain. Google OAuth cannot be claimed
  live-tested without a configured project.
- No real payment, automatic recharge, customer email/call, provider connection,
  external legal approval or paid AI benchmark was performed for this redesign.
- Desktop/mobile checks are Chromium viewport checks, not physical iOS/Android,
  Safari or screen-reader certification. Reduced-motion CSS was inspected; an
  OS-level reduced-motion simulation was not available in this browser tool.
- Navigation/homepage additions include four languages. Existing business content
  stays as configured; some detailed editor/provider/help copy remains English.
- Before screenshots cover the original workspace/desktop and mobile navigation.
  There is no equivalent captured pre-change public/auth baseline or customer
  usability study. No measured production-load or customer task-time gain is claimed.
- The two new Python presentation services pass strict mypy. Existing Flask
  middleware/routes still report missing-annotation debt under the repository's
  broad strict configuration; this is not represented as a clean repository-wide
  Python type check. Frontend Svelte/TypeScript checks are clean.
