"""Public buying questions built from the same price catalogue as checkout."""
from service.public_brand_content import _plan_prices, _prepaid_processing


def public_faq():
    sections = [
        ("What is V7 Agents and who provides it?", "V7 Agents is the configurable AI sales assistant platform provided by Vertex Seven. Vertex Seven is the brand; V7 Agents is the product. Our official website is vertex-seven.com. We operate online and serve businesses across the United Kingdom without in-person customer appointments."),
        ("Which businesses can use V7 Agents?", "Retailers, online stores, service businesses and multi-branch companies can configure V7 with their own products or services, prices, FAQs, policies, opening hours and contact paths. A service business can explain its quote process; a retailer can help visitors compare supplied products. Suitability depends on the knowledge and integrations your business configures."),
        ("How much does V7 Agents cost?", _plan_prices() + ". The subscription pays for the platform and the setup fee is separate from recurring monthly billing. Review the homepage comparison and final checkout before purchasing."),
        ("Are AI tokens included in the subscription?", _prepaid_processing() + " Subscription payments and prepaid usage credit are separate. Customers choose their supported model and purchase processing credit through their workspace."),
        ("How many messages can my AI credit cover?", "There is no fixed message allowance. The cost depends on the selected model, input tokens, output tokens and applicable cached-token pricing. Longer context or responses can use more credit. Your authorised workspace shows available models, pricing, usage history and charges; a message count alone does not determine the bill."),
        ("What happens when prepaid credit runs out?", "Chargeable model requests pause when available credit cannot safely cover the next request. Saved business knowledge remains available. Business owners can buy another one-time top-up. No automatic usage overages or recharges are enabled."),
        ("Does WhatsApp include a phone number and Meta messaging fees?", "The current plans include WhatsApp agent software, but phone numbers are not supplied. You need a suitable business number and a configured WhatsApp provider connection. Number rental, Meta or provider messaging fees and prepaid AI processing are separate costs. Website embedding does not automatically activate WhatsApp."),
        ("Can I customise the website chat widget?", "Yes. The website widget section combines testing and customisation. Configure the welcome message, supported styles, colours, branding and conversation tone, then use the generated embed instructions on your approved website. Test the live widget on mobile as well as desktop before publishing."),
        ("Will the assistant book appointments or take payments automatically?", "Knowledge configuration alone does not connect booking, checkout, stock or payment systems. Those actions need the relevant working integration. A consultation enquiry is not a confirmed booking. Configure a contact path your team monitors for human follow-up."),
        ("Are AI replies always accurate, and is 24/7 uptime guaranteed?", "AI replies can be incorrect. Maintain current business facts and test known, missing and out-of-scope questions. Replies depend on provider configuration, available credit and service availability; this website does not promise uninterrupted uptime or guaranteed sales results."),
    ]
    return {
        "title": "V7 Agents FAQs: Pricing, AI Credit & WhatsApp | Vertex Seven",
        "description": "Answers about Vertex Seven's V7 Agents: monthly pricing, separate AI tokens, model choice, WhatsApp fees, website embedding and business customisation.",
        "label": "V7 Agents FAQs", "h1": "V7 Agents: questions before you get started",
        "intro": "Clear answers about Vertex Seven's website sales assistant, what you pay for and what your business needs to configure.",
        "audience": "For UK businesses comparing website chat assistants and preparing their first agent.",
        "sections": [{"heading": question, "paragraphs": [answer]} for question, answer in sections],
        "steps": [
            {"title": "Compare", "description": "Review the platform subscription, setup fee and separate provider costs."},
            {"title": "Prepare", "description": "Collect current business knowledge and a monitored human contact path."},
            {"title": "Test", "description": "Check the chosen model, credit balance, widget and integrations before launch."},
        ],
        "caution": "These answers describe the public platform. Your workspace and checkout show the configuration and prices available to your business. Examples are not customer reviews or promised results.",
    }
