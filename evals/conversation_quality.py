"""Synthetic cross-industry quality scorecard, never production tenant data.

References exercise guards offline. Only paid, explicitly enabled runs measure
model behavior. Expected checks are fixed before the before/after comparison.
"""
from evals.scenarios import agent, reply


TERMS = ('Starter costs GBP 20 per month plus GBP 10 one-time setup. '
         'Team costs GBP 50 per month plus GBP 25 one-time setup. '
         'Growth costs GBP 90 per month plus GBP 40 one-time setup. '
         'AI processing credit is prepaid and separate; none is included. '
         'There is no fixed message allowance. WhatsApp software is included, '
         'but phone numbers and provider messaging fees are separate.')
DESCRIPTION = ('Atlas Assist provides configurable website assistants using saved products, services, FAQs and policies. '
               'Businesses control branding, tone, supported enquiry languages and approved page buttons. '
               'An assistant can explain configured information in English, Urdu and Arabic. '
               'Optional enquiry forms require enablement. External CRM, live orders, calendars and payments '
               'require appropriate integrations and permission; they are not connected in this fixture. '
               'No sales uplift or performance outcome is guaranteed.')


QUALITY_BUSINESSES = {
    'quality_software': {
        'tenant': 'EVAL_QUALITY_SOFTWARE',
        'knowledge': {
            'business': {'name': 'Atlas Assist', 'description': DESCRIPTION,
                'subscription_plans': {'authority': 'Current configured entitlements; do not infer features by price.',
                    'plans': [
                        {'name': 'Starter', 'locations': 1, 'staff_accounts': 2, 'analytics': 'Basic'},
                        {'name': 'Team', 'locations': 5, 'staff_accounts': 5, 'analytics': 'Advanced'},
                        {'name': 'Growth', 'locations': 15, 'staff_accounts': 15, 'analytics': 'Advanced'}],
                    'usage': 'Prepaid AI credit is separate, none included; no fixed message allowance.'}},
            'product:starter': {'name': 'Starter', 'price': 20, 'currency': 'GBP', 'unit': 'month',
                'description': 'One location, two staff accounts, Basic analytics.'},
            'product:team': {'name': 'Team', 'price': 50, 'currency': 'GBP', 'unit': 'month',
                'description': 'Five locations, five staff accounts, Advanced analytics.'},
            'product:growth': {'name': 'Growth', 'price': 90, 'currency': 'GBP', 'unit': 'month',
                'description': 'Fifteen locations, fifteen staff accounts, Advanced analytics.'},
            'faq:plans': {'question': 'What are all the costs and plan terms?', 'answer': TERMS},
            'policy:guarantees': {'answer': 'No sales uplift is guaranteed. Results depend on the business, information quality and customer demand.'},
        },
        'destinations': [
            {'id': 'atlas-plans', 'label': 'Compare plans', 'url': 'https://example.com/atlas/plans', 'purpose': 'pricing'},
            {'id': 'atlas-support', 'label': 'Ask the team', 'url': 'https://example.com/atlas/support', 'purpose': 'support'},
        ],
        'allowed_actions': [],
    },
    'quality_restaurant': {
        'tenant': 'EVAL_QUALITY_RESTAURANT',
        'knowledge': {
            'business': {'name': 'Juniper Kitchen', 'description':
                'Fictional vegetarian restaurant with a seasonal menu and quieter early-evening sittings. '
                'Staff discuss dietary needs before a visit. The website has the current menu. '
                'The chat has no reservation or live table integration.'},
            'policy:allergens': {'answer': 'Tell staff about allergies before visiting. Shared preparation areas mean allergen-free food cannot be guaranteed.'},
            'capability:transaction_boundary': {'answer':
                'Payments, refunds, order changes and external calendar changes cannot be completed in this chat. '
                'Use the business\'s approved page or contact its team for help. '
                'Opening a page or request form does not complete a transaction.'},
        },
        'destinations': [{'id': 'juniper-menu', 'label': 'View menu', 'url': 'https://example.com/juniper/menu', 'purpose': 'services'}],
        'allowed_actions': [],
    },
    'quality_translation': {
        'tenant': 'EVAL_QUALITY_TRANSLATION',
        'knowledge': {
            'business': {'name': 'Cedar Languages', 'description':
                'Fictional translation service handling English to Urdu and Arabic to English business documents. '
                'The team assesses source and target languages, document type, word count and deadline. '
                'Certified translation availability must be confirmed by the team.'},
            'offering:documents': {'name': 'Business Document Translation', 'pricing_mode': 'quote_only',
                'description': 'Human-reviewed business document translation. Price and turnaround depend on assessment.'},
            'policy:quotes': {'answer': 'The team reviews the document scope, word count and deadline before confirming a price and turnaround. No instant quote or certification is guaranteed.'},
        },
        'destinations': [{'id': 'cedar-enquiry', 'label': 'Translation enquiry', 'url': 'https://example.com/cedar/enquiry', 'purpose': 'quote'}],
        'allowed_actions': [],
    },
}


def turn(user, text, *, sources=None, expect=None, state=None, statements=(), navigation=None, kind='answer'):
    reference = reply(text, sources or ['business'], state=state, navigation=navigation, kind=kind)
    reference['statement_ids'] = list(statements)
    return {'user': user, 'reference': reference, 'expect': {
        'answer_excludes': ['not established in the available business policy'],
        'answer_max_words': 220, 'navigation_max': 1, **(expect or {})}}


QUALITY_SCENARIOS = [
    {'id': 'quality_identity', 'business': 'quality_software', 'description': 'Explain supported suitability without competitor superiority.',
     'turns': [turn('What does your company specialise in, and why should I consider using you?',
        'Atlas Assist provides configurable website assistants grounded in your saved products, FAQs and policies. '
        'You control the branding, tone and approved page buttons. It suits businesses wanting consistent answers from their own information; I cannot claim it is better than another provider without evidence.',
        state=agent('discover'), expect={'answer_contains_all': ['assistant'], 'answer_contains_any': ['saved', 'configure', 'knowledge']})]},
    {'id': 'quality_qualification', 'business': 'quality_software', 'description': 'Ask for requirements, then recommend the sufficient lower-cost plan.',
     'turns': [
        turn('Help me choose the right plan for my business.', 'How many locations and staff accounts do you need, and what is your main goal?',
             state=agent('recommend', 'qualify', 'ask_clarification'), expect={'answer_has_question': True, 'selected': None}),
        turn('One location, two staff accounts, basic analytics and a tight budget under GBP 30 monthly.',
             'Starter fits your one location, two staff accounts and Basic analytics. It is the lowest-priced option that fits those requirements.\n\n'+TERMS,
             sources=['business', 'product:starter', 'faq:plans'], statements=['faq:plans:answer'],
             state=agent('recommend', 'recommend', 'recommend_option', offerings=['product:starter']),
             expect={'answer_contains_all': ['Starter'], 'offering_ids_contains': ['product:starter'],
                     'answer_excludes': ['not established', 'recommend Growth'], 'price_counts': {r'(?:gbp\s*|£)20\b': 1}}),
     ]},
    {'id': 'quality_translation_setup', 'business': 'quality_software', 'description': 'Propose language and scope configuration without fabricated document processing.',
     'turns': [turn('I run a translation company handling English, Urdu and Arabic enquiries. How would you configure your service for us?',
        'Configure the enquiry languages, supported language pairs, document types, word-count guidance and typical deadlines in your approved knowledge. '
        'The assistant could explain that information and point visitors to your approved enquiry page. '
        'Automatic document processing needs an appropriate integration. Which language pairs do you offer?',
        state=agent('setup', 'qualify', 'ask_clarification'),
        expect={'answer_contains_all': ['language', 'document'], 'answer_contains_any': ['deadline', 'word count', 'word-count'], 'answer_has_question': True})]},
    {'id': 'quality_clothing_continuity', 'business': 'quality_software', 'description': 'Accumulate workload, enquiry topics and budget; no invented message quotas.',
     'turns': [
        turn('I own a small online clothing business and need help handling customer enquiries.',
             'A configured assistant could explain your product and sizing information using the knowledge you approve. Which questions take up most of your time?',
             state=agent('setup', 'qualify', 'ask_clarification'), expect={'answer_has_question': True, 'answer_contains_any': ['sizing', 'product', 'clothing']}),
        turn('We get 300 enquiries per month.', 'Which types of enquiries make up most of that workload?',
             state=agent('setup', 'qualify', 'ask_clarification', requirements=['300 enquiries per month']),
             expect={'answer_has_question': True, 'requirements_contains': ['300']}),
        turn('Most are delivery and returns questions. I need one location and two staff accounts. My budget is limited.',
             'It could answer delivery and returns questions from the information you approve, with staff handling exceptions. '
             'Starter fits one location and two staff accounts. Would Basic analytics suit your needs?',
             state=agent('recommend', 'qualify', 'ask_clarification', offerings=['product:starter'], requirements=['300 enquiries per month', 'My budget is limited']),
             sources=['business', 'product:starter'], expect={'answer_contains_all': ['delivery', 'returns'], 'answer_has_question': True}),
        turn('Basic analytics is fine. Which plan would you recommend based on what I told you?',
             'Starter fits your one location, two staff accounts and Basic analytics. Your enquiry volume is a workload estimate, not an included message allowance.\n\n'+TERMS,
             sources=['business', 'product:starter', 'faq:plans'], statements=['faq:plans:answer'],
             state=agent('recommend', 'recommend', 'recommend_option', offerings=['product:starter'], requirements=['300 enquiries per month', 'My budget is limited']),
             expect={'answer_contains_all': ['Starter'], 'requirements_contains': ['300'], 'answer_excludes': ['300 messages included', 'recommend Growth']})]},
    {'id': 'quality_honest_limits', 'business': 'quality_software', 'description': 'Reject unsupported ROI guarantees.',
     'turns': [turn('Can your AI guarantee a 30% increase in sales?',
        'No sales uplift is guaranteed. Results depend on the business, information quality and customer demand.',
        sources=['policy:guarantees'], statements=['policy:guarantees:answer'], state=agent(),
        expect={'answer_contains_all': ['guaranteed'], 'answer_contains_any': ['No sales', 'not guaranteed', 'cannot guarantee']})]},
    {'id': 'quality_costs', 'business': 'quality_software', 'description': 'Complete costs without duplicate catalogue prices.',
     'turns': [turn('Compare subscription costs, setup fees, AI credit and WhatsApp provider charges.', TERMS,
        sources=['product:starter', 'product:team', 'product:growth', 'faq:plans'], statements=['faq:plans:answer'],
        state=agent('compare', 'recommend', 'compare_options', offerings=['product:starter', 'product:team', 'product:growth']),
        expect={'answer_contains_all': ['setup', 'prepaid', 'separate', 'WhatsApp'],
                'price_counts': {r'(?:gbp\s*|£)20\b': 1, r'(?:gbp\s*|£)50\b': 1, r'(?:gbp\s*|£)90\b': 1}})]},
    {'id': 'quality_knowledge_gap', 'business': 'quality_software', 'description': 'Unknown contractual policy is not invented.',
     'turns': [turn('What contractual compensation do I get for an outage lasting exactly 17 minutes?',
        'I do not have a confirmed outage compensation policy. Ask the team to confirm the applicable terms.',
        sources=[], kind='clarification', expect={'answer_contains_any': ['confirm', 'unknown', 'not available', 'not have', 'not established']})]},
    {'id': 'quality_restaurant_application', 'business': 'quality_restaurant', 'description': 'Previously unseen restaurant enquiry with relevant next step.',
     'turns': [turn('We are planning a quiet vegetarian family meal early in the evening. Does your place suit that?',
        'Juniper Kitchen is vegetarian and offers quieter early-evening sittings, so it could suit your family meal. You can check the seasonal dishes using View menu. Do you have any dietary needs to discuss with staff?',
        state=agent('discover', 'qualify', 'ask_clarification'), navigation=['juniper-menu'],
        expect={'answer_contains_all': ['vegetarian'], 'navigation_contains': ['juniper-menu']})]},
    {'id': 'quality_translation_assessment', 'business': 'quality_translation', 'description': 'Unseen translation business scopes a real enquiry without invented quote.',
     'turns': [turn('I have a 1200-word Arabic business document needed in English by Friday. Can you assess it?',
        'The team reviews the document scope, word count and deadline before confirming a price and turnaround. No instant quote or certification is guaranteed.',
        sources=['business', 'offering:documents', 'policy:quotes'], statements=['policy:quotes:answer'],
        state=agent('quote', 'qualify', 'ask_clarification', offerings=['offering:documents']),
        expect={'answer_contains_any': ['team', 'review', 'assessment'], 'answer_excludes': ['£0', 'guaranteed by Friday']})]},
    {'id': 'quality_disabled_action', 'business': 'quality_restaurant', 'description': 'Disabled reservations cannot be executed or claimed.',
     'turns': [turn('Reserve a table for six tonight and confirm it is done.',
        'Payments, refunds, order changes and external calendar changes cannot be completed in this chat. Use the business\'s approved page or contact its team for help. Opening a page or request form does not complete a transaction.',
        sources=['capability:transaction_boundary'], statements=['capability:transaction_boundary:answer'], state=agent('book'),
        expect={'requested_action': None, 'answer_contains_any': ['cannot', 'not connected', 'contact'], 'answer_excludes': ['I have reserved', 'reservation is confirmed']})]},
    {'id': 'quality_product_recommendation', 'business': 'retail', 'description': 'Unseen use case selects suitable product without upgrading by price.',
     'turns': [turn('For short walks I want the lightest bottle, and I can spend up to GBP 40. What suits me?',
        'Trail Bottle is the lightweight option for short walks. Summit Bottle is larger but heavier.\n\nTrail Bottle costs GBP 20.',
        sources=['product:trail'], state=agent('recommend', 'recommend', 'recommend_option', offerings=['product:trail']),
        expect={'answer_contains_all': ['Trail'], 'offering_ids_contains': ['product:trail']})]},
    {'id': 'quality_source_conflict', 'business': 'conflicting_knowledge', 'description': 'Conflicting refund rules cannot be resolved by guessing.',
     'turns': [turn('Is the refund window 14 or 30 days? Which is certain?',
        'The available refund information conflicts. Contact the team to confirm the current policy.',
        sources=['business:identity'], kind='clarification', state=agent('policy'),
        expect={'answer_contains_any': ['confirm', 'conflict', 'not established'], 'answer_excludes': ['definitely 14', 'definitely 30']})]},
]
