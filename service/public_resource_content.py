"""Public setup resources describing implemented capabilities and their boundaries."""
from service.public_site_content import Solution


RESOURCE_PAGES: dict[str, Solution] = {
    '/integrations': {
        'title': 'V7 Agent Integrations: Website, WhatsApp & API | Vertex Seven',
        'description': 'Understand V7 website chat, WhatsApp setup, API and MCP access, enquiry forms and native bookings. Check what needs configuration before connecting a business system.',
        'label': 'Integrations',
        'h1': 'Connect V7 to your business workflows',
        'intro': 'Start with the channel your customers use and the task you want to finish. V7 provides website chat, configurable enquiry flows and authorised management access. Each connection has its own setup and permissions; adding a website address does not connect every system your business uses.',
        'audience': 'For business owners checking integration requirements before setup or purchase.',
        'sections': [
            {'heading': 'Website chat and approved destinations', 'paragraphs': [
                'Add the workspace embed snippet to a website you control and approve its origin. Configure the widget name, branding, greeting and business knowledge. Test on the actual website, including a phone, before sharing it with visitors.',
                'Approved destinations let the assistant offer a button to a relevant product, checkout, booking or support page. A visitor clicking a button opens that destination; it does not prove that an order, payment or booking was completed there.',
            ]},
            {'heading': 'WhatsApp needs a provider connection', 'paragraphs': [
                'Website and WhatsApp agent software are included in the plans. WhatsApp also requires an eligible business number and a configured Meta or Twilio provider connection. Phone numbers, number rental and provider messaging charges are separate from the V7 subscription and prepaid AI credit.',
                'Confirm number eligibility and provider configuration during onboarding, then test inbound messages and replies. Website chat works independently of WhatsApp. A plan purchase alone does not finish provider setup.',
            ]},
            {'heading': 'Enquiries and V7-native consultation bookings', 'paragraphs': [
                'When enabled by the business, the assistant can open quote, callback or consultation forms. A customer must submit the form successfully to create a request. Consultation slots come from the business configuration; a confirmed appointment requires a successful slot submission.',
                'V7-native booking management can be enabled so customers use their private booking-management link to cancel or move an eligible consultation to an available configured slot. This changes the V7 booking, not an appointment in an external calendar. Keep the private link private and provide a staff contact for exceptions.',
            ]},
            {'heading': 'API and MCP management access', 'paragraphs': [
                'Authorised API and MCP clients can access the business records and operations their account is permitted to use. MCP exposes defined tools for reading business information and selected catalogue or offer updates. Write operations require write permission and the relevant current record revision.',
                'Management access is separate from customer-facing chat. A business owner connecting a management client does not give anonymous visitors access to private orders, account details or administrative tools. Review the actual permissions and available operations in your workspace.',
            ]},
            {'heading': 'External orders, refunds and calendars', 'paragraphs': [
                'If you need live order lookup, a refund or a change in an external booking system, specify the system and required operation before depending on it. Public website import supplies information; it does not authenticate a customer or grant access to private records.',
                'Ask which connector is implemented, which identity checks apply and how success or failure is reported. V7 chat does not currently complete payments, refunds, order changes or external calendar changes. Use an approved website destination or staff handoff for those tasks.',
            ]},
        ],
        'steps': [
            {'title': 'Name the task', 'description': 'Identify the channel, destination system and precise information or change required.'},
            {'title': 'Confirm access', 'description': 'Check the implemented connection, account permissions and customer verification requirements.'},
            {'title': 'Test the result', 'description': 'Verify a successful request, an unavailable option and a provider failure in the connected workflow.'},
        ],
        'caution': 'Integration availability depends on configuration and permissions. A link, saved business record or imported page is not evidence of a live connection to another service. Confirm required operations before purchasing or publishing.',
    },
    '/guides/business-knowledge': {
        'title': 'Business Knowledge & Website Import Guide | Vertex Seven',
        'description': 'Prepare V7 agent knowledge from products, services, FAQs and public website pages. Learn import limits, refresh steps, conversation memory controls and practical checks.',
        'label': 'Business knowledge guide',
        'h1': 'Give your AI agent accurate business knowledge',
        'intro': 'Useful answers begin with clear source information. Put the facts that determine a customer decision into managed business records, then use public website imports to add supporting detail. Review the resulting answers whenever your prices, services or policies change.',
        'audience': 'For owners and authorised staff preparing and maintaining a V7 business workspace.',
        'sections': [
            {'heading': 'Start with the facts customers need', 'paragraphs': [
                'Add products or services with clear names, descriptions and prices where applicable. Include differences between options, availability information, locations or service areas, opening hours, delivery rules and contact paths. Explain when a price is fixed and when a customer needs a quote.',
                'Use managed FAQs and business rules for important conditions and exceptions. Keep the agent tone and sales goals separate from factual promises. A friendly style must not introduce an unapproved discount, guarantee or service.',
            ]},
            {'heading': 'Import relevant public website pages', 'paragraphs': [
                'Save your business website as a public HTTPS address in the business profile. The website import can collect up to 20 public pages from that configured host, within its content limits. Private accounts, local network addresses and pages behind sign-in are not sources for this import.',
                'The importer extracts page text; it does not automatically connect your shop database, authenticate customers or read private orders. Relevant excerpts supplement managed business knowledge. It is a bounded import rather than continuous synchronisation of the whole website.',
            ]},
            {'heading': 'Review sources and refresh changes', 'paragraphs': [
                'Check the imported pages and the answers they support. Remove or correct stale information at its source, keep important prices and policies in the management screens, and refresh the website import after publishing relevant website changes.',
                'If two sources disagree, correct the conflict instead of expecting the assistant to guess. Test a clear factual question, a policy exception and something your information does not answer. The response should distinguish the supplied facts from missing details and offer a suitable contact path.',
            ]},
            {'heading': 'Use conversation memory for follow-ups', 'paragraphs': [
                'Conversation memory helps the assistant use earlier messages in the same session. The API settings provide controls for enabling memory, history message count, context budget and memory duration. These settings bound what earlier context is available; they are not permanent customer identity or a substitute for managed company knowledge.',
                'Including more previous text can increase model input cost. Longer replies, the selected model and additional calls also affect usage. Review the usage ledger with realistic conversations before increasing context limits. Changing active memory duration does not delete separately retained conversation or audit records.',
            ]},
            {'heading': 'Keep a small launch checklist', 'paragraphs': [
                'Ask what the business sells, compare two real offerings, ask a follow-up and test a missing fact. Define a harmless preference in one conversation and ask about it later in the same session. Start another session to check that the previous visitor’s details do not appear.',
                'Open an approved website button and submit an enabled enquiry form yourself. Confirm the destination and the recorded outcome. Repeat the same checks after changing knowledge, the model or an integration, and have your team review important replies.',
            ]},
        ],
        'steps': [
            {'title': 'Prepare managed facts', 'description': 'Add current offerings, prices, FAQs, policies, locations and contact paths.'},
            {'title': 'Import and review', 'description': 'Import your public HTTPS website and inspect the supporting information.'},
            {'title': 'Refresh and retest', 'description': 'Update changed facts, refresh relevant pages and rerun realistic customer questions.'},
        ],
        'caution': 'AI answers can be wrong even when source information is available. Keep private customer data out of public website content and involve your team when an enquiry needs verification or judgement.',
    },
    '/security': {
        'title': 'V7 Access, Conversation Memory & Data Handling | Vertex Seven',
        'description': 'Understand V7 business account permissions, tenant boundaries, session memory, provider processing and retention responsibilities before launching your website agent.',
        'label': 'Security and data handling',
        'h1': 'Understand access and data handling in V7',
        'intro': 'A customer conversation, a business workspace and a management integration have different access needs. This overview explains the implemented boundaries and the questions your business should resolve before launch. It complements the privacy notice and does not replace your business’s own policies.',
        'audience': 'For business owners reviewing how customer information and management access are used.',
        'sections': [
            {'heading': 'Business accounts and tenant boundaries', 'paragraphs': [
                'Workspace access requires authentication and an assigned business role. Business data and permitted operations are scoped to the company associated with that access. Owners and authorised staff use the management workspace; visitors use the public customer chat experience.',
                'Review team membership and permissions when people join, change responsibilities or leave. Administrative API and MCP access follows its own authorisation checks. Public chat does not inherit an owner’s management privileges.',
            ]},
            {'heading': 'Conversation context and stored records are different', 'paragraphs': [
                'Active conversation memory is scoped to the business and session. Its configurable history and duration limits control which earlier messages can be supplied for a follow-up. They do not establish a verified returning-customer identity.',
                'Conversation history, enquiries, usage information and security records may be retained separately for authorised review. Expiring active memory does not automatically erase those records or provider-held data. Confirm the retention process and the applicable privacy information before collecting customer details.',
            ]},
            {'heading': 'AI providers and connected services', 'paragraphs': [
                'When paid AI is enabled, the configured provider receives the input needed for that model request, which can include instructions, relevant business information and conversation context. Connected channel or payment providers process information needed for their respective services.',
                'Review the privacy notice for provider categories and check the actual configuration and processing arrangements with the operator. This page does not assert a specific processing location, certification, contractual guarantee or zero-retention setting.',
            ]},
            {'heading': 'Customer requests and private booking links', 'paragraphs': [
                'Enabled enquiry forms collect the details needed for the stated request. Opening a form does not submit it. Give customers a clear explanation of the purpose, the information required and how your team follows up.',
                'A private management link can authorise access to an eligible V7-native booking when that feature is enabled. Customers should not share that link publicly. Private account operations in other systems require their own implemented integration, verification and permission checks.',
            ]},
            {'heading': 'Before you publish', 'paragraphs': [
                'Check who can access the workspace, what the agent is allowed to do, which providers are enabled and what personal information your forms request. Confirm the controller and privacy contact, the purposes for processing and the retention process with the operator.',
                'Use the Privacy and Cookies links for the platform notices. Each business remains responsible for its own customer-facing information and processing decisions. Contact the business handling the conversation for a request about its customer records; contact Vertex Seven about platform account questions.',
            ]},
        ],
        'steps': [
            {'title': 'Review access', 'description': 'Check business roles, team membership and integration permissions.'},
            {'title': 'Map the information', 'description': 'Identify what conversations, forms and connected providers need to process.'},
            {'title': 'Confirm the process', 'description': 'Agree privacy information, retention and the route for customer requests before launch.'},
        ],
        'caution': 'This is a product overview, not a security certification or a guarantee of regulatory compliance. Ask for verified contractual and operational details where your business requires them.',
    },
    '/guides/business-use-cases': {
        'title': 'AI Chatbot Workflows for Retail & Services | Vertex Seven',
        'description': 'Plan practical V7 chatbot workflows for retail, service enquiries and multi-location businesses, with required knowledge, customer next steps and checks before launch.',
        'label': 'Business use cases',
        'h1': 'Choose a useful chatbot workflow for your business',
        'intro': 'Start with a recurring customer question and a clear next step your team can support. A retailer may need product comparisons; a service business may need a complete enquiry; a multi-location company may need accurate branch guidance. Configure the knowledge and action around that job.',
        'audience': 'Planning guidance for retail and service businesses. These are workflow suggestions, not customer case studies or measured results.',
        'sections': [
            {'heading': 'Retail: help a shopper compare options', 'paragraphs': [
                'Prepare current catalogue descriptions, meaningful differences, prices and delivery or collection policies. Ask customers about the intended use and relevant preferences, then help them compare suitable offerings using those supplied facts.',
                'Offer an approved product or checkout destination for the next step. Confirm that the selected page belongs to the intended item. A website import or saved stock field is not proof of live inventory, a reserved item or a completed order.',
            ]},
            {'heading': 'Services: gather a useful quote or callback request', 'paragraphs': [
                'Define the service scope, areas covered, pricing basis and the details staff need before following up. Explain which work has a published price and which requires assessment. Configure a short set of useful questions rather than requesting unnecessary personal information.',
                'Enable the appropriate enquiry flow and check the submitted request in the workspace. Make clear that a quote request is not an accepted quotation or a commitment to perform the work. Assign a team contact and a realistic follow-up process.',
            ]},
            {'heading': 'Consultations: guide an eligible appointment request', 'paragraphs': [
                'Configure the consultation slots and explain what the appointment covers. Test an available slot, one that has already been taken and an incomplete form. Only report confirmation after a successful submission.',
                'If native booking management is enabled, verify the private management link and the available rescheduling or cancellation options. A V7 consultation is separate from an appointment in another calendar unless an actual integration connects them.',
            ]},
            {'heading': 'Multiple locations: point customers to the right branch', 'paragraphs': [
                'Keep branch names, opening hours, contact paths and applicable delivery or service areas current. Distinguish a physical location from a service area, and state when a rule applies only to one branch.',
                'Test a customer who names a branch, one who provides only an area and one outside your coverage. The assistant should ask for the missing detail or use the configured contact route instead of inventing a location or promising service.',
            ]},
            {'heading': 'Measure completion and review failures', 'paragraphs': [
                'Choose an outcome you can verify: opening the correct product page, receiving a complete enquiry or confirming an eligible native booking. Review the conversation, recorded request and usage cost together. A button click is evidence of navigation, not a sale.',
                'Keep failed questions and incomplete handoffs in a short review list. Correct the relevant source or workflow, then repeat the check. Expand to another use case once your team can maintain the first one reliably.',
            ]},
        ],
        'steps': [
            {'title': 'Choose one job', 'description': 'Pick a recurring enquiry with a clear customer and team outcome.'},
            {'title': 'Configure the facts and action', 'description': 'Provide the relevant knowledge and enable only the next steps your team supports.'},
            {'title': 'Verify and improve', 'description': 'Review completed requests, incorrect answers and processing costs before expanding.'},
        ],
        'caution': 'Results depend on your information, configuration and team follow-up. V7 does not guarantee sales, staff savings or successful outcomes, and additional business-system operations need an implemented connection.',
    },
}
