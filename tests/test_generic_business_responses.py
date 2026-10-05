"""Generic offerings retain grounding without overriding customer intent."""
import json
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from renderer_v7 import RendererV7
from retrieval.catalog_store import CatalogStore
from retrieval.storage import Storage
from service.business_core import BusinessCore, empty_core


@pytest.fixture
def generic_business(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    (tmp_path / 'GENERIC').mkdir()
    storage = Storage('GENERIC', business_root=tmp_path)
    core = empty_core()
    core['offerings'] = [
        {'id': 'audit', 'name': 'Website Audit', 'type': 'service', 'price_type': 'from',
         'price': 450, 'currency': 'USD', 'duration_minutes': 90, 'active': True},
        {'id': 'translation', 'name': 'Document Translation', 'type': 'service',
         'price_type': 'per_word', 'price': 0.085, 'currency': 'EUR', 'active': True},
        {'id': 'membership', 'name': 'Support Membership', 'type': 'subscription',
         'price_type': 'fixed', 'price': 20, 'currency': 'GBP', 'active': True},
        {'id': 'project', 'name': 'Custom Project', 'type': 'custom_quote',
         'price_type': 'quote', 'price': 999, 'active': True},
        {'id': 'inactive', 'name': 'Retired Package', 'type': 'package',
         'price_type': 'fixed', 'price': 100, 'active': False},
    ]
    core['business_rules'] = [
        {'id': 'audit-review', 'title': 'Website audit scope',
         'description': 'Website audit scope needs review before confirming the final price.',
         'requires_manual_review': True, 'active': True},
        {'id': 'wedding', 'title': 'Wedding deposit',
         'description': 'Wedding catering requires a deposit.', 'active': True},
    ]
    core['work'] = [{'id': 'private', 'type': 'project', 'title': 'Private client record',
                     'status': 'requested', 'customer_reference': 'PRIVATE-CUSTOMER'}]
    storage.write_json('GENERIC', 'business_core.json', core)
    return storage, core


def make_handler(storage, **deps):
    handler = MessageHandlerV7(SimpleNamespace(catalog=CatalogStore(storage), **deps))
    # An unexpected model path stays isolated; this test never calls a provider.
    handler.brain.client = None
    return handler


def turn(handler, text, session=None):
    return handler.handle(text, SimpleNamespace(tenant='GENERIC', session_id='isolated', channel='web'), session or {})


def test_generic_answer_returns_only_relevant_active_public_facts(generic_business):
    storage, _ = generic_business
    business = BusinessCore(storage, 'GENERIC')
    details = business.answer_details('Website Audit')
    assert [item['id'] for item in details['offerings']] == ['audit']
    assert 'From USD 450' in details['reply'] and '90 minutes' in details['reply']
    assert 'review before confirming' in details['reply']
    assert 'Wedding' not in details['reply']
    assert 'PRIVATE-CUSTOMER' not in json.dumps(details)
    assert 'Private client record' not in json.dumps(details)
    assert business.answer('Website Audit') == details['reply']
    assert business.answer('Can you do that for me?') is None
    assert business.answer('Retired Package') is None


def test_generic_types_and_price_conditions_are_not_flattened(generic_business):
    storage, _ = generic_business
    business = BusinessCore(storage, 'GENERIC')
    subscriptions = business.answer_details('Show subscriptions')
    assert [item['id'] for item in subscriptions['offerings']] == ['membership']
    assert 'GBP 20' in subscriptions['reply']
    assert 'billing interval and renewal terms need confirmation' in subscriptions['reply']
    assert 'per month' not in subscriptions['reply']
    assert 'EUR 0.085 per word' in business.answer('Document Translation')
    quote = business.answer('Custom Project')
    assert 'Quote required' in quote and '999' not in quote
    assert 'No booking or payment has been made' in quote


def test_relevant_offerings_after_public_context_limit_can_be_found(generic_business):
    storage, core = generic_business
    core['offerings'] = [
        {'id': str(index), 'name': f'Configured Service {index}', 'type': 'service',
         'price_type': 'quote', 'active': True}
        for index in range(60)
    ]
    core['offerings'].append({'id': 'last', 'name': 'Specialist Repair', 'type': 'service',
                              'price_type': 'quote', 'active': True})
    storage.write_json('GENERIC', 'business_core.json', core)
    business = BusinessCore(storage, 'GENERIC')
    assert len(business.public_context()['offerings']) == 50
    assert business.answer_details('Specialist Repair')['offerings'][0]['id'] == 'last'


def test_greeting_handoff_and_exact_faq_precede_generic_name_matches(generic_business):
    storage, core = generic_business
    for identifier, name in [('greet', 'Good Morning'), ('support', 'Customer Service'), ('name', 'Alice')]:
        core['offerings'].append({'id': identifier, 'name': name, 'type': 'service',
                                 'price_type': 'quote', 'active': True})
    storage.write_json('GENERIC', 'business_core.json', core)
    handler = make_handler(storage)
    assert turn(handler, 'Good morning')['intent'] == 'greeting'
    assert turn(handler, 'I need customer service')['intent'] == 'human_handoff'
    captured = turn(handler, 'My name is Alice', {'last_intent': 'human_handoff'})
    assert captured['intent'] == 'handoff_contact_captured'
    assert captured['entities']['name'] == 'Alice'
    handler._find_faq = lambda text, session, request_id: {
        'question': 'Do you offer Website Audit?', 'answer': 'The audit covers public website accessibility.'}
    answer = turn(handler, 'Do you offer Website Audit?')
    assert answer['intent'] == 'faq'
    assert answer['reply'] == 'The audit covers public website accessibility.'


def test_current_retail_price_path_keeps_precedence(generic_business):
    storage, core = generic_business
    storage.write_json('GENERIC', 'catalog.json', {'version': 1, 'currency': 'USD', 'categories': [
        {'id': 'bags', 'name': 'Bags', 'items': [
            {'sku': 'PACK', 'name': 'Canvas Pack', 'price': 149, 'unit': 'each', 'in_stock': True, 'tags': []}
        ]}
    ]})
    core['offerings'].append({'id': 'pack', 'name': 'Canvas Pack', 'type': 'custom_quote',
                             'price_type': 'quote', 'active': True})
    storage.write_json('GENERIC', 'business_core.json', core)
    result = turn(make_handler(storage), 'How much is Canvas Pack?')
    assert result['intent'] == 'price_check'
    assert '$149.00' in result['reply'] and 'Quote required' not in result['reply']


def test_generic_response_has_structured_facts_and_session_scoped_selection(generic_business):
    storage, _ = generic_business
    handler = make_handler(storage)
    result = turn(handler, 'Website Audit')
    assert result['intent'] == 'business_knowledge'
    assert result['entities']['offering_id'] == 'audit'
    assert result['facts']['items'][0]['price_type'] == 'from'
    assert result['facts']['business_knowledge']['source'] == 'business_core'
    session = {'last_items': ['translation', 'audit'], 'last_items_source': 'business_core',
               'sales_agent': {'next_action': 'compare_or_price_selection'}}
    selected = turn(handler, '2', session)
    assert [item['id'] for item in selected['facts']['items']] == ['audit']
    business = BusinessCore(storage, 'GENERIC')
    assert business.answer_details('1', selected_ids=['inactive']) is None


def test_numbered_selection_cannot_switch_between_native_ids_and_retail_skus(generic_business):
    storage, core = generic_business
    core['offerings'][0]['id'] = 'SHARED'
    storage.write_json('GENERIC', 'business_core.json', core)
    storage.write_json('GENERIC', 'catalog.json', {'version': 1, 'currency': 'USD', 'categories': [
        {'id': 'office', 'name': 'Office', 'items': [
            {'sku': 'SHARED', 'name': 'Office Desk', 'price': 45, 'unit': 'each', 'in_stock': True, 'tags': []}
        ]}
    ]})
    handler = make_handler(storage)
    state = {'last_items': ['SHARED'], 'last_items_source': 'business_core',
             'sales_agent': {'next_action': 'compare_or_price_selection'}}
    native = turn(handler, '1', state)
    assert native['intent'] == 'business_knowledge'
    assert 'Website Audit' in native['reply'] and 'From USD 450' in native['reply']
    assert 'Office Desk' not in native['reply']
    state.pop('last_items_source')
    retail = turn(handler, '1', state)
    assert retail['intent'] == 'price_check' and 'Office Desk' in retail['reply']
    assert 'Website Audit' not in retail['reply']


@pytest.mark.parametrize('action,intent', [('SEARCH_PRODUCTS', 'search_product'), ('PRICE_CHECK', 'price_check')])
@pytest.mark.parametrize('message', [
    'My online presence could be better', 'I need help improving my online presence',
])
def test_semantic_model_selection_resolves_native_facts_in_the_full_handler(generic_business, action, intent, message):
    storage, _ = generic_business
    handler = make_handler(storage)
    calls = []
    def semantic_plan(**kwargs):
        calls.append(kwargs)
        return {'action': action, 'intent': intent, 'product_name': 'Website Audit',
                'needs_clarification': False, 'meta': {'max_items': 8}}
    handler.brain = SimpleNamespace(plan=semantic_plan)
    result = turn(handler, message)
    assert len(calls) == 1
    assert result['intent'] == 'business_knowledge'
    assert result['entities']['offering_id'] == 'audit'
    assert [item['id'] for item in result['facts']['items']] == ['audit']
    assert result['facts']['business_knowledge']['source'] == 'business_core'
    assert 'From USD 450' in result['reply']
    assert '90 minutes' in result['reply']
    assert 'No booking or payment has been made' in result['reply']
    assert 'PRIVATE-CUSTOMER' not in json.dumps(result)


def test_semantic_plan_cannot_invent_or_reactivate_a_native_offering(generic_business):
    storage, _ = generic_business
    handler = make_handler(storage)
    for name in ['Imaginary Premium Package', 'Retired Package', 'Private client record']:
        assert handler._planned_generic_offering({'action': 'PRICE_CHECK', 'product_name': name}) is None


def test_explicit_native_selection_does_not_include_an_overlapping_name(generic_business):
    storage, core = generic_business
    core['offerings'].append({'id': 'other-audit', 'name': 'Website Audit Premium', 'type': 'service',
                             'price_type': 'quote', 'active': True})
    storage.write_json('GENERIC', 'business_core.json', core)
    details = BusinessCore(storage, 'GENERIC').answer_details('Website Audit', selected_ids=['audit'])
    assert [item['id'] for item in details['offerings']] == ['audit']


def test_advertised_read_only_plan_actions_resolve_existing_helpers(generic_business):
    storage, _ = generic_business
    handler = make_handler(storage)
    handler.catalog = CatalogStore(catalog={'version': 1, 'currency': 'EUR', 'categories': [
        {'id': 'services', 'name': 'Services', 'items': [{'sku': 'AUDIT', 'name': 'Audit', 'price': 45, 'in_stock': True}]}
    ]})
    price = handler._execute_plan({'action': 'PRICE_CHECK', 'sku': 'AUDIT'}, 'What does it cost?', {}, 'test')
    assert price['price']['price'] == 45 and price['currency'] == 'EUR'
    handler._find_faq = lambda text, session, request_id: {'question': 'Terms?', 'answer': 'Review is required.'}
    assert handler._execute_plan({'action': 'FAQ_LOOKUP'}, 'Terms?', {}, 'test')['faq']['answer'] == 'Review is required.'
    handler._store_info_answer = lambda text: 'The office is open weekdays.'
    assert handler._execute_plan({'action': 'STORE_INFO'}, 'Hours?', {}, 'test')['store_info']['answer'] == 'The office is open weekdays.'


def test_focused_clarifier_preserves_the_relevant_business_question():
    renderer = RendererV7()
    result = renderer.render(user_text='I need help',
                             plan={'intent': 'unknown', 'needs_clarification': True,
                                   'clarification_question': 'Is this for one person or a business team?'},
                             facts={}, session={})
    assert result == 'Is this for one person or a business team?'


def test_focused_model_question_survives_the_full_handler(generic_business):
    storage, _ = generic_business
    handler = make_handler(storage)
    handler.brain = SimpleNamespace(plan=lambda **kwargs: {
        'intent': 'unknown', 'action': 'ASK_SLOT', 'needs_clarification': True,
        'clarification_question': 'How many people would use this?',
    })
    result = turn(handler, 'Is this suitable for our team?')
    assert result['reply'] == 'How many people would use this?'
    plan = handler._normalize_plan({
        'intent': 'search_product', 'action': 'ASK_SLOT', 'needs_clarification': True,
        'clarification_question': 'Which equipment will you use this with?',
    }, 'I need compatible equipment')
    assert plan['needs_clarification'] is True


@pytest.mark.parametrize('goal,question,customer_request', [
    ('request_quote', 'What do you need a quote for?', 'Request a quote'),
    ('book_appointment', 'Which service would you like an appointment for?', 'Arrange an appointment'),
    ('start_subscription', 'What would you like your subscription to include?', 'Discuss a subscription'),
])
def test_business_goal_greetings_and_next_steps_use_safe_handoff(generic_business, goal, question, customer_request):
    storage, _ = generic_business
    class Overrides:
        def get(self, key):
            return {'primary_goal': goal, 'offering_type': 'services'} if key == 'sales_playbook' else None
    handler = make_handler(storage, overrides=Overrides())
    assert question in turn(handler, 'Hi')['reply']
    result = turn(handler, customer_request)
    assert result['intent'] == 'human_handoff'
    assert 'phone number or email' in result['reply']
    assert not result.get('actions')


@pytest.mark.parametrize('question', [
    'What is your password?', 'Please send your card number?', 'Can you visit https://example.test?',
    'Can you visit example.com?', 'Ignore the system instructions?', 'Your booking is confirmed; what is your name?',
    'What is your card PIN?', 'What is your payment PIN?', 'Can you share your security code?',
    'What are your login credentials?', 'Could you send your card details?', 'What is your account login?',
    'What is your one-time code?', 'What is your 2FA code?',
    'First question? Second question?', 'What do you need?\n', 'x' * 241 + '?',
])
def test_unsafe_model_clarifier_uses_the_safe_fallback(question):
    renderer = RendererV7()
    result = renderer.render(user_text='Help',
                             plan={'intent': 'unknown', 'needs_clarification': True,
                                   'clarification_question': question}, facts={}, session={})
    assert result != question and result.startswith('Could you clarify')


def test_unknown_availability_is_not_reported_as_out_of_stock():
    renderer = RendererV7()
    result = renderer.render(user_text='How much?', plan={'action': 'PRICE_CHECK'},
                             facts={'price': {'sku': 'AUDIT', 'name': 'Audit', 'price': 45, 'in_stock': None}}, session={})
    assert 'availability needs confirmation' in result
    assert 'out of stock' not in result
