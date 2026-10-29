


# VERTEX SEVEN — BUSINESS-FIRST AGENT INTELLIGENCE & MODULAR AGENTIC CAPABILITIES

## Objective

I want to significantly improve the intelligence, usefulness, business awareness and agentic capabilities of Vertex Seven (V7).

My concern is that, although our AI assistants are designed around the businesses they serve, I believe they could become substantially better at genuinely understanding those businesses, representing them professionally, helping their customers and contributing to measurable business outcomes.

I do not want V7 to become another generic AI chatbot platform with a collection of integrations.

**I want V7 to become a platform of highly capable, business-specific AI assistants that can understand a company, communicate like a knowledgeable member of its team, help customers make decisions and, when authorised, execute useful business operations.**

These improvements must be modular, secure, scalable, cost-conscious and compatible with our existing architecture.

Before implementing anything, thoroughly investigate the current V7 codebase. Identify what we already have, what works, what is incomplete and what genuinely needs to change.

Do not assume existing capabilities are absent. Do not introduce unnecessary complexity or rewrite functioning systems without a justified reason.

---

## 1. Make Every Agent Genuinely Understand Its Business

This is my highest priority.

Currently, the agents can provide business-related assistance, but I want them to demonstrate a much deeper and more useful understanding of the business they represent.

Each V7 agent should develop a structured understanding of its assigned business, including:

- Business identity, industry, locations and service areas.
- Products, services, pricing, variations and availability.
- Customer types and common customer needs.
- The company's unique selling points and competitive advantages.
- Business hours, contact information and operating procedures.
- Company policies, terms, limitations and frequently asked questions.
- The company's communication style, brand personality and preferences.
- Relevant integrations, workflows and operational capabilities.
- The business's objectives and desired customer outcomes.

An agent representing a software company should communicate and assist differently from an agent representing a restaurant, translation company, property business or vehicle repair service.

These differences should come from actual configured business information and capabilities, not stereotypes or assumptions about an industry.

### Business Intelligence Layer

Investigate implementing a dedicated, structured Business Intelligence Layer for each V7 tenant.

This should combine:

1. **Verified business facts:** Information explicitly configured or provided by the business.
2. **Knowledge retrieval:** Relevant documents, FAQs, catalogues, policies and other approved sources.
3. **Operational context:** Available tools, integrations, opening hours and supported workflows.
4. **Business objectives:** What the business wants customers to accomplish.
5. **Conversation context:** What the visitor needs, what has already been established and what should happen next.

The system should retrieve and use relevant information dynamically, rather than inserting the entire business knowledge base into every prompt.

Prioritise source reliability, freshness, relevance, low latency and token efficiency.

Agents must never fabricate prices, guarantees, availability, product capabilities, policies or other business facts.

When information is missing, the agent should ask an appropriate question, provide a clearly qualified answer or offer human assistance.

**The aim is for customers to feel they are speaking with someone who genuinely understands the company.**

---

## 2. Make Agents More Commercially Useful

V7 should not simply answer questions accurately.

It should help businesses achieve practical objectives.

Examples include converting interested visitors into customers, capturing qualified enquiries, recommending appropriate services, reducing repetitive support requests and helping customers complete their intended tasks.

However, I do not want agents aggressively selling products or constantly pushing customers towards purchases.

The agent must understand the customer's intention and respond appropriately.

### Customer Intent Intelligence

Consider implementing reliable intent recognition and tracking.

The agent should recognise when a customer is:

- Researching a product or service.
- Comparing options.
- Looking for a quotation.
- Ready to purchase or book.
- Requesting support.
- Making a complaint.
- Asking about an existing order or enquiry.
- Looking for human assistance.

Responses and proposed actions should adapt to the customer's actual intent.

For example:

**Customer:** "I'm looking for someone to translate legal documents."

An ordinary chatbot might explain the company's translation services.

A genuinely business-focused V7 agent should understand that this may be a prospective customer, establish what type of document needs translating, ask about the relevant languages and deadline, explain the company's actual services and help the customer take the next appropriate step.

If an approved quotation or lead-capture workflow exists, it should use that workflow.

If the company has not configured a quotation process, the agent must not invent one.

The system should be helpful and commercially aware without becoming manipulative.

### Business Goals

Allow businesses to configure priorities such as:

- Generating qualified leads.
- Increasing appointments.
- Improving customer support.
- Helping customers choose suitable products.
- Reducing repetitive administrative work.
- Handling quotations or service enquiries.
- Escalating complex enquiries to staff.

These goals should meaningfully influence the assistant's behaviour while preserving truthful responses and customer choice.

---

## 3. Improve Conversation Quality and Professionalism

A V7 agent should communicate naturally, efficiently and professionally.

Investigate how to improve:

**Contextual understanding:** The assistant should interpret what customers actually mean, including incomplete questions, follow-ups and indirect requests.

**Conversation continuity:** It should remember relevant details within the permitted conversation scope without repeatedly asking questions that have already been answered.

**Response relevance:** It should answer the specific question instead of producing generic explanations about the company.

**Appropriate brevity:** Simple questions deserve concise answers. Complicated matters deserve more detail.

**Intelligent questioning:** Ask only for information needed to help the customer progress.

**Customer guidance:** Suggest genuinely useful next steps when appropriate, rather than appending generic calls to action to every reply.

**Brand consistency:** Match the configured business tone without sounding artificial, repetitive or excessively promotional.

**Multilingual behaviour:** Support different customer languages while preserving business-specific terminology and factual accuracy.

**Human escalation:** Recognise when the assistant lacks sufficient information, cannot complete a task or should involve a human.

The assistant must not claim to have completed something unless the relevant system confirms success.

I also want the agents to feel less scripted.

Avoid repetitive introductions, unnecessary disclaimers, robotic phrasing and overusing the business's name.

The result should feel like a competent and well-trained customer-facing employee, while remaining transparent that it is an AI assistant.

---

## 4. Build Genuine Agentic Capabilities

I want V7 assistants to progress beyond simply generating responses.

Where integrations and permissions exist, agents should be able to perform authorised business actions.

However, these abilities must be genuinely useful, not agentic features added merely for marketing purposes.

Potential capabilities include:

### Lead Management

Collect relevant enquiry information, qualify leads according to business-defined criteria, create lead records and notify the appropriate person.

### Appointment Management

Check availability, offer available appointments, create bookings, send confirmations and manage changes when authorised.

### Customer Relationship Management

Retrieve permitted customer information, create records, update relevant details and record interactions.

### Customer Support Operations

Create support tickets, categorise enquiries, check ticket status and escalate unresolved issues.

### Quotation Assistance

Collect quotation requirements, retrieve approved pricing information, generate estimates where permitted and send enquiries to the appropriate person.

### Product and Service Assistance

Search catalogues, compare suitable options, check supported availability sources and help customers make informed decisions.

### Messaging and Notifications

Send authorised confirmations, notifications and follow-ups through configured communication channels.

### Business Workflow Automation

Coordinate multiple permitted actions when necessary to complete a legitimate customer task.

For instance, with the correct permissions, an agent could collect booking requirements, check availability, create the appointment, record relevant customer information and send confirmation.

These actions should be driven by the customer's needs and the business's configuration.

**Not every business needs every capability. That brings me to an essential architectural requirement.**

---

## 5. Every Agentic Capability Must Be Modular

This is non-negotiable.

I want all optional agentic capabilities implemented through a modular architecture.

A business must not be forced to use features it does not need.

Modules should be independently manageable, with clear dependencies and configuration requirements.

Proposed modules include:

| Module | Purpose |
|---|---|
| Lead Capture | Identify and record prospective customers |
| Booking Management | Manage appointments and availability |
| CRM Integration | Interact with approved customer systems |
| Support Tickets | Create and manage support cases |
| Quotation Assistance | Collect and process quotation enquiries |
| Product Assistance | Help customers select suitable products |
| Email Actions | Send authorised transactional messages |
| Workflow Automation | Execute approved multi-step processes |
| Scheduled Tasks | Run approved time-based operations |
| Analytics & Insights | Measure customer interactions and outcomes |

These are proposed capabilities, not assumptions about what currently exists.

### Administrative Control

Implement three levels of control.

**Level 1 — V7 Platform Superadmin**

The V7 platform administrator should be able to enable or disable individual modules globally, control which subscription plans can access them, establish global restrictions and disable a problematic feature immediately.

**Level 2 — Business-Level Entitlements**

Each business should have a separately enforced set of available capabilities based on its subscription and platform-level permissions.

**Level 3 — Business Administrator Configuration**

Business administrators should be able to manage the permitted modules available to their organisation, configure their behaviour, connect required integrations and control relevant permissions.

For example, a restaurant may enable bookings and product information while disabling CRM updates.

A translation company may enable lead capture, quotation assistance and support tickets while leaving bookings disabled.

### Module Enforcement

Crucially, disabling a module must actually remove its operational capabilities.

It must not simply hide the module from the dashboard.

Enforce module permissions server-side at tool discovery, tool execution and background-job execution.

The AI should only receive access to tools that are currently authorised for the specific business and context.

If a module is disabled, its actions must not remain executable through direct API calls, cached configurations, previous conversations or scheduled jobs.

Define appropriate cancellation and recovery behaviour for workflows that are already running.

---

## 6. Design a Reliable Agent Execution System

Please evaluate the best architecture for adding genuine agentic execution to the existing V7 backend.

My preferred approach is to extend the existing assistant where practical, rather than building an unnecessarily complicated multi-agent system.

Potential components:

**Agent Orchestrator:** Interprets the user's request, chooses appropriate tools, processes results and determines the next step.

**Tool Registry:** Defines the tools made available by each module, including descriptions, parameters and required permissions.

**Module Permission Engine:** Determines what each agent can do based on the authenticated tenant, subscription, configuration and user permissions.

**Execution Layer:** Securely performs authorised actions through internal services or external integrations.

**Verification Layer:** Validates tool results and ensures the assistant accurately reports success, failure or uncertainty.

**Audit Layer:** Records relevant tool executions, approvals, failures and administrative changes.

The system should support controlled multi-step tool execution without allowing uncontrolled loops, excessive API usage or unauthorised actions.

Use timeouts, retry policies, execution limits, idempotency controls and error handling where appropriate.

Do not assume that MCP is necessarily the best solution for every internal action. Evaluate existing architecture, direct tool calling, MCP and conventional service interfaces pragmatically.

Prioritise reliability and maintainability over unnecessary architectural sophistication.

---

## 7. Business-Specific Agent Behaviour

I want businesses to be able to configure how their assistants operate without requiring technical knowledge.

Investigate an improved business administration experience.

The business owner should be able to configure:

- What the assistant knows about the business.
- What objectives the assistant prioritises.
- What tasks it is allowed to complete.
- What information it is allowed to collect.
- Which actions require approval.
- When a human should be contacted.
- How the assistant should communicate.
- What happens when a request cannot be completed.

Consider providing configurable industry-specific templates.

A restaurant template might recommend menus, dietary information, reservations and opening-hour tools.

A professional services template might recommend lead capture, qualification and quotation workflows.

These should be starting configurations, not rigid assumptions.

Business owners must retain control over their own company information and agent behaviour.

---

## 8. Strong Security and Tenant Isolation

V7 is a multi-tenant platform, so security must remain central to this design.

A business must never access another business's:

- Customer information.
- Knowledge bases.
- Leads or appointments.
- Integration credentials.
- Internal tools.
- Conversation history.
- Private configuration.
- Analytics or operational records.

Tenant identity must be established using authenticated server-side context.

Never rely on tenant identifiers, role claims or permissions generated by the language model.

Every tool and background task must independently enforce authorisation.

Implement or verify protection against prompt injection, excessive tool execution, unauthorised data access and cross-tenant information leakage.

External integrations must use appropriately scoped credentials and secure secret storage.

Sensitive actions should require suitable approval.

Marketing communications must respect applicable consent and privacy requirements.

Core safeguards such as authentication, tenant isolation, authorisation and audit logging must not become optional modules.

---

## 9. Improve Business Knowledge Management

The quality of the agents depends heavily on the quality of business knowledge.

Evaluate how businesses currently upload, organise, update and maintain their information.

I want a system that helps administrators identify:

- Missing information.
- Outdated or contradictory information.
- Unanswered customer questions.
- Frequently requested services not properly documented.
- Confusing policies.
- Knowledge that requires verification.

Where appropriate, an agent could suggest improvements to the business's knowledge base.

For example:

"Customers have asked about weekend delivery 14 times, but your configured information does not specify whether this is available."

The agent should report that knowledge gap to the business administrator.

It must not automatically invent the answer.

A well-designed feedback system could make every business's assistant more useful over time.

However, learning from conversations must not automatically promote unverified customer statements into authoritative business facts.

Business administrators should approve important knowledge changes.

---

## 10. Business Analytics and Measurable Value

I want V7 to demonstrate genuine value to its customers.

Businesses should be able to understand how their assistant is helping.

Investigate metrics such as:

- Number of customer conversations.
- Enquiries handled.
- Qualified leads created.
- Confirmed appointments.
- Support tickets created or resolved.
- Successful tool executions.
- Failed or escalated requests.
- Common customer questions.
- Missing business information.
- AI operating costs and usage.

It is important to distinguish genuine outcomes from assumptions.

For example, a conversation about purchasing a product is not automatically a completed sale.

A booking should only count as confirmed if the relevant booking system confirms it.

Similarly, lead qualification must follow business-defined criteria rather than arbitrary AI judgement.

Analytics should be useful, accurate, understandable and privacy-conscious.

I want V7 owners to see why their subscription is valuable.

---

## 11. Maintain Speed, Scalability and Cost Efficiency

We cannot improve agent intelligence by making every response dramatically slower or more expensive.

Please evaluate:

- Efficient business knowledge retrieval.
- Appropriate context management.
- Prompt and token optimisation.
- Selective tool availability.
- Sensible model selection.
- Caching where safe.
- Tool execution latency.
- API usage limits.
- Per-tenant cost monitoring.
- Concurrent customer workloads.

Simple customer questions should not trigger expensive agentic workflows unnecessarily.

The architecture should distinguish between a normal factual answer and a request requiring operational actions.

For example, asking for opening hours should not require a complex multi-step agent workflow when reliable business information is already available.

I want V7 to become smarter while remaining commercially sustainable at our existing price points.

Avoid adding permanent infrastructure costs unless there is a clear benefit.

---

## 12. Compatibility With Existing V7 Features

You must first investigate our existing implementation.

Preserve working functionality wherever reasonably possible, including:

- Tenant onboarding and workspace configuration.
- Website chat widgets.
- Business knowledge and catalogues.
- Customer-facing responses.
- Subscription and billing behaviour.
- Authentication and administrative controls.
- Existing integrations.
- Website embedding.
- Current API routes and operational workflows.

Do not replace functioning features just because a newer architecture exists.

Identify opportunities to extend or refactor the current system safely.

Any necessary database migrations should be backward-compatible where practical, reversible or accompanied by a safe rollback approach.

Existing business customers must not lose their settings or data.

New agentic capabilities should be disabled by default for existing tenants unless explicitly enabled under a documented migration policy.

---

## 13. Testing and Quality Standards

I want meaningful testing, not just confirmation that the code runs.

Evaluate agents using realistic scenarios involving different business types.

Test situations where:

1. A customer asks a simple factual question.
2. A customer asks something the knowledge base does not contain.
3. A customer has a complex enquiry requiring several conversational steps.
4. A customer wants to book an appointment.
5. A customer wants a quotation.
6. A customer asks about a product unavailable in the catalogue.
7. A customer changes their mind halfway through a workflow.
8. An integration becomes unavailable.
9. An administrator disables a module during execution.
10. A customer attempts to trick the AI into accessing another business's information.
11. The AI encounters contradictory business documents.
12. A customer needs human assistance.

Include tests for factual accuracy, correct tool selection, permissions, tenant isolation, operational success, failure recovery, latency and API costs.

Where possible, establish baseline performance before changes and compare outcomes afterwards.

Do not describe functionality as production-ready unless it has actually been implemented, tested and verified.

---

## 14. What I Want You to Do First

Before making major changes, perform a detailed V7 architecture and product audit.

I want you to establish:

**A. Existing capabilities**

What does V7 already do successfully? Which current features contribute to business intelligence or agentic behaviour?

**B. Existing weaknesses**

What prevents our assistants from understanding businesses more deeply, producing better responses or completing business tasks?

**C. Opportunities**

Which improvements would produce the greatest practical value for V7 customers?

**D. Architecture**

How should we implement a modular agentic system using our current technology while avoiding unnecessary rewrites?

**E. Administrator experience**

How should platform administrators and business administrators manage modules, permissions, objectives and integrations?

**F. Security**

What safeguards are already implemented, and what additional protections are required?

**G. Cost and performance**

How would these improvements affect response times, infrastructure requirements, model usage and operating margins?

**H. Implementation roadmap**

Produce a detailed, prioritised implementation plan with dependencies, expected outcomes, testing requirements and a safe deployment strategy.

Do not invent findings about the current codebase. Distinguish verified existing functionality from recommendations.

---

## 15. Implementation Priorities

My preferred development order is:

### Phase 1 — Business Intelligence and Response Quality

Improve the existing assistant's understanding of each business, factual accuracy, conversation quality, customer-intent awareness and ability to guide customers.

These improvements should benefit every V7 customer, including those with no optional agentic modules enabled.

### Phase 2 — Modular Architecture

Introduce the module registry, feature controls, per-tenant permissions, administrator configuration and execution safeguards.

### Phase 3 — First Practical Agentic Modules

Prioritise high-value capabilities such as lead capture, support tickets and approved business workflows.

Start with capabilities V7 can implement reliably before adding complex third-party dependencies.

### Phase 4 — External Integrations

Introduce configurable booking, CRM, email and other business integrations with secure authorisation and appropriate approval requirements.

### Phase 5 — Advanced Automation and Insights

Develop more sophisticated multi-step workflows, proactive tasks, knowledge-gap reporting and analytics.

This is a proposed sequence. Adjust it if the codebase audit reveals a safer or more effective order.

---

# Final Product Vision

Vertex Seven should not merely provide a chatbot that knows a company's name, services and opening hours.

**V7 should provide businesses with a capable AI representative that understands what the company does, understands what its customers need and knows how to help those customers achieve meaningful outcomes.**

When authorised, the assistant should also be able to act on that understanding through reliable business tools.

The system should be:

**Business-aware:** Deeply grounded in each company's actual operations.

**Customer-focused:** Helpful, natural and responsive to individual needs.

**Commercially useful:** Capable of supporting genuine business objectives.

**Agentic:** Able to complete authorised tasks instead of merely describing them.

**Modular:** Every optional capability independently configurable.

**Secure:** Strictly isolated across businesses, with enforceable permissions.

**Efficient:** Fast, cost-conscious and scalable.

**Reliable:** Honest about uncertainty, tool failures and uncompleted tasks.

**Manageable:** Understandable and controllable by nontechnical business owners.

I do not want unnecessary complexity, generic AI gimmicks or features that look impressive but provide little value.

I want an improvement to the actual quality of our product.

**Your immediate task is to assess V7 against this vision, identify the most important gaps and produce a technically detailed, prioritised plan. Once the plan is established, implement improvements in safe, testable stages, preserving existing working functionality.**

The end goal is simple:

**A customer using a V7 assistant should feel that the AI genuinely knows the business, understands the customer's situation and can provide meaningful assistance — not that they are talking to a generic chatbot with company information pasted into its instructions.**

Business Intelligence Layer — Core Platform Requirement

The Business Intelligence Layer must be a fundamental part of Vertex Seven, available to every business regardless of subscription tier.

Starter (£99/month), Business (£199/month) and Scale (£349/month) must all benefit from strong business understanding, accurate knowledge retrieval, customer-intent recognition and intelligent, context-aware responses.

These foundational intelligence capabilities must never be locked behind premium modules.

Subscription tiers may instead differ in advanced agentic capabilities, integrations, automation limits, AI usage allowances and other operational features.

Every V7 customer deserves an intelligent assistant. Higher tiers should unlock what the assistant can do, not whether it understands the business.