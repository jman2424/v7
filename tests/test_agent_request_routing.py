"""Action shortcuts respect intent before a funded or automatic answer runs."""
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    instance = MessageHandlerV7(SimpleNamespace())
    instance.sales_actions = {key: {'enabled': True} for key in ('consultation', 'quote', 'callback')}
    return instance


@pytest.mark.parametrize('text', [
    "I don't want a demo, I need to understand the service",
    'Do not call me back',
    "I don't want to speak to a human",
    "I don't need a human",
    "Please don't contact me",
    'No callback, please',
    'Not now, no consultation',
    'No need for a quote',
    'I would prefer not to book a demo',
    'No quiero reservar una cita',
    'No me interesa una consulta',
    'No quiero hablar con una persona',
    'Je ne veux pas de démo',
    "Ne m'appelez pas",
    'Je ne veux pas parler avec une personne',
    'لا أريد حجز موعد',
    'لا تتصل بي',
    'لا أريد التحدث مع شخص',
])
def test_declined_action_never_opens_form_or_handoff(handler, text):
    assert handler._conversion_action(text, 'web') is None
    assert handler._explicit_human_request(text) is False
    assert handler._requests_handoff(text) is False


@pytest.mark.parametrize(('text', 'action'), [
    ('Can we arrange a demo?', 'consultation'),
    ('Can you get me a quote?', 'quote'),
    ('Please call me back', 'callback'),
    ('No website yet, book a demo', 'consultation'),
    ("I don't have a website and would like to book a demo", 'consultation'),
    ("I don't want a demo, can you get me a quote?", 'quote'),
    ("Do not call me back; I want a quote", 'quote'),
    ("I don't want a quote but I want a demo", 'consultation'),
    ('Quiero reservar una cita', 'consultation'),
    ('Quiero solicitar un presupuesto', 'quote'),
    ('Llámame por favor', 'callback'),
    ('Je voudrais réserver une démo', 'consultation'),
    ('Je souhaite demander un devis', 'quote'),
    ('Rappelez-moi', 'callback'),
    ('أريد حجز موعد', 'consultation'),
    ('أريد عرض سعر', 'quote'),
    ('اتصل بي', 'callback'),
])
def test_explicit_positive_request_still_offers_configured_action(handler, text, action):
    response = handler._conversion_action(text, 'web')
    assert response is not None and response[0] == action
    assert 'form' in response[1]
    if action == 'consultation':
        assert 'confirmed only after the form succeeds' in response[1]


@pytest.mark.parametrize('text', [
    'I want to speak to a human',
    'Can I talk to a person?',
    'I need a human to help with my V7 account. Who do I contact?',
    'I want a person to help',
    "I'd like a human please",
    'Get me a human',
    'Quiero hablar con una persona',
    'Je voudrais parler avec une personne',
    'أريد التحدث مع شخص',
])
def test_explicit_human_request_is_recognised(handler, text):
    assert handler._explicit_human_request(text) is True


@pytest.mark.parametrize('text', [
    'Do I need to talk to a human?',
    'What is a human agent?',
    'How does a human agent work?',
    'Do I need a human?',
    'I need a human resources chatbot',
])
def test_question_about_handoff_is_left_to_the_agent(handler, text):
    assert handler._explicit_human_request(text) is False
    assert handler._requests_handoff(text) is False


@pytest.mark.parametrize('text', [
    'I need to cancel my appointment',
    'Quiero cancelar mi cita',
    'Je souhaite annuler mon rendez-vous',
    'أريد إلغاء موعد',
])
def test_existing_booking_support_never_starts_new_booking(handler, text):
    assert handler._conversion_action(text, 'web') is None


def test_action_still_requires_enabled_setting_and_web_channel(handler):
    handler.sales_actions['quote']['enabled'] = False
    assert handler._conversion_action('Get me a quote', 'web') is None
    assert handler._conversion_action('Book a demo', 'whatsapp') is None


def test_decline_reaches_funded_answer_without_erasing_customer_text(handler, monkeypatch):
    seen = []
    def answer(text, session, **kwargs):
        seen.append(text)
        return {'reply': 'Here is how the service works.', 'actions': []}
    monkeypatch.setattr(handler, '_grounded_answer', answer)
    text = "I don't want a demo, I need to understand the service"
    response = handler.handle(text, SimpleNamespace(tenant='EXAMPLE', channel='web'), {})
    assert response['intent'] == 'grounded_answer'
    assert response.get('actions', []) == []
    assert seen == [text]


def test_need_a_human_uses_saved_handoff_before_provider_or_catalogue(handler, monkeypatch):
    from unittest.mock import Mock
    configured = 'For account help, email help@example.test.'
    handler.sales_playbook['handoff_message'] = configured
    provider = Mock()
    monkeypatch.setattr(handler, '_grounded_answer', provider)
    response = handler.handle('I need a human to help with my account. Who do I contact?',
                              SimpleNamespace(tenant='EXAMPLE', channel='web'), {})
    assert response['intent'] == 'human_handoff'
    assert response['reply'] == configured
    assert not provider.called


def test_negated_handoff_remains_declined_when_provider_is_unavailable(handler, monkeypatch):
    monkeypatch.setattr(handler, '_grounded_answer', lambda *args, **kwargs: None)
    response = handler.handle("I don't want to speak to a human", SimpleNamespace(tenant='EXAMPLE', channel='web'), {})
    assert response['intent'] != 'human_handoff'


@pytest.mark.parametrize('text', ['What is a human agent?', 'Do I need to talk to a person?', 'How does a human agent work?'])
def test_handoff_explanation_is_not_a_contact_request_in_automatic_mode(handler, monkeypatch, text):
    monkeypatch.setattr(handler, '_grounded_answer', lambda *args, **kwargs: None)
    response = handler.handle(text, SimpleNamespace(tenant='EXAMPLE', channel='web'), {})
    assert response['intent'] != 'human_handoff'
