import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service import api_usage, grounded_conversation, usage_wallet
from service.plan_usage import AllowancePaused
from tests.test_api_usage import completion, fake_exchange, ledger


KNOWLEDGE = {'product:basic': {'name': 'Basic', 'price': 99, 'currency': 'GBP'},
             'faq:cancel': {'answer': 'Cancel future renewal through subscription settings.'}}


def client_for(text, sources):
    client = Mock()
    client.chat.completions.create.return_value = completion(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps({'answer': text, 'kind': 'answer', 'sources': sources})))])
    return client


def ask(client, tenant='EXAMPLE', question='How much?', history=None):
    with api_usage.usage_context(tenant, 'test', 'v7'):
        return grounded_conversation.answer(client, 'gpt-4o-mini', question,
                                            KNOWLEDGE, history or [], 'professional')


def test_funded_answer_uses_accounted_provider_and_only_its_tenant(ledger):
    other = usage_wallet.report('BETA')['balance_pence']
    client = client_for('Basic is £99. Cancellation is managed in settings.', ['product:basic', 'faq:cancel'])
    assert ask(client).startswith('Basic is £99.')
    assert api_usage.summary('EXAMPLE', 30)['totals']['total_tokens'] == 2500
    assert api_usage.summary('BETA', 30)['totals']['calls'] == 0
    assert usage_wallet.report('BETA')['balance_pence'] == other
    assert usage_wallet.report('EXAMPLE')['spent_pence'] > 0


def test_empty_credit_skips_provider_and_suppresses_more_calls_this_turn(ledger):
    client = client_for('Basic is £99.', ['product:basic'])
    with api_usage.usage_context('EMPTY', 'test', 'v7'):
        assert grounded_conversation.answer(client, 'gpt-4o-mini', 'How much?', KNOWLEDGE, [], 'friendly') is None
        with pytest.raises(AllowancePaused, match='saved_knowledge_only_for_turn'):
            api_usage.tracked_completion(client, purpose='planning', model='gpt-4o-mini')
    client.chat.completions.create.assert_not_called()
    assert ask(client, 'BETA') == 'Basic is £99.'


@pytest.mark.parametrize('text,sources', [
    ('Basic costs £500.', ['product:basic']),
    ('Basic costs $99.', ['product:basic']),
    ('Use https://evil.test/pay', ['product:basic']),
    ('I have cancelled your subscription.', ['faq:cancel']),
    ('Another company offers this.', ['other-company']),
    ('Basic includes everything.', []),
])
def test_unsafe_claims_are_rejected_after_accounting(ledger, text, sources):
    assert ask(client_for(text, sources)) is None
    assert api_usage.summary('EXAMPLE', 30)['totals']['calls'] == 1


def test_follow_up_includes_bounded_recent_conversation(ledger):
    history = [{'role': 'assistant', 'content': '1) Basic — £99 per month.'},
               {'role': 'user', 'content': 'option 1'}]
    client = client_for('The first option is Basic at £99 per month.', ['product:basic'])
    assert ask(client, question="What's the first option do?", history=history)
    payload = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
    assert payload['recent_conversation'] == history
    assert payload['question'] == "What's the first option do?"


def test_provider_failure_returns_fallback_without_exposing_error(ledger):
    client = client_for('', [])
    client.chat.completions.create.side_effect = RuntimeError('private provider failure')
    assert ask(client) is None


def test_handler_prefers_grounded_answer_over_delivery_and_catalogue(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    handler = MessageHandlerV7(SimpleNamespace())
    monkeypatch.setattr(handler, '_grounded_answer', lambda question, session: 'Prepare your products and delivery policies.')
    result = handler.handle('What should I prepare for delivery policies?',
                            SimpleNamespace(tenant='EXAMPLE', channel='test'), {})
    assert result['intent'] == 'grounded_answer'
    assert 'postcode' not in result['reply']


def test_knowledge_excludes_private_catalogue_fields(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from retrieval.catalog_store import CatalogStore
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    catalog = CatalogStore(catalog={'categories': [{'id': 'services', 'name': 'Services', 'items': [
        {'sku': 'basic', 'name': 'Basic', 'price': 99, 'api_key': 'private-key', 'internal_notes': 'private'},
        {'sku': 'hidden', 'name': 'Hidden', 'price': 500, 'public': False},
    ]}]})
    handler = MessageHandlerV7(SimpleNamespace(catalog=catalog, rewriter=SimpleNamespace(_client=object(), _model='gpt-4o-mini')))
    seen = []
    monkeypatch.setattr(grounded_conversation, 'answer', lambda *args, **kwargs: seen.append(args[3]))
    handler._grounded_answer('Basic', {})
    encoded = json.dumps(seen)
    assert 'private-key' not in encoded and 'internal_notes' not in encoded
    assert 'Hidden' not in encoded
