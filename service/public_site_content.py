"""Public product explanations, independent of tenant records and settings."""

from __future__ import annotations

from typing import TypedDict


class SolutionSection(TypedDict):
    heading: str
    paragraphs: list[str]


class SolutionStep(TypedDict):
    title: str
    description: str


class Solution(TypedDict):
    title: str
    description: str
    label: str
    h1: str
    intro: str
    audience: str
    sections: list[SolutionSection]
    steps: list[SolutionStep]
    caution: str


SOLUTIONS: dict[str, Solution] = {
    "website-chatbot": {
        "title": "Website Chatbot for Business | Vertex Seven",
        "description": "Add a website chatbot with your business knowledge, branding and contact paths. V7 Agents helps visitors explore products, policies and their next step.",
        "label": "Website chatbot",
        "h1": "A website chatbot built around your business",
        "intro": "A visitor should not need to search several pages to ask a straightforward question. V7 Agents brings your catalog, FAQs, branch details and delivery information into website chat. Customers can describe what they need, ask follow-up questions and find a practical next step, while your team manages the information behind the answers.",
        "audience": "For businesses that want useful conversations on their existing website.",
        "sections": [
            {"heading": "Help visitors navigate real business information", "paragraphs": [
                "Use a website chatbot to support the questions customers already ask: which product fits their needs, when a branch opens, whether delivery covers their area, or how to contact the team. V7 uses the information configured for your company. Accurate product descriptions, current prices and clear policies give the assistant a more useful foundation than a welcome message alone.",
            ]},
            {"heading": "Keep your website and your brand", "paragraphs": [
                "Your workspace provides an embed snippet for an approved website origin. Choose the assistant name, greeting, logo, layout and colours to suit your site. The widget offers a compact entry point for the conversation, with a customer chat experience that adapts to smaller screens. Your website remains the place to browse, compare and buy; chat helps explain what visitors find there.",
            ]},
            {"heading": "Give your team a useful next step", "paragraphs": [
                "Set a primary conversation goal and the contact information your business can fulfil. Where enabled, customer actions can collect a quote or callback request, or offer configured consultation slots. Review retained conversations and leads in the company workspace. That context helps your people continue an enquiry rather than asking the customer to start again, but follow-up still needs a responsible team member.",
            ]},
        ],
        "steps": [
            {"title": "Prepare the answers", "description": "Add your business profile, catalog, FAQs, locations and policies. Decide which questions the assistant should pass to your team."},
            {"title": "Test the experience", "description": "Try real customer questions in the workspace, including missing information and unusual requests. Refine your knowledge and greeting before launch."},
            {"title": "Embed and maintain", "description": "Add the supplied snippet to your approved website, check it on a phone, and update business information when products or policies change."},
        ],
        "caution": "AI responses can be incorrect. Website chat needs a configured company and a working deployment; it does not automatically connect to every shop system or replace staff decisions. Keep the assistant's knowledge current and provide a clear human contact path for requests it cannot resolve.",
    },
    "ai-chatbot-software": {
        "title": "AI Chatbot Software for Businesses | Vertex Seven",
        "description": "Configure V7 AI chatbot software with your catalog, FAQs, tone and sales playbook. Manage knowledge, test replies and review conversations in one workspace.",
        "label": "AI chatbot software",
        "h1": "AI chatbot software your business can tailor",
        "intro": "A useful assistant needs more than a general instruction to be helpful. V7 Agents is AI chatbot software with a business workspace for the information, conversation goals and presentation your company controls. Configure products or services, shape the tone, test questions and review customer conversations as your business changes.",
        "audience": "For owners and teams who need to manage an assistant without editing shared platform code.",
        "sections": [
            {"heading": "Separate business facts from conversation style", "paragraphs": [
                "The catalog, FAQs, locations and delivery policies provide customer-facing facts. The sales playbook describes your business model, ideal customer, fulfilment approach and primary goal. Response guidance and tone influence how the assistant presents that information. Keeping those responsibilities clear makes it easier to correct an answer: update an inaccurate fact, or refine the wording guidance if the facts are right but the response is unsuitable.",
            ]},
            {"heading": "Work from a managed company workspace", "paragraphs": [
                "Business owners manage their own company's setup through authenticated screens. Platform administrators can onboard companies and configure platform integrations. V7 keeps company information behind tenant boundaries, so adding another business does not mean copying its catalog into your assistant. The workspace also brings together widget appearance, customer actions, conversation review and usage information, subject to the account's permissions.",
            ]},
            {"heading": "Evaluate replies before publishing changes", "paragraphs": [
                "Use the test conversation alongside the widget settings to check both appearance and answers. Ask about known products, ask a question your knowledge does not cover, and try a request that needs a person. The platform provides controls for response length and supported model parameters, while business facts and safety rules remain required. Model behaviour and availability depend on the deployment's configured AI provider.",
            ]},
        ],
        "steps": [
            {"title": "Define the business", "description": "Describe what you sell, who you serve and what a useful customer outcome looks like. Add accurate customer-facing information."},
            {"title": "Set the boundaries", "description": "Choose your conversation goal and handoff message. Enable only quote, callback or consultation actions your team can fulfil."},
            {"title": "Review and refine", "description": "Test a repeatable set of customer enquiries, publish your website widget and review retained conversations for gaps in the setup."},
        ],
        "caution": "AI chatbot software is not a guarantee of correct answers or higher sales. V7 requires onboarding and provider configuration; optional WhatsApp requires a separate configured connection. People remain responsible for maintaining business facts, checking important replies and handling commitments that need human approval.",
    },
    "sales-chatbot": {
        "title": "Sales Chatbot with Your Business Playbook | Vertex Seven",
        "description": "Give your sales chatbot a goal, product knowledge and qualification questions. V7 supports discovery, quotes, callbacks and team follow-up when configured.",
        "label": "Sales chatbot",
        "h1": "A sales chatbot with a practical next step",
        "intro": "Not every sales enquiry starts with a product name. A customer may have a budget, a problem to solve or a project that needs a conversation. V7 Agents uses your business knowledge and sales playbook to support discovery, explain relevant options and point customers toward an action your company can actually fulfil.",
        "audience": "For product sellers and service businesses with different sales journeys.",
        "sections": [
            {"heading": "Start with the customer and the offering", "paragraphs": [
                "Configure whether your business offers products, services or both. Describe your business focus, customer type and ideal customer so the assistant has context for the enquiry. Your catalog supplies the details behind product guidance; the playbook supplies qualification questions and value propositions. Those inputs let a sales chatbot ask a relevant next question instead of applying the same pitch to every visitor.",
            ]},
            {"heading": "Choose a goal that matches your sales process", "paragraphs": [
                "Some businesses need a purchase enquiry, while others need a quote request or consultation. V7 supports playbook goals such as driving sales, capturing leads, answering questions and requesting quotes. Configure fulfilment context for delivery, collection, on-site or remote work where appropriate. A service business can focus on understanding requirements; a retailer can focus on product details and the customer's preferred option.",
            ]},
            {"heading": "Make the handoff deliberate", "paragraphs": [
                "Set a handoff message and clear contact paths for larger orders, custom work or questions that need staff judgement. Quote and callback requests are available when the company enables those actions. Consultation times must be configured, and a slot is confirmed only after a successful customer submission. The workspace lets your team review requests and retained conversation context before following up.",
            ]},
        ],
        "steps": [
            {"title": "Map the enquiry", "description": "List the information your sales team normally needs, such as intended use, project scope or location. Choose a small set of qualification questions."},
            {"title": "Supply the facts", "description": "Keep descriptions, pricing and delivery policies current. Explain where prices are fixed and where the customer must request a quote."},
            {"title": "Test the next step", "description": "Check a simple enquiry, a complex request and an unavailable option. Confirm that the assistant directs each to an appropriate outcome."},
        ],
        "caution": "A sales chatbot should not invent discounts, availability, guaranteed delivery or commitments. AI can misunderstand a request. Review the setup and involve your team where approval is needed. V7 supports sales conversations and recorded requests; it does not promise conversion results or automate every transaction.",
    },
    "customer-support-chatbot": {
        "title": "Customer Support Chatbot for FAQs | Vertex Seven",
        "description": "Help customers find FAQs, opening hours, delivery policies and contact paths. Configure a V7 customer support chatbot with clear limits and team handoff.",
        "label": "Customer support chatbot",
        "h1": "A customer support chatbot for everyday enquiries",
        "intro": "Customers often need the same practical information before or after they choose a product: opening hours, delivery areas, collection arrangements or how to reach the right person. V7 Agents can use your FAQs and business policies to support those everyday enquiries, with a clear contact path when the answer needs your team.",
        "audience": "For businesses with recurring customer questions and a team handling exceptions.",
        "sections": [
            {"heading": "Make common answers easier to find", "paragraphs": [
                "Add the questions customers ask most often and the policies that answer them. Branch records cover locations and hours; delivery information explains the areas and rules your company has configured. A customer support chatbot can bring these details into the conversation, rather than expecting someone to find the right footer link. Write policies in plain language, including any conditions that change the answer.",
            ]},
            {"heading": "Use website knowledge with care", "paragraphs": [
                "The workspace can import up to six public pages from the HTTPS website saved in your business profile. Imported excerpts can supplement structured information for questions it does not cover. This is a bounded import, not continuous synchronisation of an entire website. Review the source pages, refresh the import when they change, and keep important prices, rules and FAQs in the relevant management screens.",
            ]},
            {"heading": "Recognise when support needs a person", "paragraphs": [
                "Provide contact details and a handoff message for complaints, unusual requests or missing information. Your team can review retained conversations and customer requests in the company workspace. Chat should not imply that it has checked a private order or processed a refund unless a real configured integration provides that capability. For account-specific matters, direct the customer to the support process your business already uses.",
            ]},
        ],
        "steps": [
            {"title": "Collect repeat questions", "description": "Start with the enquiries your team answers regularly. Include policy conditions, exceptions and the right contact details."},
            {"title": "Check the limits", "description": "Test an answer in the FAQ, an answer in public website information and a request involving private order details. Verify the handoff is clear."},
            {"title": "Maintain the knowledge", "description": "Update opening hours and policies when they change. Review conversation gaps and add useful, accurate answers over time."},
        ],
        "caution": "AI replies can be wrong, and missing business information can lead to an incomplete answer. V7's FAQ and policy assistance is not an automatic helpdesk, refund processor or order lookup. Keep human support available for disputes, sensitive information and decisions that require verification.",
    },
    "ai-lead-generation-software": {
        "title": "AI Lead Generation Software for Enquiries | Vertex Seven",
        "description": "Use V7 AI lead generation software to support inbound enquiries, ask configured qualification questions and collect enabled quote or callback requests.",
        "label": "AI lead generation software",
        "h1": "AI lead generation software for inbound enquiries",
        "intro": "A visitor asking about a service is already expressing an interest. V7 Agents helps your business understand that enquiry and offer a suitable next step. Configure a lead-capture goal, qualification questions and customer actions so your team receives requests with context, rather than a disconnected list of contact details.",
        "audience": "For businesses that turn website enquiries into quotes, consultations or callbacks.",
        "sections": [
            {"heading": "Qualify through a useful conversation", "paragraphs": [
                "Describe the customer you serve and the information your team needs to decide what to do next. The sales playbook accepts a small set of qualification questions, business focus and value propositions. A project-based business might ask about the scope of the work; a local service might need a location. Use questions that help the customer and your team, rather than requesting unnecessary personal information.",
            ]},
            {"heading": "Capture a request your business can fulfil", "paragraphs": [
                "Enable quote requests, callbacks or consultations in customer action settings. These options are company-specific; your business decides which ones appear. Configured consultation slots can be offered, and a successful submission is needed before a time is confirmed. Requests without a selected time still need staff follow-up. A contact request should describe what will happen next so the visitor knows what to expect.",
            ]},
            {"heading": "Review the context before following up", "paragraphs": [
                "V7's workspace includes lead records, retained conversations and recent customer requests for your assigned company. Your team can review the enquiry before continuing the conversation through its normal channels. This is inbound AI lead generation software: it helps handle interest from people who reach your website. It does not scrape prospects, generate guaranteed buyers or automatically send an outbound campaign on your behalf.",
            ]},
        ],
        "steps": [
            {"title": "Define a useful lead", "description": "Choose the outcome you want to support and the minimum information required to follow up. Explain your service area or offering clearly."},
            {"title": "Configure the request", "description": "Set the playbook goal, qualification questions and enabled customer actions. Make the handoff wording match your actual team process."},
            {"title": "Check and follow up", "description": "Submit a test enquiry, confirm that the request and context are available, and give a team member responsibility for reviewing new requests."},
        ],
        "caution": "A recorded enquiry is not a guaranteed qualified lead or a sale. AI can misread requirements, and staff should verify details before making commitments. Collect only information needed for the request, explain your privacy practices and maintain a reliable follow-up process outside the chat.",
    },
    "conversational-ai-platform": {
        "title": "Conversational AI Platform for Business | Vertex Seven",
        "description": "Configure a V7 conversational AI platform for products, services and mixed businesses. Manage company knowledge, sales goals, branding and conversations.",
        "label": "Conversational AI platform",
        "h1": "A conversational AI platform for different business models",
        "intro": "A retailer, a consultancy and a business taking project enquiries need different conversations. V7 Agents separates the shared platform from each company's knowledge and playbook. The business configures what it offers, who it serves and how customers take the next step, while the platform provides the workspace and customer chat experience.",
        "audience": "For businesses and platform operators managing company-specific assistants.",
        "sections": [
            {"heading": "Describe how your company operates", "paragraphs": [
                "Choose products, services or a mixed offering, then set a business model and fulfilment approach. The playbook includes models such as retail, appointments, professional services, projects, subscriptions and hospitality. Those settings provide conversation context; they do not create a full reservation, property or subscription-management system. Your configured catalog, FAQs, locations and rules supply the facts needed for customer-facing answers.",
            ]},
            {"heading": "Manage companies through separate workspaces", "paragraphs": [
                "The conversational AI platform is multi-tenant. Business owners work with their own company's information, while platform administrators manage onboarding and platform configuration according to their permissions. Widget branding and conversation goals belong to the company, so one business can use a different tone and appearance from another. Customer messages must route to the correct company rather than a shared pool of business knowledge.",
            ]},
            {"heading": "Connect the channels your deployment supports", "paragraphs": [
                "Website chat can be embedded on approved business websites. WhatsApp is an optional channel that requires a configured Meta or Twilio connection and the appropriate service setup. Website chat works independently of that add-on. Model availability, API usage and integration settings also depend on the deployment. Start with the customer channel you can support well, then test additional connections before offering them publicly.",
            ]},
        ],
        "steps": [
            {"title": "Onboard the company", "description": "The platform operator sets up the workspace and access. Add the business profile and accurate customer-facing information for that company."},
            {"title": "Tailor the journey", "description": "Choose a primary goal and response guidance. Configure branding, contact paths and only the customer actions the business can fulfil."},
            {"title": "Test each channel", "description": "Check real questions, missing facts and handoff behaviour. Verify company routing and presentation before publishing an embed or connecting another channel."},
        ],
        "caution": "AI assistance does not make every business process automatic. Specialised workflows and private systems may need a separate integration. V7 cannot guarantee correct responses, so keep company information current, test changes and use your team for decisions or commitments requiring human judgement.",
    },
    "branded-website-chat-widget": {
        "title": "Branded Website Chat Widget | Vertex Seven",
        "description": "Style a branded website chat widget with your logo, colours, greeting and layout. Preview V7 chat, test answers and embed it on approved business websites.",
        "label": "Branded website chat widget",
        "h1": "A branded website chat widget that fits your site",
        "intro": "Chat should feel like part of your business website. V7 Agents lets you choose the name, welcome message, images, colours and layout customers see. Preview the appearance in your workspace, test the assistant's replies and publish the widget through the supplied website embed snippet when the experience is ready.",
        "audience": "For businesses that need their own visual identity and a manageable website integration.",
        "sections": [
            {"heading": "Control the identity customers see", "paragraphs": [
                "Set an assistant name, a short chat title and a welcome message that explains how it can help. Add a company logo or an assistant avatar using a supported image URL. Keep the greeting specific to your business: a service assistant might invite a project question, while a retailer might offer help finding a product. The name and message should match the role you want the assistant to perform.",
            ]},
            {"heading": "Choose a layout and an accessible palette", "paragraphs": [
                "The widget designer includes ten visual layouts and starting colour palettes. You can enter six-digit hex colours for the brand accent, chat background, header and fields, message text and customer bubble. Appearance previews show how those choices work together. The widget uses a readable light or dark text alternative when a selected colour has insufficient contrast, but you should still check the whole experience on your actual website.",
            ]},
            {"heading": "Bring appearance and answers together", "paragraphs": [
                "A branded website chat widget needs both a visual fit and useful information. The appearance preview is a sample; use Test conversation to check replies with saved business knowledge. The workspace also provides the embed snippet and approved origin settings for deployment. Customers can use text chat on supported browsers. Microphone input and reply playback depend on browser capabilities and permissions, so text must remain a usable option.",
            ]},
        ],
        "steps": [
            {"title": "Match the brand", "description": "Choose a style, name, greeting and logo. Start with a palette or enter your own colours, then save the widget appearance."},
            {"title": "Test in context", "description": "Check the saved customer widget and real answers. Review long messages, colour contrast and the smaller-screen layout before sharing it."},
            {"title": "Publish on your site", "description": "Configure your approved website origin and use the supplied embed snippet. Confirm the launcher does not cover important page controls on mobile."},
        ],
        "caution": "The widget preview does not prove that a live integration is configured. Website security policies, browser permissions and the platform deployment can affect availability. Keep branding assets reachable, test after site changes and maintain a clear contact path when chat or optional browser features are unavailable.",
    },
    "ai-product-recommendation-chatbot": {
        "title": "AI Product Recommendation Chatbot | Vertex Seven",
        "description": "Help customers explore your catalog with a V7 AI product recommendation chatbot. Use product facts, customer questions and clear delivery or team handoff paths.",
        "label": "AI product recommendation chatbot",
        "h1": "An AI product recommendation chatbot with your catalog",
        "intro": "Customers often know what they want to achieve before they know which product to choose. V7 Agents supports a conversation about those needs using the catalog and business information you provide. The assistant can help visitors explore relevant options, ask a useful follow-up question and understand what to do next.",
        "audience": "For retailers and product businesses helping shoppers compare suitable options.",
        "sections": [
            {"heading": "Build recommendations on product facts", "paragraphs": [
                "Give the assistant clear product names, categories, descriptions, prices and stock information. Explain the differences a customer would need to compare, such as intended use, dimensions or included features. An AI product recommendation chatbot is more useful when it can work from meaningful catalog details. Keep those records current rather than expecting AI to know your stock or independently verify a supplier's latest specifications.",
            ]},
            {"heading": "Use the conversation to understand the need", "paragraphs": [
                "A broad enquiry can lead to a clarifying question about the intended use, preferred option or other requirement. Your business focus and sales playbook provide context for the guidance. For example, a fictional lamp store might ask whether the customer wants warm evening light or brighter light for work. The aim is to make the choice easier to discuss, without treating an AI suggestion as a guaranteed best fit.",
            ]},
            {"heading": "Connect product discovery to the next step", "paragraphs": [
                "A product conversation may also need delivery details, collection information or help from a person. Configure your company's policies and contact paths so the assistant can explain those next steps. Larger orders or requirements the catalog does not cover can move to a team handoff. Your workspace provides retained conversation and lead context for review, but a recommendation does not itself complete a purchase or reserve stock.",
            ]},
        ],
        "steps": [
            {"title": "Improve the catalog", "description": "Add the features customers use to choose between products. Check product links, prices and availability before making them customer-facing."},
            {"title": "Test different needs", "description": "Try a specific product request, a broad description of a need and a request your catalog cannot satisfy. Look for useful questions and honest limits."},
            {"title": "Keep guidance current", "description": "Update discontinued items and changed policies. Review retained enquiries to find missing product information, then retest the relevant questions."},
        ],
        "caution": "AI suggestions can be incomplete or incorrect. Customers should confirm important specifications and suitability before buying, especially where professional advice is required. Catalog data needs maintenance or a separately configured integration; V7 does not automatically synchronise every inventory system or guarantee recommendation accuracy.",
    },
}
