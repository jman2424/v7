"""Regressions from real customer testing, independent of a particular tenant."""
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from retrieval.catalog_store import CatalogStore
from retrieval.faq_store import FAQStore
from service.reply_formatting import readable_reply
from service import chat_diagnostics
from service.sales_agent import SalesAgentPolicy
from tests.conftest import set_test_identity
from tests.test_grounded_conversation import _structured_answer


@pytest.fixture
def assistant(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    catalog = CatalogStore(catalog={'version': 1, 'currency': 'GBP', 'categories': [{
        'id': 'care', 'name': 'Vehicle care', 'items': [
            {'sku': 'SMALL', 'name': 'Enhancement Small', 'price': 400, 'unit': 'vehicle'},
            {'sku': 'MEDIUM', 'name': 'Enhancement Medium', 'price': 450, 'unit': 'vehicle'},
            {'sku': 'LARGE', 'name': 'Enhancement Large', 'price': 500, 'unit': 'vehicle'},
        ]}]})
    return MessageHandlerV7(SimpleNamespace(catalog=catalog, faq=FAQStore(faq=[
        {'q': 'What are your opening hours?', 'a': 'Open daily from 8am to 6pm.', 'tags': ['hours']},
        {'q': 'What services do you offer?', 'a': 'Vehicle care and training.', 'tags': ['services']},
        {'q': 'How much is ceramic coating?', 'a': 'Coating starts at £250.', 'tags': ['prices']},
    ])))


def test_numbered_choice_survives_pending_qualification(assistant, monkeypatch):
    monkeypatch.setattr(assistant, '_grounded_answer', lambda *a, **k: pytest.fail('A numeric choice is already resolved'))
    session = {'last_items': ['SMALL', 'MEDIUM', 'LARGE'], 'sales_agent': {
        'next_action': 'ask_qualification_question', 'qualification_pending': True}}
    result = assistant.handle('3', SimpleNamespace(channel='test'), session)
    assert result['intent'] == 'price_check'
    assert result['facts']['price']['sku'] == 'LARGE'
    assert '£500.00' in result['reply'] and 'coating' not in result['reply'].lower()
    policy = SalesAgentPolicy(overrides={'sales_playbook': {
        'qualification_questions': ["What is your car's make and model?"]}})
    guided = policy.guide(result, user_text='3', session=session)
    assert not guided['agent'].get('qualification_answers')
    assert guided['agent']['qualification_pending']


@pytest.mark.parametrize('text', [
    'who is your owner are they trained', 'where can i find you guys', 'what',
])
def test_information_questions_do_not_use_catalogue_partial_matches(assistant, text):
    assert not assistant._looks_like_product_query(text)
    result = assistant.handle(text, SimpleNamespace(channel='test'), {'last_category': 'care'})
    assert result['intent'] not in {'search_product', 'browse_category', 'price_check'}
    assert '£400' not in result['reply']


def test_exact_faq_ranks_above_answer_word_overlap():
    store = FAQStore(faq=[
        {'q': 'What services do you offer?', 'a': 'Services, booking, prices and social media.', 'tags': ['services']},
        {'q': 'How do I book?', 'a': 'Use our booking page to check available times.', 'tags': ['booking']},
    ])
    assert store.best_match('How do I book?', min_sim=0.45)[0]['q'] == 'How do I book?'
    assert store.best_match('okay', min_sim=0.45) == []
    assert store.best_match('3', min_sim=0.45) == []


def test_fallback_search_does_not_match_sentence_filler_against_product_names(assistant):
    assistant.catalog = CatalogStore(catalog={'version':1,'currency':'GBP','categories':[{
        'id':'surface','name':'Ceramic and surface coatings','items':[
            {'sku':f'{kind}_{size}','name':f'{name} {size} starting price','price':price}
            for kind,name,price in [('LEATHER','Leather Coating',100),('CERAMIC','Entry 2-Year Ceramic Coating',250)]
            for size in ('Small','Medium','Large')]}]})
    question = 'What are the Small, Medium and Large starting prices for standalone ceramic coating?'
    result = assistant.handle(question,SimpleNamespace(channel='test'),{})
    assert result['facts']['items'][0]['sku'].startswith('CERAMIC_')
    plan = assistant._heuristic_plan(question,'synthetic')
    assert not {'the','what','are','and','for'} & set(plan['meta']['search_tags'])


def test_long_answer_incidental_word_is_not_a_direct_faq_match():
    store = FAQStore(faq=[{'q': 'How does assessment work?', 'a':
        ' '.join(f'background{i}' for i in range(100)) + ' A BMW owner may book.', 'tags': []}])
    assert store.best_match('who is your owner', min_sim=0.45) == []


def test_private_faq_never_qualifies_for_direct_fallback():
    store = FAQStore(faq=[{'q': 'What are your hours?', 'a': 'PRIVATE', 'public': False}])
    assert store.best_match('What are your hours?') == []


@pytest.mark.parametrize('channel', ['web', 'test'])
def test_final_navigation_is_clickable_in_both_customer_and_console_channels(assistant, channel):
    assistant.website_destinations = [{
        'id': 'booking', 'label': 'Book a service', 'url': 'https://booking.example.com/', 'enabled': True}]
    result = assistant.finalize_navigation({'reply': 'Continue at https://booking.example.com/.'}, channel)
    assert 'https://' not in result['reply']
    assert result['actions'] == [{'type': 'navigate', 'label': 'Book a service', 'url': 'https://booking.example.com/'}]


def test_tester_endpoint_returns_real_navigation_but_does_not_submit_actions(app, client, monkeypatch):
    with client.session_transaction() as state:
        set_test_identity(client, state, {'id': 'operator', 'roles': ['platform_admin'], 'tenant': 'EXAMPLE'})
    handler = app.container.for_tenant('EXAMPLE').handler.h_v7
    handler.website_destinations = [{
        'id': 'booking', 'label': 'Book a service', 'url': 'https://booking.example.com/', 'enabled': True}]
    monkeypatch.setattr(handler, '_grounded_answer', lambda *a, **k: {
        'reply': 'Use https://booking.example.com/.', 'actions': []})
    response = client.post('/admin/api/test-agent?tenant=EXAMPLE', json={'message': 'How do I book?'})
    assert response.status_code == 200
    assert 'https://' not in response.json['reply']
    assert response.json['actions'] == [{
        'type': 'navigate', 'label': 'Book a service', 'url': 'https://booking.example.com/'}]


@pytest.mark.parametrize('question,text', [
    ('Where would you put my car?', 'Your BMW X3 would provisionally use the Large band because it is an SUV.'),
    ('What services do you offer?', 'We offer mobile detailing, paint correction and coatings.'),
])
def test_descriptive_model_answer_is_not_replaced_by_entire_faq(monkeypatch, question, text):
    source = {'question': 'Which cars are Small, Medium or Large?',
              'answer': 'SUVs use Large. Ask for make and model. Never invent a category.'}
    if 'services' in question:
        source = {'question': 'What services do you offer?',
                  'answer': 'Mobile detailing, paint correction and coatings. Booking is available on our site.'}
    answer, _, _, _ = _structured_answer(monkeypatch, {
        'answer': text, 'kind': 'answer', 'sources': ['faq:details'],
        'statement_ids': ['faq:details:answer']}, question=question, knowledge={'faq:details': source})
    assert answer == text
    assert 'Never invent' not in answer


def test_pricing_groups_are_separated_without_losing_any_price_or_condition():
    text = ('Starting prices for Small / Medium / Large are Entry 2-Year £250 / £275 / £300, '
            'Premium 3-Year £300 / £325 / £350, and Signature 5-Year £350 / £375 / £400. '
            'Larger vehicles or additional correction are quoted on inspection.')
    formatted = readable_reply(text)
    assert '\n\nPremium' in formatted and '\n\nand Signature' in formatted
    assert formatted.split() == text.split()
    assert readable_reply(formatted) == formatted


def test_first_message_recall_survives_short_history_but_is_session_scoped(app, client):
    app.container.storage.write_json('EXAMPLE', 'ai_model.json', {'memory': {
        'enabled': True, 'history_messages': 2, 'history_tokens': 256, 'retention_minutes': 60}})
    token = None
    for message in ['hello', 'thanks', 'okay', 'what was my first mesage']:
        response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': message,
            **({'conversation_token': token} if token else {})})
        assert response.status_code == 200
        token = response.json['conversation_token']
    assert response.json['reply'] == 'Your first message was: “hello”'
    fresh = app.test_client().post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'what was my first message'})
    assert "don't have the first message" in fresh.json['reply']
    app.container.storage.write_json('EXAMPLE', 'ai_model.json', {'memory': {'enabled': False}})
    disabled = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'what was my first message',
        'conversation_token': token})
    assert "don't have the first message" in disabled.json['reply']


def test_console_provider_timeout_uses_the_same_budget_as_public_web(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(chat_diagnostics.time, 'monotonic', lambda: clock[0])
    with chat_diagnostics.turn_scope('test', 'a' * 24, 'synthetic-session'):
        assert chat_diagnostics.provider_timeout(60) == 20
        clock[0] = 28
        assert chat_diagnostics.provider_timeout(60) == 2


def test_approved_navigation_url_need_not_also_appear_in_a_cited_faq(monkeypatch):
    links = []
    payload = {'answer': 'Use https://booking.example.com/ to continue.', 'kind': 'answer',
               'sources': ['business'], 'navigation': ['booking']}
    from service import grounded_conversation
    import json
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', lambda *a, **k:
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]))
    answer = grounded_conversation.answer(object(), 'test-model', 'Show the website',
        {'business': {'name': 'Example'}}, [], 'professional', selected_links=links,
        destinations=[{'id': 'booking', 'label': 'Book', 'url': 'https://booking.example.com/'}])
    assert answer and 'https://' not in answer
    assert links == [{'type': 'navigate', 'label': 'Book', 'url': 'https://booking.example.com/'}]


def test_failed_model_answers_both_booking_and_social_parts_without_catalogue(assistant, monkeypatch):
    monkeypatch.setattr(assistant, '_grounded_answer', lambda *a, **k: None)
    assistant.faq = FAQStore(faq=[{'q': 'How do I book an appointment?',
        'a': 'Use https://booking.example.com/ to choose an available appointment.'}])
    assistant.business_profile['social'] = {'Instagram': 'https://www.instagram.com/example'}
    result = assistant.handle('How can I get a quote or make a booking? also do you have any socials',
                              SimpleNamespace(channel='test'), {'last_category': 'care'})
    assert result['intent'] == 'store_info'
    assert 'booking.example.com' in result['reply'] and 'instagram.com' in result['reply']
    assert '£400' not in result['reply']


@pytest.mark.parametrize('question', ['How do I cancel a booking?', 'Can you refund my booking?',
                                     'What deposit is needed for a booking?'])
def test_booking_fallback_cannot_replace_support_or_payment_policy(assistant, question):
    assert assistant._fallback_navigation_information(question, request_id='synthetic') is None


def test_requested_social_links_take_priority_over_extra_booking_suggestions():
    from service.website_destinations import buttonize_reply
    targets = [{'id': key, 'label': key.title(), 'url': url} for key, url in (
        ('book', 'https://booking.example.com/'), ('guest', 'https://booking.example.com/guest'),
        ('manage', 'https://booking.example.com/manage'), ('instagram', 'https://www.instagram.com/example'),
        ('tiktok', 'https://www.tiktok.com/@example'))]
    suggestions = [{'type': 'navigate', 'label': row['label'], 'url': row['url']} for row in targets[:3]]
    text = 'Book at ' + targets[0]['url'] + '. Instagram: ' + targets[3]['url'] + ' TikTok: ' + targets[4]['url']
    reply, actions = buttonize_reply(text, targets, suggestions)
    assert 'https://' not in reply
    assert [row['label'] for row in actions] == ['Book', 'Instagram', 'Tiktok']


def test_customer_details_survive_a_large_assistant_reply_and_filter_private_data(app):
    from service.message_handler import MessageContext
    handler = app.container.for_tenant('EXAMPLE').handler
    ctx = MessageContext(tenant='EXAMPLE', session_id='synthetic-details', channel='test', metadata={})
    handler._remember_turn(ctx, handler._load_session(ctx), 'if i have a bmw x3 whats the costs',
                           {'reply': 'Long catalogue prose. ' * 300})
    session = handler._load_session(ctx)
    assert 'if i have a bmw x3 whats the costs' in session['conversation_customer_statements']
    handler._remember_turn(ctx, session, 'my email is private@example.test', {'reply': 'Thanks.'})
    assert all('private@' not in value for value in handler._load_session(ctx)['conversation_customer_statements'])
    from service.grounded_conversation import agent_context_rows
    context = agent_context_rows({'customer_statements': session['conversation_customer_statements']}, {})
    assert context['customer_statements'] == ['if i have a bmw x3 whats the costs']
    assert handler.memory.get('different-session', 'conversation_customer_statements') is None


def test_car_size_followup_is_not_overwritten_by_a_quote_related_faq(monkeypatch):
    text = 'Your BMW X3 would use the Large band because it is an SUV; this is an estimate for an unlisted model.'
    answer, _, _, _ = _structured_answer(monkeypatch, {
        'answer': text, 'kind': 'answer', 'sources': ['faq:consultation'],
        'statement_ids': ['faq:consultation:answer']}, question='so were would you put my car',
        knowledge={'faq:consultation': {'question': 'How do you use my car size during a consultation and quote?',
            'answer': 'Use the model and size band for a starting price. Final quotes require inspection. SUVs use Large.'}})
    assert answer == text


def test_descriptive_question_cannot_bypass_payment_process_protection(monkeypatch):
    policy = 'The team reviews the vehicle before confirming the quote.'
    answer, _, _, _ = _structured_answer(monkeypatch, {
        'answer': 'Pay first and the team will confirm your vehicle quote afterwards.',
        'kind': 'answer', 'sources': ['faq:consultation'], 'statement_ids': ['faq:consultation:answer']},
        question='What size is my car?', knowledge={'faq:consultation': {
            'question': 'How does a consultation work?', 'answer': policy}})
    assert answer == policy
