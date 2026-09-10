# AGENTS.md - V7 AI Sales Agent Platform

This repository is for a modular, multi-tenant AI sales agent chatbot platform.
It is not an education platform and has nothing to do with Acaderra.

Agents working in this repository must treat the product as a reusable sales
assistant that can be configured, deployed, and managed for different companies.

## Product Goal

V7 is designed to be an advanced AI sales assistant for businesses.

The system should:

- Understand the niche, catalog, policies, branches, delivery rules, offers, FAQs,
  and tone of the company it is assisting.
- Drive useful sales conversations, not just answer isolated questions.
- Support multiple customer channels, including web chat and WhatsApp.
- Be embeddable on each business's own website as a branded chat widget or
  hosted chat experience.
- Keep each company/tenant isolated from every other company.
- Be easy to adapt for new companies without rewriting shared platform code.
- Be manageable by both the platform operator and the business owner.

## Roles

The expected management model is:

- `platform_admin`: the owner/operator of this platform.
- `business_owner`: the company owner who manages their own chatbot setup.
- `business_staff`: optional limited-access staff for a tenant.
- `customer`: the end user chatting with the sales agent.

Do not add or rename roles casually. When role logic exists, inspect the code
before changing it.

## Tenant Model

Tenant-specific data should live behind tenant boundaries.

Typical tenant configuration includes:

- Catalog/products
- Prices and offers
- FAQs
- Store/branch information
- Delivery areas and rules
- Branding
- Website embed settings
- Tone/style settings
- Overrides and guardrails
- Analytics and lead history

Never allow one tenant's data, analytics, leads, settings, or credentials to leak
into another tenant.

## Management Requirements

The platform should be manageable at two levels:

- Business owners should be able to update their own products, prices, stock
  status, FAQs, branches, opening hours, delivery rules, offers, contact paths,
  brand tone, and website widget settings without code changes.
- Platform admins should be able to onboard tenants, configure integrations,
  control AI mode/settings, inspect logs, monitor analytics, manage owner access,
  and troubleshoot tenant knowledge.

When adding management features, prefer authenticated dashboard/API workflows
over manual file edits.

## Website Integration

The sales agent must be easy to integrate into a tenant's existing website.

Website integration should support:

- A lightweight embeddable script or iframe widget.
- Tenant-specific branding, colors, logo, welcome message, and tone.
- Clear tenant identification so messages always route to the correct business.
- Safe CORS/origin controls for approved business domains.
- Mobile-friendly chat UI.
- Lead capture and handoff paths where appropriate.
- Analytics attribution for website conversations.

Do not hardcode one business's domain or branding into shared widget code.

## Frontend Direction

The long-term owner/admin frontend should use SvelteKit with a polished,
business-grade UI. Until that frontend exists, keep the current Flask dashboard
working and secure.

When adding frontend work:

- Prefer reusable, tenant-aware management screens.
- Keep owner workflows simple enough for non-technical business users.
- Avoid exposing server secrets or tenant-private data in browser bundles.
- Keep website widget UI mobile-friendly and easy to embed.

## Backend Direction

The current backend is Python/Flask and should remain stable while the platform
evolves. Rust may be introduced for performance-critical or security-sensitive
services when there is a clear boundary and a real reason.

Do not rewrite working Python services into Rust without an explicit migration
plan.

## Engineering Rules

- Prefer small, correct changes over large rewrites.
- Preserve existing behavior unless the task explicitly asks to change it.
- Follow the current stack and patterns in this repo.
- Keep shared platform logic separate from tenant-specific data.
- Do not introduce hardcoded company-specific behavior into shared code.
- Do not weaken authentication, authorization, CSRF, rate limiting, validation,
  logging, or tenant isolation to make something pass.
- Do not store real secrets in code.
- Do not invent requirements without evidence from the user or repository.

## Current Stack

The current implementation is a Python/Flask application with:

- `app/` for app creation, config, middleware, and dependency wiring.
- `routes/` for HTTP endpoints.
- `service/` for orchestration, analytics, CRM, routing, memory, and sales logic.
- `retrieval/` for tenant data stores.
- `ai_modes/` for V5/V6/V7 response strategies.
- `business/` for tenant data.
- `dashboard/` for admin and widget UI assets.
- `tests/` for pytest coverage.

Do not migrate frameworks unless explicitly asked.

## Testing

Run the smallest relevant check for the change.

Common commands include:

- `pytest`
- `ruff check .`
- `mypy .`

Do not claim checks passed unless they were actually run.

## Final Response

When finishing code work, report:

- What changed.
- Files changed.
- Checks run and results.
- Any known risk or skipped check.
