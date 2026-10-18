"""Fault injection at the real request, memory and accounted-provider boundaries."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APITimeoutError

from service import api_usage, chat_diagnostics, usage_wallet
from service.plan_usage import AllowancePaused
from tests import test_api_usage
from tests.test_api_usage import completion, fake_exchange
from tests.test_grounded_conversation import _structured_answer

ledger = test_api_usage.ledger


def test_guarded_turn_is_in_same_conversation_history(app, client, monkeypatch):
    handler = app.container.for_tenant('EXAMPLE').handler
    monkeypatch.setattr(handler, '_guard_input', lambda *args, **kwargs: {
        'reply': 'Please clarify that term.', 'intent': 'system_clarify'})
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'SYNTHETIC unknown term'}).json
    history = handler.memory.get(response['session_id'], 'conversation_history')
    assert history[-2:] == [{'role': 'user', 'content': 'SYNTHETIC unknown term'},
                            {'role': 'assistant', 'content': 'Please clarify that term.'}]


def test_optional_crm_failure_preserves_answer_and_private_text_stays_out_of_logs(app, client, monkeypatch, caplog):
    handler = app.container.for_tenant('EXAMPLE').handler
    monkeypatch.setattr(handler, '_log_crm', Mock(side_effect=RuntimeError('SYNTHETIC_PRIVATE_EXCEPTION')))
    with caplog.at_level('INFO'):
        response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'green = good'})
    assert response.status_code == 200 and 'green = good' in response.json['reply']
    assert 'SYNTHETIC_PRIVATE_EXCEPTION' not in caplog.text
    events = [json.loads(row.message) for row in caplog.records if row.name == 'Chat.Diagnostics']
    assert any(row['event'] == 'chat_optional_failure' for row in events)
    assert any(row['event'] == 'chat_finished' and row['provider_calls'] == 0 for row in events)
    assert any(row['event'] == 'chat_http_finished' and row['request_id'] == response.headers['X-Request-ID'] for row in events)
    assert all('green' not in json.dumps(row) for row in events)


def test_failed_contact_capture_does_not_claim_success(app, client, monkeypatch):
    handler = app.container.for_tenant('EXAMPLE').handler
    monkeypatch.setattr(handler.h_v7, 'handle', lambda *args, **kwargs: {
        'reply': 'I recorded your details.', 'intent': 'handoff_contact_captured', 'entities': {}})
    monkeypatch.setattr(handler, '_log_crm', Mock(side_effect=RuntimeError('private')))
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'Please contact me'})
    assert response.status_code == 200 and "couldn't save" in response.json['reply']
    history = handler.memory.get(response.json['session_id'], 'conversation_history')
    assert "couldn't save" in history[-1]['content']


def test_shared_web_budget_caps_saved_timeout_and_stops_extra_calls(ledger, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(chat_diagnostics.time, 'monotonic', lambda: clock[0])
    client = Mock()
    client.chat.completions.create.return_value = completion()
    with chat_diagnostics.turn_scope('web', 'a'*24, 'PRIVATE_SESSION'), api_usage.usage_context('EXAMPLE', 'web'):
        api_usage.tracked_completion(client, purpose='planning', model='gpt-4o-mini', timeout=60)
        assert client.chat.completions.create.call_args.kwargs['timeout'] == 20
        clock[0] = 27.5
        api_usage.tracked_completion(client, purpose='planning', model='gpt-4o-mini', timeout=60)
        assert client.chat.completions.create.call_args.kwargs['timeout'] == 2.5
        clock[0] = 31
        with pytest.raises(AllowancePaused, match='turn_budget_exhausted'):
            api_usage.tracked_completion(client, purpose='planning', model='gpt-4o-mini')
    assert client.chat.completions.create.call_count == 2


def test_expired_budget_after_reservation_settles_zero_without_provider_call(ledger, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(chat_diagnostics.time, 'monotonic', lambda: clock[0])
    reserve = usage_wallet.reserve_usage
    def delayed(*args, **kwargs):
        result = reserve(*args, **kwargs)
        clock[0] = 31
        return result
    monkeypatch.setattr(usage_wallet, 'reserve_usage', delayed)
    before = usage_wallet.report('EXAMPLE')['balance_pence']
    client = Mock()
    with chat_diagnostics.turn_scope('web', 'a'*24, 'same'), api_usage.usage_context('EXAMPLE', 'web'):
        with pytest.raises(AllowancePaused):
            api_usage.tracked_completion(client, purpose='planning', model='gpt-4o-mini')
    client.chat.completions.create.assert_not_called()
    wallet = usage_wallet.report('EXAMPLE')
    assert wallet['balance_pence'] == before and wallet['unknown_reservations'] == 0


def test_provider_timeout_is_accounted_once_and_logs_no_exception_content(ledger, caplog):
    client = Mock()
    client.chat.completions.create.side_effect = APITimeoutError(request=httpx.Request('POST', 'https://api.openai.com/v1/chat/completions'))
    with caplog.at_level('INFO'), chat_diagnostics.turn_scope('web', 'b'*24, 'PRIVATE_SESSION'), api_usage.usage_context('EXAMPLE', 'web'):
        with pytest.raises(APITimeoutError):
            api_usage.tracked_completion(client, purpose='conversation_answer', model='gpt-4o-mini')
    assert client.chat.completions.create.call_count == 1
    assert 'PRIVATE_SESSION' not in caplog.text
    assert '"error_type":"APITimeoutError"' in caplog.text
    assert api_usage.summary('EXAMPLE', 30)['totals']['calls'] == 1


@pytest.mark.parametrize('kind', ['clarification', 'refusal'])
def test_unrelated_faq_cannot_overwrite_conversational_model_reply(monkeypatch, kind):
    answer, _, _, _ = _structured_answer(monkeypatch, {
        'answer': 'Could you explain what you mean?' if kind == 'clarification' else 'I can help with this business, but not unrelated homework.',
        'kind': kind, 'sources': ['faq:setup'], 'statement_ids': ['faq:setup:answer']},
        question='What do you mean by that unusual word?',
        knowledge={'faq:setup': {'question':'How do I get started?', 'answer':'Your operator arranges onboarding. Install the embed snippet.'}})
    assert answer and 'onboarding' not in answer and 'embed' not in answer


def test_greeting_does_not_retrieve_or_call_provider(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    handler = MessageHandlerV7(SimpleNamespace())
    monkeypatch.setattr(handler, '_grounded_answer', lambda *a, **k: pytest.fail('Greeting must not retrieve or call a model'))
    assert handler.handle('hello', SimpleNamespace(channel='web'), {})['intent'] == 'greeting'


def test_filler_words_cannot_choose_an_onboarding_faq():
    from retrieval.faq_store import FAQStore
    store = FAQStore(faq=[{'q': 'Can you help with onboarding?', 'a': 'Install the embed snippet.', 'tags': []}])
    assert store.best_match('Can you help me with some') == []
    assert store.best_match('Can you help with onboarding?')


def test_timeout_fallback_uses_relevant_saved_knowledge_without_second_provider_call(ledger, monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from retrieval.faq_store import FAQStore
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    client = Mock()
    client.chat.completions.create.side_effect = APITimeoutError(request=httpx.Request('POST', 'https://api.openai.com'))
    handler = MessageHandlerV7(SimpleNamespace(
        faq=FAQStore(faq=[{'q':'What is your returns policy?', 'a':'Unused items can be returned within 30 days.', 'tags':['returns']},
                         {'q':'How do I get started?', 'a':'UNRELATED_ONBOARDING_COPY', 'tags':['setup']}]),
        rewriter=SimpleNamespace(_client=client, _model='gpt-4o-mini')))
    with api_usage.usage_context('EXAMPLE', 'web'):
        result = handler.handle('What is your returns policy?', SimpleNamespace(channel='web',tenant='EXAMPLE'), {})
    assert result['intent'] != 'system_error'
    assert '30 days' in result['reply'] and 'UNRELATED_ONBOARDING_COPY' not in result['reply']
    assert client.chat.completions.create.call_count == 1


def test_definitions_outlive_recent_messages_but_obey_clear_and_tenant_session_scope(app, client):
    settings = {'memory':{'enabled':True,'history_messages':2,'history_tokens':256,'retention_minutes':60}}
    app.container.storage.write_json('EXAMPLE','ai_model.json',settings)
    token = None
    for message in ['green means good','hello','hi','hello','does green = what?']:
        response = client.post('/chat_api',json={'tenant':'EXAMPLE','message':message,
            **({'conversation_token':token} if token else {})})
        assert response.status_code == 200
        token = response.json['conversation_token']
    assert response.json['reply'] == 'You said green = good.'
    fresh = app.test_client().post('/chat_api',json={'tenant':'EXAMPLE','message':'does green = what?'}).json
    assert 'good' not in fresh['reply']
    app.container.storage.write_json('EXAMPLE','ai_model.json',{**settings,'memory_generation':'cleared-in-test'})
    cleared = client.post('/chat_api',json={'tenant':'EXAMPLE','message':'does green = what?','conversation_token':token}).json
    assert 'good' not in cleared['reply']


def test_optional_faq_failure_does_not_break_known_business_answer(monkeypatch, caplog):
    from handlers.handler_v7 import MessageHandlerV7
    from service import grounded_conversation
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    faq = Mock()
    faq.best_match.side_effect = faq.all.side_effect = RuntimeError('PRIVATE_KNOWLEDGE_EXCEPTION')
    handler = MessageHandlerV7(SimpleNamespace(faq=faq,rewriter=SimpleNamespace(_client=object(),_model='gpt-4o-mini')))
    monkeypatch.setattr(grounded_conversation,'answer',lambda *a,**kw:'A grounded business answer.')
    with caplog.at_level('INFO'):
        response = handler._grounded_answer('What is the business?',{})
    assert response['reply'] == 'A grounded business answer.'
    assert 'PRIVATE_KNOWLEDGE_EXCEPTION' not in caplog.text
