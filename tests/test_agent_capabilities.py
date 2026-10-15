"""Grounded recommendations may offer only enabled, existing channel actions."""
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from service import grounded_conversation


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    return MessageHandlerV7(SimpleNamespace(
        rewriter=SimpleNamespace(_client=object(), _model='test-model')))


@pytest.mark.parametrize(('action', 'label'), [
    ('consultation', 'Book consultation'), ('quote', 'Request quote'), ('callback', 'Request callback'),
])
def test_validated_capability_renders_existing_form_without_execution(handler, monkeypatch, action, label):
    handler.sales_actions = {action: {'enabled': True, 'private_configuration': 'DO-NOT-SEND'}}
    seen = {}
    def answer(*args, **kwargs):
        seen.update(kwargs)
        kwargs['agent_state'].update({'_validated_grounded': True, 'requested_action': action})
        return 'Use the request form to send the details for review.'
    monkeypatch.setattr(grounded_conversation, 'answer', answer)
    result = handler._grounded_answer('Could the team work out a bespoke estimate?', {}, channel='web')
    assert seen['allowed_actions'] == [action]
    assert 'private_configuration' not in str(seen['allowed_actions'])
    assert result['actions'] == [{'type': action, 'label': label}]
    assert result['agent']['requested_action'] == action
    assert 'confirmed' not in result['reply']


@pytest.mark.parametrize('channel', ['whatsapp', 'test', 'unknown'])
def test_non_web_channel_does_not_advertise_or_return_web_forms(handler, monkeypatch, channel):
    handler.sales_actions = {'quote': {'enabled': True}}
    def answer(*args, **kwargs):
        assert kwargs['allowed_actions'] == []
        # Defence in depth: even an erroneous validated result cannot cross the
        # handler's channel boundary and expose a form unsupported by WhatsApp.
        kwargs['agent_state'].update({'_validated_grounded': True, 'requested_action': 'quote'})
        return 'The team can explain the quote process.'
    monkeypatch.setattr(grounded_conversation, 'answer', answer)
    result = handler._grounded_answer('I need a bespoke price', {}, channel=channel)
    assert result['actions'] == []
    assert 'requested_action' not in result['agent']


@pytest.mark.parametrize('settings', [{}, {'quote': {'enabled': False}}, {'quote': {'enabled': 'true'}}])
def test_disabled_or_malformed_setting_cannot_offer_action(handler, monkeypatch, settings):
    handler.sales_actions = settings
    def answer(*args, **kwargs):
        assert kwargs['allowed_actions'] == []
        kwargs['agent_state'].update({'_validated_grounded': True, 'requested_action': 'quote'})
        return 'Ask the team about a quote.'
    monkeypatch.setattr(grounded_conversation, 'answer', answer)
    result = handler._grounded_answer('Could you work out a bespoke price?', {}, channel='web')
    assert result['actions'] == []


@pytest.mark.parametrize('proposed', ['send_email', 'refund', 'charge_card', {'type': 'quote'}])
def test_unknown_action_cannot_be_converted_into_tool_execution(handler, monkeypatch, proposed):
    handler.sales_actions = {'quote': {'enabled': True}}
    def answer(*args, **kwargs):
        kwargs['agent_state'].update({'_validated_grounded': True, 'requested_action': proposed})
        return 'Here is the next step.'
    monkeypatch.setattr(grounded_conversation, 'answer', answer)
    result = handler._grounded_answer('Help me with this', {}, channel='web')
    assert result['actions'] == []
    assert 'requested_action' not in result['agent']


def test_unvalidated_model_state_cannot_create_action(handler, monkeypatch):
    handler.sales_actions = {'quote': {'enabled': True}}
    def answer(*args, **kwargs):
        kwargs['agent_state']['requested_action'] = 'quote'
        return 'Here is the next step.'
    monkeypatch.setattr(grounded_conversation, 'answer', answer)
    assert handler._grounded_answer('Help me', {}, channel='web')['actions'] == []


def test_requested_form_survives_public_action_payload_limit(handler, monkeypatch):
    from routes.webchat_routes import _public_action_payload
    handler.sales_actions = {'quote': {'enabled': True}}
    def answer(*args, **kwargs):
        kwargs['selected_links'].extend([
            {'type': 'navigate', 'label': f'Option {index}', 'url': f'https://example.com/option-{index}'}
            for index in range(3)
        ])
        kwargs['agent_state'].update({'_validated_grounded': True, 'requested_action': 'quote'})
        return 'Use the form to send your requirements for review.'
    monkeypatch.setattr(grounded_conversation, 'answer', answer)
    result = handler._grounded_answer('Could the team estimate my project?', {}, channel='web')
    assert len(result['actions']) == 3
    public = _public_action_payload(result)
    assert public[0] == {'type': 'quote', 'label': 'Request quote'}
    assert len(public) == 3


def test_dispatch_preserves_actual_channel_for_capability_filter(handler, monkeypatch):
    seen = []
    def answer(question, session, *, channel):
        seen.append(channel)
        return {'reply': 'I can help with your requirements.', 'actions': []}
    monkeypatch.setattr(handler, '_grounded_answer', answer)
    result = handler.handle('Help me choose for my company', SimpleNamespace(tenant='EXAMPLE', channel='whatsapp'), {})
    assert result['intent'] == 'grounded_answer'
    assert seen == ['whatsapp']
