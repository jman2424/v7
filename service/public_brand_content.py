"""Public brand facts; no account, tenant or provider-login information."""
from service.public_site_content import Solution


ABOUT: Solution = {
    "title": "About Vertex Seven | V7 Agents for Business Websites",
    "description": "Vertex Seven provides V7 Agents, a configurable AI sales assistant for business websites. Learn about the product, UK online service, setup and pricing.",
    "label": "About Vertex Seven",
    "h1": "Vertex Seven, the brand behind V7 Agents",
    "intro": "Vertex Seven provides V7 Agents: an AI sales assistant platform for business websites. Vertex Seven is the brand and V7 Agents is the product. Our official website is vertex-seven.com. We operate online and serve businesses across the United Kingdom, without in-person customer appointments.",
    "audience": "For retailers, online stores, service businesses and companies with multiple branches.",
    "sections": [
        {"heading": "What does V7 Agents do?", "paragraphs": [
            "V7 Agents helps website visitors explore products or services, ask questions about business policies, and find a useful next step. Businesses configure the information behind the conversation: catalog, prices, FAQs, opening hours, branches, delivery rules and contact paths.",
            "The product includes a business management workspace and an embeddable website chat widget. Teams can tailor response tone, conversation goals, welcome messages, colours and widget appearance, then test customer questions before publishing.",
        ]},
        {"heading": "How does it fit different business models?", "paragraphs": [
            "A retailer can configure product information and delivery policies. A service business can explain its services and collect enquiries. A multi-branch company can supply branch details and opening hours. Each business supplies its own facts and chooses customer actions that its team can fulfil.",
            "Quotes, callbacks, consultation slots and other customer actions depend on configuration. Listing a service does not automatically connect a booking system, payment service or shop inventory. WhatsApp is optional and needs a configured Meta or Twilio provider connection.",
        ]},
        {"heading": "What does the platform cost?", "paragraphs": [
            "The monthly platform plan is £400 plus £80 VAT, or £480 per month including VAT. Required implementation is a separate one-time £200 plus £40 VAT, or £240 including VAT. AI API usage is additional and varies with usage; it is not included in either charge.",
            "The optional WhatsApp add-on is a separate £200 plus £40 VAT, or £240 per month including VAT. Website chat works independently of this add-on. Review the homepage pricing section and the checkout totals before purchasing.",
        ]},
        {"heading": "What should a business test before launch?", "paragraphs": [
            "Try a known product or service question, a policy question, an enquiry needing your team, a request outside your business knowledge, and a question with missing details. Check that the answers match your source information and that the next step is something your business can actually provide.",
            "AI responses can be incorrect. Your team remains responsible for accurate business information, important decisions and customer follow-up. Product descriptions and illustrative conversations on this website are not customer testimonials or guarantees of sales results.",
        ]},
    ],
    "steps": [
        {"title": "Explore the product", "description": "Read the public solution pages and sample conversation on the homepage. No account is needed to explore them."},
        {"title": "Arrange onboarding", "description": "A platform operator creates the business workspace and owner access. Business management requires an authorised account."},
        {"title": "Configure and launch", "description": "Add current business knowledge, test typical enquiries and embed the widget on your approved website."},
    ],
    "caution": "Vertex Seven is an online-only business. This page describes the public V7 Agents product; it does not expose company workspaces, customer conversations or account information. The service needs onboarding and a working provider configuration.",
}
