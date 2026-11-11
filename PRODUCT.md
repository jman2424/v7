# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Business owners (primary).** Owners of small local shops and retail businesses
  (the first buyers), usually non-technical, deciding whether an AI assistant can
  answer their customers and then running it themselves from the console.
- **Their customers.** Anonymous visitors chatting through the widget on the
  business's own website, or over WhatsApp, often on a phone.
- **Platform operator.** Vertex Seven staff onboarding businesses and monitoring them.

## Product Purpose

V7 Agents is an AI sales and support assistant a business configures with its own
products, prices, FAQs, branches, delivery rules and offers. It answers customers on
the business's website and WhatsApp, captures leads, and shows the owner what was
asked and sold. Success: a shop owner can set it up without code and trust what it
tells customers.

## Positioning

The assistant answers only from the business's own saved knowledge, and the owner
controls that knowledge, the assistant's limits and its spending from one workspace.

## Operating Context

- Owners use the console at `/console` on a laptop or phone: Home, My Business,
  Sales & Customers, Channels, Billing, Settings.
- Prospects meet the product on the public site (home, pricing, solutions, guides)
  and can try the live widget there before signing up.
- The widget runs inside an iframe on third-party business websites, with each
  business's own name, logo and colours.
- Pricing is in GBP: a monthly subscription plus separate prepaid AI usage.

## Capabilities and Constraints

- Channels: website chat, WhatsApp, phone and email.
- Console languages offered: English, Spanish, French, Arabic (right-to-left).
  Translation coverage is partial today.
- Strict Content-Security-Policy: scripts need a nonce, styles may be inline, fonts
  and images must be same-origin (images may also be `https:`/`data:`). No third-party
  font or script hosts.
- The public site is server-rendered Jinja templates with plain CSS and small
  scripts; the console is SvelteKit; the widget is one template, one stylesheet and
  one script. No CSS framework.
- The widget must remain themeable per business and must not carry Vertex Seven's
  look onto a customer's website beyond the small attribution.

## Brand Commitments

- Name: Vertex Seven; product: V7 Agents.
- The approved logo files in `dashboard/static/img/` (see `docs/guides/branding.md`)
  are used unchanged.
- Dark green remains the brand colour. The owner chose to keep this identity and
  make all three surfaces share one consistent system (decision of 11 November 2026).

## Evidence on Hand

- Real plan names and prices from `service/plan_catalog.py`.
- A working live widget on the homepage, backed by a real configured tenant.
- No customer testimonials, logos, case studies or usage statistics exist. Do not
  invent any.

## Product Principles

1. The business's own facts come first; the assistant never outranks them.
2. A non-technical owner must be able to do everything without help.
3. Costs are stated plainly, before they are incurred.
4. One business never sees another's data, branding or customers.
5. Say what the product does today; make no claim it cannot demonstrate.

## Accessibility & Inclusion

Visible keyboard focus, reduced-motion support and right-to-left layout already exist
and must be preserved. Target WCAG 2.2 AA contrast.
