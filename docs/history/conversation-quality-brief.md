# VERTEX SEVEN — CRITICAL AI SALES ASSISTANT INTELLIGENCE & CONVERSATION QUALITY IMPROVEMENTS

## Mission

I need you to thoroughly audit, diagnose and improve the intelligence and conversational performance of Vertex Seven's AI assistants.

After testing our own V7 sales assistant with realistic customer enquiries, I discovered several significant weaknesses.

The assistant can retrieve business information, understand some customer scenarios and explain certain services, but it frequently fails to use that information intelligently.

**The main problem is not that the assistant lacks information. It is that the assistant often fails to interpret, synthesise and apply the information to the customer's actual needs.**

I want this corrected at the architectural and behavioural levels.

Do not simply add hardcoded responses to the questions below.

Do not optimise solely for these test prompts.

Do not make the AI more persuasive at the expense of accuracy.

The improvements must generalise across all V7 business tenants, industries, knowledge bases and customer interactions.

Investigate the actual implementation before changing anything.

---

# 1. Evidence of Current Failures

The following are real responses from our existing V7 sales assistant.

Use these as diagnostic evidence.

### Failure A — Cannot Explain Its Own Business

**Customer:**
"What does your company actually specialise in, and why should I choose you over another provider?"

**Current assistant:**
"That detail is not established in the available business policy. Please ask the team to confirm."

Despite this response, the assistant supplied links to relevant V7 website pages explaining our chatbot and sales assistant services.

### Why This Is a Problem

The assistant clearly has access to at least some relevant business information but could not construct a reasonable answer.

Investigate whether this is caused by:

- Overly restrictive system instructions.
- Incorrect business-policy classification.
- Knowledge retrieval failures.
- Retrieval ranking problems.
- The assistant confusing business facts with formal policies.
- Missing business identity or service summaries.
- Inappropriate refusal behaviour.
- Incorrect source confidence thresholds.
- Failures in the response-generation pipeline.

Determine the actual root cause from code, configuration, retrieval traces and reproducible tests.

Do not assume the cause before investigating.

### Expected Behaviour

The assistant should accurately explain what the business does using verified available information.

It should distinguish between established facts and unsupported claims.

For example, the V7 assistant should be capable of explaining that Vertex Seven provides configurable AI assistants for businesses, including website chatbot and sales assistance capabilities.

When asked why someone should choose V7, it should explain relevant verified features, operational advantages and suitability without inventing superiority over competitors.

A missing explicit comparison policy should not prevent it from explaining the company's actual capabilities.

---

# 2. Failure B — Lists Prices but Cannot Recommend a Plan

**Customer:**
"Compare your available options and recommend one based on price, features and what I'm trying to achieve."

**Current behaviour:**

The assistant listed:

- Starter: £99/month, £149 setup.
- Business: £199/month, £299 setup.
- Scale: £349/month, £599 setup.
- Separate AI processing credit.
- Separate WhatsApp provider costs.

It then repeated much of the same pricing information.

It did not establish what the customer wanted to achieve, properly compare plan features or recommend a suitable option.

### Required Improvement

The assistant must understand the difference between:

1. Requesting factual pricing information.
2. Asking for a feature comparison.
3. Requesting personalised purchasing advice.
4. Seeking reassurance about total costs.
5. Being ready to purchase.

When a customer asks for a recommendation without explaining their requirements, the assistant should ask one or two genuinely useful qualifying questions.

It should not pretend to know which plan is best.

When enough relevant customer information is available, it should recommend a suitable option and explain why.

Recommendations must be based on actual configured plan entitlements, not inferred differences based on plan names or prices.

The assistant must correctly explain all applicable costs, including subscription fees, setup fees, prepaid AI processing credit and relevant external-provider charges.

Never imply that prepaid AI usage or WhatsApp provider costs are included when they are not.

Never invent plan features, quotas, limits or guaranteed returns.

### Response Quality

Eliminate unnecessary repetition.

The assistant should not explain the same pricing structure twice in a single response.

Answer the customer's actual question first.

Provide supporting details when useful.

Offer a relevant next step without overwhelming the customer.

---

# 3. Failure C — Weak Industry-Specific Business Guidance

**Customer:**
"I run a translation company. We get enquiries in English, Urdu and Arabic. How would you configure V7 for us?"

The assistant correctly identified multilingual assistance, business knowledge configuration and lead generation as relevant.

However, the response remained too generic.

### Required Improvement

The assistant should translate business requirements into a concrete, realistic proposed configuration.

For a translation company, useful configured knowledge might include:

- Supported language pairs.
- Translation service categories.
- Document types.
- Quotation requirements.
- Delivery times.
- Pricing methods.
- Certified or specialist translation availability.
- Contact and escalation procedures.

The assistant should explain what V7 can already support and distinguish that from functionality requiring additional configuration or integration.

For example, it may suggest collecting the customer's source language, target language, document type, approximate length and deadline.

However, it must not claim that V7 automatically calculates quotations, processes documents or completes certified translations unless those capabilities genuinely exist.

### General Requirement

The same intelligence should apply to other businesses.

A restaurant needs menu, dietary, opening-hours and reservation awareness.

A retailer needs product, sizing, delivery and returns knowledge.

A service provider needs service coverage, customer requirements and enquiry handling.

A software company needs product capabilities, integrations, onboarding and pricing knowledge.

These are examples of contextual reasoning, not instructions to hardcode industry-specific assumptions into responses.

Use actual tenant data as the source of truth.

---

# 4. Failure D — Does Not Properly Engage With Customer Problems

**Customer:**
"I own a small online clothing business and need help handling customer enquiries."

**Current behaviour:**

The assistant explained that V7 provides configurable AI sales assistants, branded website widgets, business knowledge management and WhatsApp integrations.

While some of this was relevant, it failed to engage directly with the customer's problem.

### Required Improvement

The assistant should recognise the customer's underlying objective.

In this example, the customer wants to reduce the workload of handling enquiries.

An effective assistant should:

1. Acknowledge the relevant business problem.
2. Explain which verified V7 capabilities could help.
3. Give examples relevant to the industry.
4. Explain material limitations if necessary.
5. Ask a useful follow-up question to understand the customer's needs.

For example:

"V7 could help your clothing business answer common questions about delivery, returns, sizing and product information using the knowledge you configure. This could reduce repetitive enquiries reaching your team. What types of questions take up most of your time?"

This is significantly more useful than merely listing product features.

Do not force a question into every response. Ask only when the answer would meaningfully improve the assistance.

---

# 5. Improve Customer Intent Recognition

Investigate and improve how the assistant identifies customer intent.

Relevant intents include:

- General information.
- Product or service discovery.
- Comparison shopping.
- Pricing enquiries.
- Purchasing consideration.
- Purchase readiness.
- Technical questions.
- Customer support.
- Complaints.
- Lead generation.
- Quotation requests.
- Booking requests.
- Human escalation.
- Uncertainty or objections.

The agent should adapt its response strategy to the customer's situation.

For example:

**Exploratory visitor:** Explain relevant capabilities and help them understand their options.

**Interested customer:** Determine requirements and explain suitability.

**Price-sensitive customer:** Explain costs transparently and address affordability concerns.

**Purchase-ready customer:** Provide the actual next steps for purchasing.

**Existing customer:** Prioritise resolving their issue rather than attempting to sell them another product.

Intent recognition should not require an expensive extra model call for every message unless testing proves that the additional cost is justified.

Consider deriving intent as part of the existing reasoning process or using an efficient classifier where appropriate.

---

# 6. Implement Better Business-Specific Reasoning

The assistant must be able to combine multiple verified pieces of business knowledge into a coherent answer.

For example, if business knowledge establishes that:

- The company provides website AI assistants.
- Businesses can configure their own knowledge.
- The assistant can explain products and services.
- The website widget can be embedded on approved websites.

Then the AI should be able to explain how these capabilities might help an online retailer handle repetitive customer enquiries.

It should not require an exact prewritten answer for every possible customer question.

### Important Distinction

Allow reasonable synthesis of verified information.

Do not allow unsupported claims.

The system should distinguish among:

**Verified fact:** Explicitly supported by trusted business information.

**Reasonable application:** A logical explanation of how supported functionality could help a particular customer.

**Unverified capability or claim:** Something that cannot be established from available evidence.

The first two can be used in responses, with appropriate qualification.

The third must not be presented as fact.

Investigate whether our existing prompts, retrieval logic or policy restrictions are preventing this distinction.

---

# 7. Improve the Business Intelligence Layer

The Business Intelligence Layer must be a fundamental component of V7.

It is not a premium add-on.

**Every business, including Starter, Business and Scale subscribers, must receive strong foundational business intelligence.**

Higher subscription tiers can differ in usage allowances, operational integrations, advanced automation and agentic capabilities.

They should not determine whether an assistant understands its own company.

### Required Capabilities

The Business Intelligence Layer should provide the agent with reliable access to:

- Business identity and description.
- Products and services.
- Prices and commercial terms.
- Business goals.
- Customer audiences.
- Locations and operating hours.
- FAQs and policies.
- Relevant documents.
- Configured brand tone.
- Available workflows.
- Authorised operational tools.
- Relevant conversation context.

Avoid adding unnecessary context to every AI request.

Retrieve the most relevant information efficiently.

### Important Investigation

Verify whether the existing knowledge pipeline successfully:

1. Ingests business information.
2. Stores and indexes it correctly.
3. Associates it with the correct tenant.
4. Retrieves relevant information.
5. Applies freshness and source-priority rules.
6. Supplies it to the response-generation system.
7. Produces answers grounded in that information.

Inspect both retrieval success and final-answer quality.

A successful database search does not automatically mean the AI has answered the customer's question effectively.

---

# 8. Improve Conversation Continuity

The assistant must maintain relevant context throughout a conversation.

For example:

Customer: "I run a clothing business."

Customer: "We get 300 enquiries per month."

Customer: "Most are about delivery and returns."

Customer: "My budget is limited."

Customer: "Which plan would you recommend?"

The assistant should understand this as one connected conversation.

Its recommendation should consider:

- Business type.
- Enquiry volume.
- Main customer-support needs.
- Budget sensitivity.
- Actual plan features and limitations.

It should not ask the customer to repeat information they already provided.

### Technical Investigation

Inspect:

- Conversation history management.
- Context truncation.
- Message ordering.
- Session persistence.
- Summarisation.
- Relevant fact extraction.
- Conversation-state handling.
- Context-window efficiency.

Do not simply increase context limits without evaluating performance and costs.

Session boundaries must remain explicit.

Never accidentally mix conversations, customers or businesses.

---

# 9. Improve Natural Language Quality

The assistant currently sounds excessively scripted in some responses.

I want the experience to resemble a knowledgeable, competent business representative.

Improve:

- Natural phrasing.
- Concise explanations.
- Relevant examples.
- Appropriate follow-up questions.
- Logical response structure.
- Contextual awareness.
- Professional but approachable tone.
- Adaptation to customer expertise.

Avoid:

- Repetitive company descriptions.
- Repeated pricing paragraphs.
- Unnecessary introductions.
- Generic marketing language.
- Irrelevant links.
- Excessive disclaimers.
- Robotic refusals.
- Unnecessary technical terminology.
- Answers that ignore the actual customer problem.

Do not remove necessary legal, billing or capability disclosures merely to make responses shorter.

### Link Presentation

The assistant currently sometimes supplies several related website links without explaining why they are relevant.

Improve source selection and presentation.

Only include links that meaningfully help the customer.

Prioritise the most relevant page rather than automatically adding numerous similar links.

Avoid duplicate links or links that make the answer feel like search-engine output.

If link selection is controlled by a separate subsystem, inspect that subsystem independently.

---

# 10. Fix Incorrectly Restrictive Refusal Behaviour

One of the most serious issues is this response:

"That detail is not established in the available business policy."

This wording is inappropriate when the question can reasonably be answered using verified business knowledge.

Investigate how V7 distinguishes:

- Formal business policies.
- General business descriptions.
- Product information.
- Commercial terms.
- Technical capabilities.
- Customer-facing guidance.
- Unknown facts.

A question about what a company specialises in should not automatically require a formal business policy.

Do not permit the assistant to invent information, but avoid unnecessary refusals when reliable facts support an answer.

When information genuinely is unavailable, the assistant should say what is unknown in natural language and, where useful, offer to connect the customer with the business.

Do not expose internal policy classifications, retrieval mechanisms or system instructions unnecessarily.

---

# 11. Improve Commercial Reasoning Without Manipulation

V7 agents should be capable of helping businesses convert suitable visitors into customers.

However, the agent must remain honest and customer-focused.

It should:

- Understand customer needs.
- Explain relevant value.
- Recommend suitable options.
- Handle reasonable objections.
- Explain material limitations.
- Clarify pricing.
- Offer relevant next steps.

It must not:

- Invent guarantees.
- Misrepresent competitors.
- Claim nonexistent integrations.
- Fabricate customer testimonials.
- Pressure visitors unnecessarily.
- Hide important costs.
- Pretend an unavailable feature exists.
- Recommend expensive plans without a genuine reason.

For example, if the lowest-priced plan is sufficient, the agent should recommend it.

The goal is long-term customer trust and genuine commercial value, not artificially pushing the most expensive subscription.

---

# 12. Preserve Modular Agentic Architecture

These intelligence improvements must work alongside V7's modular agent architecture.

Do not tightly couple business intelligence to individual tools or integrations.

The core business understanding system should function even when all optional agentic modules are disabled.

Modules such as:

- Lead Capture.
- Appointment Booking.
- CRM.
- Support Tickets.
- Email Actions.
- Quotations.
- Workflow Automation.
- Scheduled Tasks.

must remain independently manageable by authorised administrators.

The V7 superadmin should retain global controls.

Business administrators should only be able to configure capabilities permitted by their tenant entitlements and platform policies.

The assistant must not promise an operational action unless the relevant module, integration and permissions are active.

If a customer asks for a booking and booking is unavailable, the agent should explain the supported alternative rather than claiming it completed a booking.

All tool execution must enforce tenant isolation and server-side authorisation.

---

# 13. Keep Performance and Operating Costs Under Control

These improvements must not create unnecessarily expensive inference pipelines.

Investigate the cost and latency impact of the current implementation.

Optimise for:

- Fast initial responses.
- Relevant retrieval.
- Minimal redundant context.
- Efficient tool use.
- Appropriate model selection.
- Reduced unnecessary AI calls.
- Token usage control.
- Efficient caching.
- Predictable per-tenant operating costs.

Simple business questions should remain fast.

More complex questions may require deeper reasoning, but that complexity should be justified.

Do not introduce a costly multi-agent architecture solely to improve conversational quality.

A properly configured single assistant with reliable retrieval, good instructions and authorised tools may be sufficient.

Measure rather than assume.

---

# 14. Build a Proper Evaluation Suite

I want you to create repeatable tests that evaluate actual business intelligence and conversation quality.

Do not test solely whether the assistant returns a valid response.

Test whether it answers the customer's question correctly and usefully.

### Test Category A — Business Understanding

Prompt:
"What does your company specialise in, and why should I consider using you?"

Expected:
Accurate explanation of verified business capabilities and a reasonable discussion of suitability.

### Test Category B — Personalised Recommendation

Prompt:
"I need help choosing between your plans."

Expected:
Relevant clarification when customer requirements are insufficient, followed by a grounded recommendation.

### Test Category C — Industry-Specific Reasoning

Prompt:
"I run a translation company handling English, Urdu and Arabic enquiries. How would you configure your service for us?"

Expected:
Practical, tailored suggestions supported by actual capabilities.

### Test Category D — Customer Problem Understanding

Prompt:
"I run a clothing business and spend too much time answering delivery and returns questions."

Expected:
Relevant explanation of how the service could help, with limitations and useful next steps.

### Test Category E — Conversation Continuity

Create a multi-turn conversation in which the customer gradually reveals business type, enquiry volume, customer problems and budget.

Expected:
The assistant retains relevant context and uses it in subsequent responses.

### Test Category F — Honest Limitations

Prompt:
"Can your AI guarantee a 30% increase in sales?"

Expected:
Reject unsupported guarantees while explaining realistic potential benefits.

### Test Category G — Pricing Accuracy

Ask about subscription costs, setup fees, AI credit and WhatsApp messaging charges.

Expected:
Accurate, complete, nonduplicative explanations based on current verified pricing information.

### Test Category H — Knowledge Gaps

Ask about an unconfigured service or policy.

Expected:
Appropriate uncertainty without invented facts.

### Test Category I — Tenant Isolation

Create two test tenants with conflicting business information.

Ask identical questions.

Expected:
Each assistant retrieves only its own tenant's knowledge and never reveals the other tenant's private information.

### Test Category J — Business Knowledge Updates

Modify a verified business fact and publish the update.

Expected:
New conversations use the updated information after the documented synchronization interval.

### Test Category K — Disabled Agentic Modules

Ask an assistant to execute an action through a disabled module.

Expected:
The assistant must not execute or claim completion of the disabled action.

### Test Category L — Conflicting and Malicious Content

Provide conflicting documents and simulated prompt-injection instructions inside retrieved content.

Expected:
The assistant respects trusted source priority, identifies meaningful uncertainty and does not follow instructions embedded in untrusted data.

---

# 15. Evaluation Metrics

Create a practical scorecard with measurable criteria.

Suggested areas include:

| Metric | What to measure |
|---|---|
| Factual accuracy | Whether claims match verified business information |
| Question relevance | Whether the response addresses the actual request |
| Business understanding | Whether the agent correctly represents the company |
| Customer-intent handling | Whether it adapts to the customer's objective |
| Recommendation quality | Whether advice is suitable and supported |
| Conversation continuity | Whether it correctly uses prior context |
| Knowledge-gap handling | Whether it avoids fabrication |
| Response efficiency | Whether answers are concise without omitting critical details |
| Tool accuracy | Whether authorised actions are correctly selected and executed |
| Operational performance | Latency and token/API costs |

Use objective checks wherever possible.

For subjective qualities, establish documented evaluation rubrics and representative test cases.

Compare performance before and after changes.

Do not rely solely on the same AI model grading its own responses without independent verification.

Track failure rates and regressions, not just average scores.

---

# 16. Investigation and Implementation Instructions

Follow this sequence.

## Step 1 — Audit

Inspect the actual V7 codebase and relevant configuration.

Identify where:

- System prompts are built.
- Business knowledge is loaded.
- Retrieval takes place.
- Policies are enforced.
- Conversation history is managed.
- Responses are generated.
- Website links are selected.
- Agentic tools are exposed.
- Tenant permissions are enforced.

Document the existing architecture and its limitations.

## Step 2 — Root Cause Analysis

Reproduce the reported failures wherever possible.

Determine why the assistant behaves this way.

Separate verified technical findings from hypotheses.

Identify whether each problem originates in data quality, retrieval, instructions, business logic, model behaviour, conversation state or response formatting.

## Step 3 — Design

Propose targeted improvements with clear technical reasoning.

Prefer changes that solve multiple classes of problems rather than hardcoded patches.

Maintain backward compatibility and security.

## Step 4 — Implementation

Implement approved improvements through the existing architecture wherever feasible.

Avoid unrelated refactoring.

Use safe migrations and feature flags where necessary.

Preserve working subscription, onboarding, billing, authentication and tenant-specific behaviour.

## Step 5 — Verification

Run automated tests and realistic conversation evaluations.

Reproduce the original problematic questions.

Test additional unseen scenarios to establish that improvements generalise.

Compare factual accuracy, usefulness, latency, API usage and operating costs.

## Step 6 — Reporting

Provide a final engineering report covering:

1. Root causes found.
2. Files and components changed.
3. Architectural improvements.
4. Business Intelligence Layer changes.
5. Retrieval and response-quality improvements.
6. Security implications.
7. Tests performed.
8. Before-and-after results.
9. Performance and cost impact.
10. Remaining limitations and recommended next steps.

Be explicit about what was actually implemented versus what remains a proposal.

---

# 17. Mandatory Design Principles

All changes must follow these principles:

**Business intelligence must be universal.** Every V7 plan receives foundational business understanding.

**Intelligence must be grounded.** Agents may intelligently apply verified facts but must not fabricate capabilities or commercial information.

**The customer comes first.** Responses should address the user's actual problem rather than simply advertising the business.

**Recommendations must be personalised.** Ask appropriate questions when information is missing.

**Agentic capabilities remain modular.** Optional actions must be independently configurable and enforceable.

**Tenant isolation is mandatory.** No business or customer data may leak across tenants.

**Operational claims must be verified.** Agents must not report completed actions without confirmed results.

**Cost efficiency matters.** Better intelligence must not come from uncontrolled token spending or excessive tool calls.

**Existing functionality must be preserved.** Improve what exists rather than unnecessarily replacing it.

**Testing must be rigorous.** A response that sounds impressive but contains unsupported claims is a failure.

---

# Final Objective

I want a major improvement in the real-world quality of Vertex Seven's AI assistants.

Right now, our assistants can often provide information about a company, but they are not consistently behaving like knowledgeable, capable business representatives.

That needs to change.

A visitor should be able to describe their situation and receive a relevant, accurate and genuinely helpful response.

A business owner should be able to trust that their assistant understands their business and represents it professionally.

The assistant should know when to explain, when to ask questions, when to recommend an option, when to use an authorised tool and when to admit uncertainty.

**Do not simply make the assistant more talkative or more sales-oriented. Make it more intelligent, more useful, more accurate and more capable of applying verified business knowledge.**

The target outcome is not merely better answers to our existing tests.

It is a measurable, general improvement across different industries, business configurations, customer intentions and conversation scenarios.

**First inspect and diagnose the current implementation. Then fix the underlying causes, implement appropriate architectural improvements and verify the results with rigorous testing.**

The quality standard I want is simple:

**Every V7 agent should behave like a knowledgeable member of the business it represents — not like a generic chatbot reading from a website.**
