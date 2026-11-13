# Documentation index

| Start here | |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Repository map, request flow, tenancy, storage, where to change things. |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | Current gaps and deferred work. |
| [../AGENTS.md](../AGENTS.md) | Rules for anyone (human or AI) changing this repository. |
| [../env.example](../env.example) | Every environment variable. |

## reference/ — how the system works

| Page | Covers |
|---|---|
| [http-routes.md](reference/http-routes.md) | Every endpoint and its handler (generated). |
| [module-index.md](reference/module-index.md) | One line per Python module (generated). |
| [data-model.md](reference/data-model.md) | Tenant documents, SQLite tables, PostgreSQL. |
| [rest-api.md](reference/rest-api.md) | The `/api/v1` REST interface. |
| [mcp.md](reference/mcp.md) | The MCP endpoint and OAuth consent. |
| [agent-conversations.md](reference/agent-conversations.md) | How a grounded reply is produced. |
| [grounded-conversations.md](reference/grounded-conversations.md) | Funded answers and the saved-knowledge fallback. |
| [conversation-memory-and-navigation.md](reference/conversation-memory-and-navigation.md) | Memory controls and website destinations. |
| [channel-intelligence.md](reference/channel-intelligence.md) | Shared reasoning, channel-specific delivery. |
| [ai-disclosure-and-phone.md](reference/ai-disclosure-and-phone.md) | AI identification and inbound calls. |
| [agent-module-controls.md](reference/agent-module-controls.md) | Optional agent modules and grants. |
| [business-actions-and-testing.md](reference/business-actions-and-testing.md) | Bookings and other chat actions. |
| [business-applications.md](reference/business-applications.md) | Commercial eligibility applications. |
| [business-sync.md](reference/business-sync.md) | Data sources, imports and the sync engine. |
| [generic-business-core.md](reference/generic-business-core.md) | Supporting non-retail businesses. |
| [chat-reliability.md](reference/chat-reliability.md) | Transcript reliability and console search. |
| [response-performance.md](reference/response-performance.md) | Chat latency measurement. |

## guides/ — setting up and running a business on V7

| Page | Covers |
|---|---|
| [onboarding.md](guides/onboarding.md) | Configuring a new tenant. |
| [business-imports.md](guides/business-imports.md) | Importing a client's information and keeping it current. |
| [launch-readiness.md](guides/launch-readiness.md) | Checklist before a customer goes live. |
| [registration.md](guides/registration.md) | Account creation and the mail sender it needs. |
| [account-recovery.md](guides/account-recovery.md) | Passwords and account management. |
| [widget-workspace.md](guides/widget-workspace.md) | Designing and installing the website widget. |
| [whatsapp-setup.md](guides/whatsapp-setup.md) | Connecting WhatsApp. |
| [client-email-setup.md](guides/client-email-setup.md) | Support email setup and retention. |
| [vertex-email-operations.md](guides/vertex-email-operations.md) | Vertex Seven's own mail addresses. |
| [billing-plans.md](guides/billing-plans.md) | Monthly plans. |
| [prepaid-usage-billing.md](guides/prepaid-usage-billing.md) | Prepaid AI usage. |
| [ai-model-settings.md](guides/ai-model-settings.md) | Per-business model choice. |
| [tester-limits.md](guides/tester-limits.md) | Free tester allowance. |
| [referrals.md](guides/referrals.md) | Referral programme. |
| [platform-offers.md](guides/platform-offers.md) | Operator controls for live platform offers. |
| [setup-promotion-codes.md](guides/setup-promotion-codes.md) | Setup offers and implementation support. |
| [signup-discount-offers.md](guides/signup-discount-offers.md) | Optional customer signup discounts. |
| [subscription-discounts.md](guides/subscription-discounts.md) | Private subscription discount codes. |
| [language-support.md](guides/language-support.md) | Console languages. |
| [branding.md](guides/branding.md) | Vertex Seven logo and brand assets. |
| [privacy-cookie-policy.md](guides/privacy-cookie-policy.md) | Public privacy and cookie pages. |
| [public-seo.md](guides/public-seo.md) | Public search pages. |

## operations/ — running the deployment

| Page | Covers |
|---|---|
| [operations.md](operations/operations.md) | Backups, recovery, WhatsApp routing, dependencies, monitoring. |
| [security.md](operations/security.md) | Security controls and account provisioning. |
| [live-backup.md](operations/live-backup.md) | Complete export of a live SQLite runtime. |
| [supabase-migration.md](operations/supabase-migration.md) | Moving to PostgreSQL. |
| [agent-evaluation.md](operations/agent-evaluation.md) | Running the agent benchmark. |

## legal/ — drafts awaiting a solicitor

Proposed Acceptable Use Policy and data import/synchronisation terms, with the questions
for review. Not in force. See [legal/README.md](legal/README.md).

## history/ — dated work records

Briefs, audits and release records kept for context. They describe the code as it
was on their date and may name files that have since moved or been removed. Do not
treat them as current reference.
