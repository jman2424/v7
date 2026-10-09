"""Public brand facts; no account, tenant or provider-login information."""
from service.public_site_content import Solution


SETUP_GUIDE: Solution = {
    "title": "V7 Agents Setup Guide | Vertex Seven",
    "description": "Prepare business knowledge, test customer enquiries and launch a branded website chatbot with this practical V7 Agents setup guide.",
    "label": "Setup guide",
    "h1": "From business knowledge to a useful customer conversation",
    "intro": "A practical guide to preparing and testing V7 Agents for your business website. The examples below are fictional demonstrations, not customer testimonials or measured results.",
    "audience": "For online retailers, service businesses and teams managing multiple branches.",
    "sections": [
        {"heading": "Start with facts your team can maintain", "paragraphs": [
            "Prepare your current products or services, prices, FAQs, delivery rules, opening hours and contact details. Include conditions and exceptions: where delivery is available, when a quote needs review, and which questions your team must handle.",
            "Use the business workspace to maintain this information. Keep private credentials and unnecessary customer details out of the knowledge you supply. Choose a conversation goal your team can fulfil, such as helping a visitor compare products or requesting a callback.",
        ]},
        {"heading": "Retail demonstration: narrow the choice", "paragraphs": [
            "Fictional catalogue: a compact desk lamp costs £35 and has adjustable warm light. A customer asks, ‘Which lamp fits a small desk?’ A useful response explains the known size and lighting features, then asks about the customer's needs before recommending it.",
            "Test ‘Can you deliver tomorrow?’ separately. If your policy does not confirm a delivery date, the assistant should explain the published delivery rules and offer the configured contact path. A product recommendation must not invent stock availability or promise an unverified arrival date.",
        ]},
        {"heading": "Service demonstration: qualify an enquiry", "paragraphs": [
            "Fictional service: a design studio offers website consultations, with final prices provided after reviewing scope. A visitor asks, ‘How much is a new website?’ A useful conversation asks about the work needed and explains the quote process instead of inventing a fixed price.",
            "Configure the details needed for follow-up and explain what happens next. A request for a consultation is not a confirmed booking unless a working booking integration actually confirms it. Test the handoff using a contact route your team monitors.",
        ]},
        {"heading": "Multi-branch demonstration: identify the location", "paragraphs": [
            "Fictional business: one branch opens on Sundays and another does not. When a visitor asks about Sunday opening, the assistant should identify the branch before answering from its supplied hours.",
            "Check ambiguous location names, temporary opening changes and enquiries outside the supplied service area. Maintain branch-specific facts so a visitor receives the policy for the location they need.",
        ]},
        {"heading": "Test before embedding on your website", "paragraphs": [
            "Use the widget section to test a known fact, missing information, an out-of-scope request and a request needing your team. Compare answers with your source material. Check the welcome message, brand colours, mobile layout and contact links.",
            "Configure the approved website origin and use the workspace's generated embed instructions. Test on the actual website before launch. Knowledge configuration does not automatically connect payments, inventory or booking systems; optional WhatsApp needs its own provider setup.",
        ]},
        {"heading": "Review actual conversations after launch", "paragraphs": [
            "Review available conversation and enquiry records in your authorised workspace. Look for unanswered questions, unclear next steps and outdated facts, then update the relevant business information and retest.",
            "Start with what you can observe. These demonstrations are acceptance criteria, not evidence of increased sales. Publish customer stories or reviews only when they exist and you have permission to use them.",
        ]},
    ],
    "steps": [
        {"title": "Prepare", "description": "Collect accurate business facts and decide which enquiries require human follow-up."},
        {"title": "Test", "description": "Try the fictional scenarios with your own facts and check the responses against them."},
        {"title": "Launch and review", "description": "Embed on an approved website, verify the contact path and maintain the knowledge as your business changes."},
    ],
    "caution": "AI responses can be incorrect. Arrange authorised workspace access and a working provider configuration before launch. The examples are fictional and do not represent existing customers, testimonials or guaranteed outcomes.",
}


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
