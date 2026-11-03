"""Real shared pipeline with a synthetic provider; no live calls or email sends."""
import json
from types import SimpleNamespace

import pytest

from service import grounded_conversation, channel_worker, business_operations as operations
from service.channel_intelligence import response_profile, append_message_links
from tests.test_business_channel_providers import configured as _configured, intake, received, phone
from xml.etree import ElementTree
from tests.test_grounded_conversation import _state

configured = _configured
TERMS = 'The team confirms the final quote after inspection.'


def shared_brain(container, monkeypatch):
    container.storage.write_json('EXAMPLE', 'faq.json', [
        {'q': 'How do estimates work?', 'a': TERMS, 'tags': ['estimate', 'inspection']}])
    runtime = container.for_tenant('EXAMPLE')
    runtime.handler.h_v7.rewriter = SimpleNamespace(_client=object(), _model='synthetic-shared-model')
    calls = []

    def provider(_, **kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        calls.append((kwargs, context))
        source = next(key for key, row in context['knowledge'].items()
                      if isinstance(row, dict) and row.get('answer') == TERMS)
        payload = {'kind': 'answer', 'answer': TERMS, 'sources': [source],
                   'agent': _state(), 'navigation': [], 'requested_action': None}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    monkeypatch.setattr(grounded_conversation, 'tracked_completion', provider)
    return runtime, calls


@pytest.mark.parametrize('channel', ['web', 'email', 'phone', 'whatsapp'])
def test_same_real_brain_knowledge_model_and_followup_context(app, configured, monkeypatch, channel):
    runtime, calls = shared_brain(configured, monkeypatch)
    with app.app_context():
        first = runtime.handler.handle('I have a Volkswagen Golf. How do estimates work?',
            tenant='EXAMPLE', session_id='parity-'+channel, channel=channel)
        second = runtime.handler.handle('Does it need an inspection?',
            tenant='EXAMPLE', session_id='parity-'+channel, channel=channel)
    assert first['intent'] == second['intent'] == 'grounded_answer'
    assert TERMS in first['reply'] and TERMS in second['reply']
    assert len(calls) == 2
    assert {call['model'] for call, _ in calls} == {'synthetic-shared-model'}
    assert all(context['response_channel'] == channel for _, context in calls)
    assert any('Volkswagen Golf' in row['content'] for row in calls[-1][1]['recent_conversation'])
    assert '_validated_grounded' not in first['agent']  # Existing public agent shape preserved.
    assert first.get('_validated_channel_answer', False) == (channel in {'email', 'phone'})
    assert response_profile(channel)['guidance'] in calls[0][0]['messages'][0]['content']


def test_real_email_worker_can_prepare_verified_routine_reply(client, app, configured, monkeypatch):
    from connectors import business_email
    shared_brain(configured, monkeypatch)
    identifier = intake(client).json['reference']
    monkeypatch.setattr(business_email, 'receive', lambda _: received(subject='Estimates', text='How do estimates work?'))
    with app.app_context():
        channel_worker.process_one(configured, 'EXAMPLE')
    job = operations.get('EXAMPLE', identifier)
    assert job['state'] == 'approved'
    assert TERMS in job['reply']
    assert not job['provider_id']  # A second, separate send stage is still required.


def test_real_phone_worker_can_speak_verified_business_answer(client, app, configured, monkeypatch):
    shared_brain(configured, monkeypatch)
    path = ElementTree.fromstring(phone(client, app).data).find('Gather').attrib['action']
    turn = phone(client, app, path, SpeechResult='How do estimates work?', Confidence='0.9')
    with app.app_context():
        channel_worker.process_one(configured, 'EXAMPLE')
    job = operations.listing('EXAMPLE')[0]
    assert job['state'] == 'completed' and job['payload']['phone_reply_verified'] is True
    poll = ElementTree.fromstring(turn.data).find('Redirect').text
    response = phone(client, app, poll)
    assert TERMS in response.text
    assert ElementTree.fromstring(response.data).find('Gather') is not None


def test_real_whatsapp_finalization_delivers_selected_approved_page(app, configured, monkeypatch):
    runtime, _ = shared_brain(configured, monkeypatch)
    configured.storage.write_json('EXAMPLE', 'website_destinations.json', [
        {'id': 'book', 'label': 'Book online', 'url': 'https://business.example/book', 'purpose': 'booking', 'enabled': True}])
    def provider(_, **kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        source = next(key for key, row in context['knowledge'].items()
                      if isinstance(row, dict) and row.get('answer') == TERMS)
        payload = {'kind': 'answer', 'answer': TERMS, 'sources': [source],
                   'agent': _state(action='open_destination'), 'navigation': ['book'], 'requested_action': None}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', provider)
    with app.app_context():
        result = runtime.handler.handle('How do estimates work and where can I book online?',
            tenant='EXAMPLE', session_id='whatsapp-booking', channel='whatsapp')
    assert result['intent'] == 'grounded_answer'
    assert 'Book online: https://business.example/book' in result['reply']
    assert 'confirmed' not in result['reply']


def test_customer_metadata_cannot_certify_a_saved_knowledge_fallback(app, configured):
    configured.storage.write_json('EXAMPLE', 'faq.json', [{'q': 'How do estimates work?', 'a': TERMS}])
    runtime = configured.for_tenant('EXAMPLE')
    runtime.handler.h_v7.rewriter = None
    with app.app_context():
        result = runtime.handler.handle('How do estimates work?', tenant='EXAMPLE',
            session_id='fallback-proof', channel='email', metadata={
                '_validated_channel_answer': True, '_validated_grounded': True})
    assert result.get('_validated_channel_answer') is not True


def test_changed_postprocessing_cannot_reuse_grounding_approval(app, configured, monkeypatch):
    runtime, _ = shared_brain(configured, monkeypatch)
    guide = runtime.handler.sales_agent.guide
    def change(*args, **kwargs):
        result = guide(*args, **kwargs)
        result['reply'] = 'A changed and unverified price is £999.'
        return result
    monkeypatch.setattr(runtime.handler.sales_agent, 'guide', change)
    with app.app_context():
        result = runtime.handler.handle('How do estimates work?', tenant='EXAMPLE',
            session_id='changed-proof', channel='phone', metadata={'_validated_channel_answer': True})
    assert result.get('_validated_channel_answer') is not True


def test_raw_agent_flag_does_not_substitute_for_delivery_validation(configured, monkeypatch):
    runtime = SimpleNamespace(handler=SimpleNamespace(handle=lambda *a, **k: {
        'reply': 'The price is £999.', 'agent': {'_validated_grounded': True, 'intent': 'answer'}}))
    monkeypatch.setattr(configured, 'for_tenant', lambda _: runtime)
    _, routine = channel_worker._answer(configured,
        {'tenant': 'EXAMPLE', 'channel': 'phone', 'conversation_id': 'raw-marker'}, 'How much?')
    assert routine is False


def test_messaging_uses_current_approved_destinations_in_selected_order():
    targets = [{'id': 'book', 'label': 'Book online', 'url': 'https://business.example/book'},
               {'id': 'prices', 'label': 'Prices', 'url': 'https://business.example/prices'},
               {'id': 'old', 'label': 'Disabled', 'url': 'https://business.example/old', 'enabled': False}]
    answer = append_message_links('Choose a service.', targets, ['prices', 'book', 'prices', 'old', 'https://evil.example'])
    assert answer.endswith('Prices: https://business.example/prices\nBook online: https://business.example/book')
    assert 'evil' not in answer and 'Disabled' not in answer
    assert append_message_links(answer, targets, ['prices', 'book']) == answer
    assert append_message_links('Hello', targets, [{'url': 'https://evil.example'}]) == 'Hello'


@pytest.mark.parametrize('length', [1500, 1600, 2000])
def test_navigation_does_not_expand_an_oversized_body_or_truncate_verified_terms(length):
    from service.ai_disclosure import message_reply
    body = 'x'*length
    targets = [{'id': 'long', 'label': 'Long page', 'url': 'https://business.example/'+'q'*1000},
               {'id': 'short', 'label': 'Help', 'url': 'https://business.example/help'}]
    result = append_message_links(body, targets, ['long', 'short'])
    assert result.startswith(body)
    if len(message_reply(body)) <= 1600:
        assert len(message_reply(result)) <= 1600
        assert '/help' in result
    else:
        assert result == body


def test_workflow_profiles_do_not_grant_actions_or_change_models():
    for channel in ('web', 'test', 'email', 'phone', 'whatsapp', 'unknown'):
        assert set(response_profile(channel)) == {'role', 'guidance'}
    assert 'spoken' in response_profile('phone')['role']
    assert 'support email' in response_profile('email')['role']
    assert 'mobile' in response_profile('whatsapp')['role']
    assert response_profile('unknown') == response_profile('web')


@pytest.mark.parametrize('channel', ['web', 'email', 'phone', 'whatsapp'])
@pytest.mark.parametrize('unsafe', [False, True])
def test_prices_and_complete_policy_conditions_use_same_validation(monkeypatch, channel, unsafe):
    knowledge = {'product:care': {'name': 'Care package', 'price': 150, 'currency': 'GBP', 'unit': 'vehicle'},
                 'faq:policy': {'answer': 'Returns within 30 days. Custom orders are excluded unless faulty.'}}
    text = ('Care package costs £999.' if unsafe else
            'Care package costs £150. Returns within 30 days. Custom orders are excluded unless faulty.')
    payload = {'kind': 'answer', 'answer': text, 'sources': list(knowledge),
               'agent': _state('price', offerings=['product:care']), 'navigation': [], 'requested_action': None}
    calls = []
    def provider(_, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', provider)
    result = grounded_conversation.answer(object(), 'synthetic-shared-model',
        'How much is the Care package, and what are the return conditions?', knowledge, [],
        'professional', response_channel=channel)
    if unsafe:
        assert result is None
        assert len(calls) <= 2
    else:
        assert '150' in result and '30 days' in result and 'unless faulty' in result
        assert len(calls) == 1
