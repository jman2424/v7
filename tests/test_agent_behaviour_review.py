"""Customer-language regressions and independently failing knowledge sources."""
import json
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from service import grounded_conversation
from service.conversation_turns import reply, unrelated_task


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    result = MessageHandlerV7(SimpleNamespace())
    result.sales_actions = {key: {'enabled': True} for key in ('consultation', 'quote', 'callback')}
    return result


@pytest.mark.parametrize('text', [
    'Can you explain your callback process?', 'I want to know about your consultation',
    'Why would I want a demo?', 'I am not sure I want a quote',
    'Maybe I need a consultation', 'How do I request a quote?',
    'Tell me about callback options', 'I need information about a quote',
    'If I wanted a quote later', 'Could you explain how callbacks work?',
])
def test_information_and_uncertainty_do_not_open_forms(handler, text):
    assert handler._conversion_action(text, 'web') is None


@pytest.mark.parametrize(('text', 'action'), [
    ('Can you get me a quote and do not call me back', 'quote'),
    ('How does pricing work? Please request a callback', 'callback'),
    ('I am not sure what I need, but please book a consultation', 'consultation'),
])
def test_separate_positive_action_still_works(handler, text, action):
    assert handler._conversion_action(text, 'web')[0] == action


@pytest.mark.parametrize('text', ['hi prices', 'hello refund', 'hey delivery', 'hi stock'])
def test_short_greeting_does_not_swallow_business_topic(handler, text):
    assert handler._is_greeting(text) is False
    seen = []
    handler._grounded_answer = lambda question, session, **kwargs: seen.append(question) or 'Here is the answer.'
    result = handler.handle(text, SimpleNamespace(channel='web'), {})
    assert result['intent'] == 'grounded_answer' and seen == [text]


@pytest.mark.parametrize('text', ['hello', 'hi there', 'good morning', 'hello team', 'helo'])
def test_real_greetings_remain_local(handler, text):
    assert handler._is_greeting(text)


@pytest.mark.parametrize('text', ['thanks', 'thank you very much', 'cheers', 'merci', 'gracias',
                                 'bye', "I'm good thanks", 'who are you', 'help', 'no thanks', 'not now'])
def test_simple_conversation_skips_provider_and_retrieval(handler, text):
    def unexpected(*args, **kwargs):
        pytest.fail('A short acknowledgement must not require model/retrieval calls')
    handler._grounded_answer = unexpected
    assert handler.handle(text, SimpleNamespace(channel='web'), {})['reply']


@pytest.mark.parametrize('text', ['Can you help me with my Python order?',
                                 'Help me connect your Python SDK',
                                 'Help me debug your widget integration'])
def test_business_integration_and_account_questions_reach_knowledge(text):
    assert unrelated_task(text) is False


@pytest.mark.parametrize('text', ['make a Python calculator', 'write a JavaScript game',
                                 'help me with Python homework', 'write me a poem',
                                 'Make a Python calculator for your API', 'write an essay about my order'])
def test_unrelated_artifacts_remain_out_of_scope(text):
    assert unrelated_task(text) is True


@pytest.mark.parametrize('question,missing', [
    ('what does green stand for?',None),('what did green mean again?',None),
    ('remind me what green means',None),
    ('what did I tell you about green?',"I don't have that detail available in this conversation. Could you tell me again?")])
def test_natural_recall_uses_current_customer_definition(question,missing):
    facts = {}
    assert reply('green = good', [], facts=facts)
    assert reply(question, [], facts=facts) == 'You said green = good.'
    assert reply(question, [], facts={}) == missing
    assert reply(question, [], {'enabled': False}, facts=facts) == missing


@pytest.mark.parametrize('question', ['How much will a bespoke website cost?',
                                     'Explain the quote process', 'No thanks, no quote'])
def test_model_cannot_turn_information_or_refusal_into_quote_form(monkeypatch, question):
    payload = {'kind': 'answer', 'answer': 'Pricing depends on scope; the team reviews quote requests.',
               'sources': ['policy:quote'], 'statement_ids': ['policy:quote:answer'],
               'navigation': [], 'requested_action': 'quote', 'agent': {
                   'intent': 'quote', 'stage': 'convert', 'next_action': 'open_request_form',
                   'offering_ids': [], 'selected_offering_id': None, 'requirements': []}}
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', lambda *args, **kwargs:
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]))
    state = {}
    answer = grounded_conversation.answer(object(), 'test-model', question,
        {'policy:quote': {'answer': 'Pricing depends on scope; the team reviews quote requests.'}},
        [], 'professional', allowed_actions=['quote'], agent_state=state)
    assert answer and 'Pricing depends on scope' in answer
    assert 'requested_action' not in state
    assert state['next_action'] == 'await_customer_question'
    assert 'Open the quote request form' not in answer


@pytest.mark.parametrize('failed_source', ['catalog_search', 'catalog_preview', 'delivery', 'branches', 'offers', 'business_core', 'currency'])
def test_optional_source_failure_keeps_other_public_knowledge(handler, monkeypatch, caplog, failed_source):
    def broken(*args, **kwargs):
        raise RuntimeError('PRIVATE provider body sk-proj-do-not-log-this-value')
    product = {'sku': 'basic', 'name': 'Basic', 'price': 20}
    handler.rewriter = SimpleNamespace(_client=object(), _model='test-model')
    handler.catalog = SimpleNamespace(
        search=broken if failed_source == 'catalog_search' else lambda **kwargs: [product],
        list_all_items=broken if failed_source == 'catalog_preview' else lambda: [product],
        get_item_by_sku=lambda sku: product, currency=broken if failed_source == 'currency' else lambda: 'GBP')
    if failed_source == 'delivery':
        handler.policy = SimpleNamespace(delivery_notes=broken)
    if failed_source == 'branches':
        handler.geo = SimpleNamespace(branches=broken)
    if failed_source == 'offers':
        handler.offers = SimpleNamespace(active=broken)
    if failed_source == 'business_core':
        handler.business_core = SimpleNamespace(public_context=broken)
    seen = []
    def answer(*args, **kwargs):
        seen.append(args[3])
        return 'Here is the available business information.'
    monkeypatch.setattr(grounded_conversation, 'answer', answer)
    with caplog.at_level('INFO', logger='Chat.Diagnostics'):
        # Broad discovery uses the preview fallback; a focused match now
        # deliberately avoids that unnecessary read altogether.
        question = 'Tell me about Basic and browse all services' if failed_source == 'catalog_preview' else 'Tell me about Basic'
        result = handler._grounded_answer(question, {}, channel='web')
    assert result['reply'] and seen[0]['product:basic']['name'] == 'Basic'
    assert 'chat_optional_failure' in caplog.text
    assert 'PRIVATE' not in caplog.text and 'sk-proj-' not in caplog.text
    if failed_source == 'delivery':
        assert 'delivery' not in seen[0]
    if failed_source == 'currency':
        assert 'price' not in seen[0]['product:basic']


def test_focused_match_does_not_fetch_entire_catalogue(handler, monkeypatch):
    handler.rewriter = SimpleNamespace(_client=object(), _model='test-model')
    product = {'sku': 'basic', 'name': 'Basic', 'price': 20}
    def unnecessary():
        pytest.fail('A focused match must not fetch the catalogue preview')
    handler.catalog = SimpleNamespace(search=lambda **kwargs: [product], list_all_items=unnecessary,
        get_item_by_sku=lambda sku: product, currency=lambda: 'GBP')
    # Isolate the retrieval fallback from the separate local exact-name
    # resolver, which may inspect the already-loaded catalogue index.
    monkeypatch.setattr(handler, '_exact_catalog_item_in_text', lambda *args, **kwargs: product)
    seen = []
    monkeypatch.setattr(grounded_conversation, 'answer', lambda *args, **kwargs:
        seen.append(args[3]) or 'Basic is available in the published catalogue.')
    assert handler._grounded_answer('Tell me about Basic', {}, channel='web')['reply']
    assert seen[0]['product:basic']['price'] == 20


def test_missing_faq_rows_and_render_failure_do_not_crash_chat(handler, caplog):
    def broken(*args):
        raise RuntimeError('PRIVATE response body')
    handler.faq = SimpleNamespace(best_match=lambda *args, **kwargs: [{'q': 'Question', 'a': 'Answer'}],
                                  all=lambda: None, render_answer=broken)
    with caplog.at_level('INFO', logger='Chat.Diagnostics'):
        assert handler._optional_faq_rows() == []
        assert handler._find_faq('Question', {}, request_id='test') is None
    assert 'faq_retrieval' in caplog.text and 'faq_render' in caplog.text
    assert 'PRIVATE' not in caplog.text


def test_explicit_callback_is_not_lost_to_wrong_model_intent(monkeypatch):
    payload = {'kind': 'answer', 'answer': 'The callback form lets the team review your request.',
               'sources': ['capability:request:callback'], 'navigation': [],
               'requested_action': 'callback', 'agent': {
                   'intent': 'quote', 'stage': 'assist', 'next_action': 'open_request_form',
                   'offering_ids': [], 'selected_offering_id': None, 'requirements': []}}
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', lambda *args, **kwargs:
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]))
    state = {}
    answer = grounded_conversation.answer(object(), 'test-model', 'Please call me back about my website.',
        {'business': {'name': 'Example studio'}}, [], 'professional',
        allowed_actions=['callback'], agent_state=state)
    assert answer and state['requested_action'] == 'callback'
    assert state['intent'] == 'handoff' and state['next_action'] == 'open_request_form'
