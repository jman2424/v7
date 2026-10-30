"""Business guidance must survive rendering without becoming policy boilerplate."""
import pytest

from tests.test_grounded_statements import run


BUSINESS = {'name': 'Atlas Assist', 'about':
    'Configurable website assistants answer questions from saved products and FAQs, '
    'with branded widgets and links to approved booking pages.'}


def test_verified_description_is_not_a_missing_policy(monkeypatch):
    text = ('Atlas Assist provides configurable website assistants grounded in your saved products and FAQs. '
            'Its branded widget can point visitors to approved booking pages.')
    answer, _, diagnostics, calls = run(monkeypatch, {'business': BUSINESS}, text=text,
        question='What does your company specialise in, and why should I consider it?',
        sources=['business'], intent='discover', ids=[])
    assert answer == text
    assert diagnostics['accepted'] and len(calls) == 1
    assert 'not established' not in answer


def test_oxford_comma_saved_policy_sources_are_description_not_policy_claims(monkeypatch):
    text = 'Atlas Assist uses saved products, services, FAQs, and policies to answer business questions.'
    answer, _, diagnostics, _ = run(monkeypatch, {'business': BUSINESS}, text=text,
        question='What do you specialise in?', sources=['business'], intent='discover', ids=[])
    assert answer == text and diagnostics['accepted']


def test_suitability_sentence_survives_a_price_in_the_same_paragraph(monkeypatch):
    terms = 'Starter costs GBP 20 per month. AI credit is separate.'
    facts = {'business': BUSINESS, 'product:starter': {'name': 'Starter', 'description': 'Two staff accounts.',
        'price': 20, 'currency': 'GBP', 'unit': 'month'}, 'faq:terms': {'answer': terms}}
    answer, _, diagnostics, _ = run(monkeypatch, facts,
        text='Starter fits your two staff accounts. It costs GBP 20 per month.',
        question='Which plan fits my two staff accounts?', sources=list(facts), intent='recommend',
        ids=['faq:terms:answer'])
    assert 'Starter fits your two staff accounts.' in answer
    assert terms in answer and answer.count('20') == 1 and diagnostics['accepted']


def test_customer_policy_topics_are_not_claims_about_our_policy(monkeypatch):
    text = ('For your online shop, a configured assistant could answer delivery and returns questions '
            'using the information you approve. Which enquiries take up most of your time?')
    knowledge = {'business': BUSINESS, 'faq:cost': {'question': 'How much does it cost?',
        'answer': 'Starter costs GBP 20 per month. AI credit is separate.'}}
    answer, _, diagnostics, calls = run(monkeypatch, knowledge, text=text,
        question='I run an online shop and spend too much time on delivery and returns questions. How could you help?',
        sources=['business'], intent='setup', ids=[])
    assert answer == text
    assert diagnostics['accepted'] and len(calls) == 1
    assert 'GBP 20' not in answer
    import json
    prompt = json.loads(calls[0]['messages'][1]['content'])
    assert 'faq:cost' not in prompt['knowledge']


def test_pricing_keeps_useful_qualification_and_does_not_repeat_prices(monkeypatch):
    policy = ('Starter costs GBP 20 per month plus GBP 10 setup. '
              'AI processing credit is separate and no usage credit is included.')
    knowledge = {'business': BUSINESS,
        'product:starter': {'name': 'Starter', 'price': 20, 'currency': 'GBP', 'unit': 'month'},
        'faq:pricing': {'question': 'What are the plan prices?', 'answer': policy}}
    answer, _, diagnostics, calls = run(monkeypatch, knowledge,
        question='Compare the plans and help me choose based on what I need.',
        text='Which team access and locations do you need?\n\n'+policy,
        sources=['business', 'product:starter', 'faq:pricing'], intent='compare',
        ids=['faq:pricing:answer'])
    assert diagnostics['accepted'] and len(calls) == 1
    assert 'Which team access and locations do you need?' in answer
    assert policy in answer
    assert answer.count('20') == 1
    assert 'GBP 10 setup' in answer


@pytest.mark.parametrize('policy', [
    'Starter costs GBP 25 per month.',
    'Starter Plus costs GBP 20 per month.',
    'Starter costs GBP 20 per year.',
    'Starter costs USD 20 per month.',
    'Starter costs GBP 20 setup.',
    'Starter costs GBP 10 per month plus GBP 20 setup.',
])
def test_distinct_prices_currencies_names_and_units_are_not_deduplicated(policy):
    from service.grounded_statements import _duplicate_price
    row = {'name': 'Starter', 'price': 20, 'currency': 'GBP', 'unit': 'month'}
    assert not _duplicate_price(row, {'faq:terms:answer': {'source_id': 'faq:terms', 'text': policy}},
                                ['faq:terms:answer'])


@pytest.mark.parametrize('claim', [
    'We answer returns questions. Refunds are accepted after any deadline.',
    'We answer delivery questions. Orders always arrive the next day.',
    'Our booking pages guarantee an appointment.',
    'We answer payment questions and charge no setup fees.',
])
def test_topic_normalisation_does_not_free_policy_or_financial_claims(monkeypatch, claim):
    policy = 'The team must confirm the applicable terms. Do not assume a refund or delivery deadline.'
    answer, _, diagnostics, _ = run(monkeypatch,
        {'business': BUSINESS, 'policy:terms': {'answer': policy}}, text=claim,
        question='How could your assistant help with delivery and refund terms for my business?', sources=['business', 'policy:terms'],
        intent='setup', ids=['policy:terms:answer'])
    assert answer == policy
    assert diagnostics['accepted']


def test_structured_offering_prices_cannot_be_swapped_in_model_prose(monkeypatch):
    knowledge = {'business': BUSINESS,
        'product:basic': {'name': 'Basic', 'price': 20, 'currency': 'GBP'},
        'product:plus': {'name': 'Plus', 'price': 50, 'currency': 'GBP'}}
    answer, _, diagnostics, _ = run(monkeypatch, knowledge, question='Compare Basic and Plus prices.',
        text='Basic costs GBP 50. Plus costs GBP 20.', sources=list(knowledge), intent='compare', ids=[])
    assert diagnostics['accepted']
    assert 'Basic: £20.00' in answer and 'Plus: £50.00' in answer
    assert 'Basic costs GBP 50' not in answer


def test_customer_percentage_in_denied_guarantee_uses_complete_verified_policy(monkeypatch):
    policy = 'No sales uplift is guaranteed. Results depend on the business and customer demand.'
    answer, _, diagnostics, calls = run(monkeypatch, {'policy:guarantees': {'answer': policy}},
        question='Can you guarantee a 30% increase in sales?',
        text='Our AI does not guarantee a 30% increase in sales.', sources=['policy:guarantees'],
        intent='answer', ids=['policy:guarantees:answer'])
    assert answer == policy and diagnostics['accepted'] and len(calls) == 1


@pytest.mark.parametrize('text', [
    'Our AI guarantees a 30% increase in sales.',
    'Our AI does not guarantee a 30% increase but guarantees a 50% increase.',
    'Our AI does not guarantee a 30% increase. I have charged your card.',
    'Our AI does not guarantee a 30% increase. Visit https://evil.example/',
])
def test_denied_percentage_repair_cannot_hide_other_unsafe_claims(monkeypatch, text):
    answer, _, diagnostics, _ = run(monkeypatch,
        {'policy:guarantees': {'answer': 'No sales uplift is guaranteed.'}},
        question='Can you guarantee a 30% increase?', text=text, sources=['policy:guarantees'],
        intent='answer', ids=['policy:guarantees:answer'])
    assert answer is None and not diagnostics['accepted']


def test_unknown_outage_policy_does_not_become_a_sales_guarantee_statement(monkeypatch):
    answer, state, diagnostics, calls = run(monkeypatch,
        {'policy:guarantees': {'answer': 'No sales uplift is guaranteed.'}},
        question='What contractual compensation do I get for an outage?',
        text='The service does not guarantee contractual compensation for outages.',
        sources=['policy:guarantees'], intent='policy', ids=['policy:guarantees:answer'])
    assert 'confirmed information' in answer and 'sales uplift' not in answer
    assert diagnostics['accepted'] and state['_response_kind'] == 'clarification' and len(calls) == 1


@pytest.mark.parametrize('question', [
    'I own a clothing shop and want help handling repetitive enquiries.',
    'I manage a restaurant. How would you configure the assistant?',
    'My company receives enquiries in several languages. Can your service help?',
])
def test_customer_scenarios_do_not_preview_unrelated_tariffs_or_policies(question):
    from service.agent_knowledge import prioritize_knowledge, response_focus
    knowledge = {'business': BUSINESS,
        'product:starter': {'name': 'Starter', 'price': 20},
        'policy:unrelated': {'answer': 'Refunds within fourteen days.'}}
    assert response_focus(question, {}) == 'apply_configurable_capabilities_to_customer_problem'
    assert list(prioritize_knowledge(knowledge, question, {})) == ['business']


def test_explicit_price_and_policy_followups_retain_their_current_sources():
    from service.agent_knowledge import prioritize_knowledge
    knowledge = {'business': BUSINESS, 'product:starter': {'name': 'Starter', 'price': 20},
        'policy:refunds': {'answer': 'Refunds within fourteen days.'}}
    assert 'product:starter' in prioritize_knowledge(knowledge, 'What does Starter cost?', {})
    assert 'policy:refunds' in prioritize_knowledge(knowledge, 'What is your refund policy?', {})


def test_nested_plan_context_is_task_scoped_without_mutating_tenant_knowledge():
    from service.agent_knowledge import prioritize_knowledge, response_focus
    business = {**BUSINESS, 'subscription_plans': {'plans': [{'name': 'Starter', 'staff_accounts': 2}]}}
    knowledge = {'business': business}
    context = {'customer_statements': ['I own an online clothing business.']}
    assert response_focus('We get 300 enquiries per month.', context) == 'apply_configurable_capabilities_to_customer_problem'
    setup = prioritize_knowledge(knowledge, 'We get 300 enquiries per month.', context)
    assert 'subscription_plans' not in setup['business']
    assert 'subscription_plans' in business
    prices = prioritize_knowledge(knowledge, 'Which plan do you recommend?', context)
    assert prices['business']['subscription_plans'] == business['subscription_plans']


@pytest.mark.parametrize('flag', ['qualification_declined', 'qualification_paused'])
def test_task_hint_cannot_restart_declined_or_paused_qualification(flag):
    from service.agent_knowledge import response_focus
    assert response_focus('Help me choose a plan.', {'previous_agent': {flag: True}}) == 'answer_current_question'
