"""Public buying guidance grounded in V7's configured product and price catalogue."""
from service.public_brand_content import _prepaid_processing
from service.public_site_content import Solution


def public_pricing() -> Solution:
    return {
        'title': 'V7 Agents Pricing: Plans, Setup & AI Costs | Vertex Seven',
        'description': 'Compare V7 Agents Starter, Business and Scale plans, one-time setup fees, separate AI credit and WhatsApp costs. Choose a website chatbot plan for your business.',
        'label': 'Pricing',
        'h1': 'V7 Agents pricing, with every cost explained',
        'intro': 'Compare the platform subscription, one-time setup and separate AI processing costs before choosing a plan. Every plan includes website and WhatsApp agent software; the differences are locations, team size and service level.',
        'audience': 'GBP pricing for businesses choosing an AI sales assistant. No AI credit is included in the subscription.',
        'sections': [
            {'heading': 'Which plan should you choose?', 'paragraphs': [
                'Start with the comparison above: count the branches or service areas you need to configure and the staff who need workspace access, then compare onboarding and analytics. The business owner is separate from the staff allowance. A higher plan does not automatically connect a shop, booking system or other external service.',
                'Plan labels such as Basic and Advanced describe the service level. Access to business data and tools still follows the account permissions and integrations enabled for your workspace.',
            ]},
            {'heading': 'How much does AI processing cost?', 'paragraphs': [
                _prepaid_processing(),
                'There is no guaranteed number of messages per top-up. Input includes business instructions and conversation context; output is the generated reply. A message may require more than one model call. Longer conversations, longer replies and the selected model change the cost. Applicable cached-token pricing is recorded separately from ordinary input pricing.',
                'Your workspace shows available models, their prices, the usage ledger and the remaining balance. Paid model requests pause when credit cannot safely cover the next request or its cost is unknown. Saved business knowledge remains available. Purchased credit carries forward; there are no automatic recharges or usage overages.',
            ]},
            {'heading': 'What is separate from the monthly plan?', 'paragraphs': [
                'Setup is a one-time payment shown separately from the monthly subscription. AI processing is funded separately with prepaid credit. WhatsApp needs a suitable business number and a configured provider connection; number rental and Meta or provider messaging fees are additional costs outside V7 credit.',
                'If you need access to customer orders, stock, a payment provider or an external booking system, discuss the specific integration and permissions before buying. Importing public website information does not connect private customer records or enable every business action.',
            ]},
            {'heading': 'Can you change or cancel a subscription?', 'paragraphs': [
                'The business owner can review eligible plan changes and cancellations in the Subscription section of the workspace. Stripe presents the final review. An eligible plan change may include a prorated charge or credit, which Stripe shows before confirmation.',
                'Cancellation stops renewal at the end of the current billing period. Opening the review does not cancel the plan; the owner must confirm in Stripe. Cancellation does not automatically refund earlier payments or prepaid AI credit. Existing invoices remain in payment history.',
            ]},
        ],
        'steps': [
            {'title': 'Compare the total', 'description': 'Include monthly subscription, setup, AI processing and any separate WhatsApp provider costs.'},
            {'title': 'Check the fit', 'description': 'Confirm your locations, staff access, business knowledge and required integrations.'},
            {'title': 'Review before paying', 'description': 'Your workspace and final Stripe checkout show the prices and terms that apply to your purchase.'},
        ],
        'caution': 'AI output can be incorrect. Plan prices do not guarantee a number of replies, a sales result or uninterrupted service. Keep business knowledge current and test your required workflows before launch.',
    }


BUYING_GUIDE: Solution = {
    'title': 'How to Choose a Website Chatbot: Buyer Checklist | Vertex Seven',
    'description': 'Compare website chatbots with a practical checklist for business knowledge, conversation memory, AI costs, integrations and handoff. Includes example test questions.',
    'label': 'Website chatbot buying guide',
    'h1': 'How to choose a website chatbot for your business',
    'intro': 'A useful comparison starts with your customer questions and the work your team needs to finish. Use this checklist to evaluate a website chatbot with your own business information, rather than judging only a polished demo.',
    'audience': 'For business owners comparing AI chatbots for retail, online stores and service enquiries. The example questions below are a test plan, not customer results.',
    'sections': [
        {'heading': '1. Pick one customer job to test', 'paragraphs': [
            'Choose a concrete starting point: helping a visitor compare products, explaining a delivery policy or gathering the details needed for a quote. Write down what a successful next step looks like and who in your team will handle it. Broad promises to automate everything are difficult to evaluate against real work.',
            'For a product comparison, provide the current catalogue, prices and important differences. For a service enquiry, provide eligibility, service areas, required details and the route to a human. Ask the provider to demonstrate the same job with your supplied information.',
        ]},
        {'heading': '2. Check both known and missing information', 'paragraphs': [
            'Prepare a question with a clear answer in your knowledge, one with an exception and one your source does not answer. For example: “What does this service include?”, “Does that apply outside your usual service area?” and “Can you guarantee availability tomorrow?” The assistant should distinguish a published fact from an unknown detail.',
            'For website imports, ask which pages are included, how updates are refreshed and what happens when a page conflicts with a managed policy. Public website retrieval does not prove access to private orders, live inventory or customer accounts. In V7, imported public pages supplement managed business knowledge and need review and refresh.',
        ]},
        {'heading': '3. Test follow-up questions in the same conversation', 'paragraphs': [
            'Try this sequence: “I need an option for a small team”; “My budget is lower than I first thought”; “Which of those fits that budget?” Check whether the assistant uses the earlier context and asks a useful question when a detail is missing. Also test a greeting and an unrelated question so ordinary conversation does not produce a random sales script.',
            'Check the boundary as well: start a new conversation and verify that another visitor does not receive the previous visitor’s details. Ask how history is retained, who can access it and whether returning-customer memory needs a verified identity. Remembering one session and identifying a returning customer are separate capabilities.',
        ]},
        {'heading': '4. Separate a suggested action from a completed action', 'paragraphs': [
            'Ask the chatbot to open a quote request, find an order or change a booking. Establish whether it offers a website button, opens a form or actually updates an authorised business system. The wording should match the result: opening a form is not submitting it, and a request is not a confirmed booking.',
            'For an action that changes data, test permissions, customer identity, confirmation, repeated clicks and provider failure. Get the integration requirements in writing before depending on order changes, refunds or other private account operations. V7 provides configured website destinations and enabled enquiry flows; further business-system access depends on the integration and permissions available.',
        ]},
        {'heading': '5. Compare the complete cost', 'paragraphs': [
            'Compare the subscription and setup separately from usage. Ask whether usage is billed by messages, conversations or model tokens, whether context counts, which model is used and whether one customer turn can trigger several paid calls. Ask for the exact behaviour when the budget runs out.',
            'For V7, AI processing uses separately purchased prepaid credit, with no fixed message cap and no automatic recharge. Website and WhatsApp share the credit balance. Phone numbers and WhatsApp provider fees are separate. Compare real conversations of different lengths rather than assuming that every message costs the same.',
        ]},
        {'heading': '6. Check the customer and team experience', 'paragraphs': [
            'Test the live widget on a phone and with a keyboard. Check that text remains readable, links have clear labels, buttons open the intended destination and error messages explain the next step. Verify that your team can update an answer without changing application code.',
            'Before launch, submit a test enquiry, find it in the workspace and have a team member complete the follow-up. Keep a short record of failed questions, fix the underlying knowledge or workflow and rerun the same sequence after a change. A successful demo is a starting point for this process, not proof of reliability in every conversation.',
        ]},
    ],
    'steps': [
        {'title': 'Bring your evidence', 'description': 'Use current prices, policies and realistic customer questions in every comparison.'},
        {'title': 'Run the same test', 'description': 'Include follow-ups, missing facts, budget limits and one required business action.'},
        {'title': 'Check the outcome', 'description': 'Review the answer, actual action, team handoff and usage cost together.'},
    ],
    'caution': 'This guide is published by Vertex Seven, the provider of V7 Agents. It describes evaluation questions and V7’s public capabilities, not an independent ranking of providers or a guarantee of customer outcomes.',
}
