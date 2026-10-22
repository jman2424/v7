"""Readability must not change prices, policy conditions or follow-up indices."""
from unittest.mock import Mock

import pytest

from ai_modes.contracts import safe_minimal_rewrite
from renderer_v7 import RendererV7
from service.reply_formatting import readable_reply
from service.rewriter import Rewriter


@pytest.mark.parametrize('scope,count', [('top_picks', 3), ('item_list', 3),
                                         ('full_store', 5), ('full_category', 5)])
def test_catalogue_pages_are_short_and_numbered_on_separate_lines(scope, count):
    facts = catalogue(scope)
    result = render(facts)
    lines = result.splitlines()
    assert [line.split(')')[0] for line in lines if line[:1].isdigit()] == [str(i) for i in range(1, count + 1)]
    assert f'Option {count + 1} ' not in result
    assert result.count('final quote on inspection') == 1
    assert f'Option {count} (starting price) – £{100 + count:.2f}' in result
    assert '\n\n' in result


def catalogue(scope='top_picks'):
    return {'items': [{'sku': f'ITEM_{i}', 'name': f'Option {i} (starting price)',
                       'price': 100 + i, 'unit': 'vehicle; starting price, final quote on inspection'}
                      for i in range(1, 13)],
            'search_meta': {'scope': scope, 'max_items': 20}, 'currency': 'GBP'}


def render(facts):
    return RendererV7(offering_type='services', max_sentences=1).render(
        user_text='Show services', plan={'intent': 'search_product', 'action': 'SEARCH_PRODUCTS'},
        facts=facts, session={})


def test_short_units_and_different_conditions_stay_with_their_own_price():
    facts = catalogue()
    facts['items'][0]['unit'] = 'hour'
    facts['items'][1]['unit'] = 'visit; minimum two visits required'
    result = render(facts)
    assert 'Option 1 (starting price) (hour) – £101.00' in result
    assert 'minimum two visits required' in result
    assert 'final quote on inspection' in result


def test_prose_breaks_preserve_every_word_decimal_url_and_condition():
    text = ('The quoted starting price is £250.50 and applies only after a team inspection. '
            'Remote locations and heavily soiled vehicles require an individual quotation before work starts. '
            'The full manufacturer warranty requires a professional maintenance visit at least every six weeks. '
            'Check https://business.example/policy or email support@business.example before choosing a date. '
            'A request is not a confirmed appointment and no payment has been taken.')
    result = readable_reply(text)
    assert '\n\n' in result
    assert result.split() == text.split()
    assert readable_reply(result) == result


def test_existing_lists_and_fenced_code_are_not_flattened_or_interpreted():
    text = ('Your options:\n\n1) Small — £100.25\n2) Large — £200.50\n\n'
            '```python\nif ready:\n    print("<script>alert(1)</script>")\n\n    finish()\n```')
    assert readable_reply(text) == text
    assert safe_minimal_rewrite(text) == text
    rewriter = Rewriter(max_chars=50)
    rewriter._client = Mock()
    assert rewriter.rewrite(text) == text
    rewriter._client.chat.completions.create.assert_not_called()


def test_final_api_reply_and_memory_keep_paragraphs(app, client, monkeypatch):
    handler = app.container.for_tenant('EXAMPLE').handler
    text = 'Options:\n\n1) Starter — £99\n2) Business — £199\n\nAI usage credit is separate.'
    monkeypatch.setattr(handler, '_guard_input', lambda *args, **kwargs: {
        'reply': text, 'intent': 'system_clarify'})
    response = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'SYNTHETIC formatting check'})
    assert response.status_code == 200
    assert text in response.json['reply']
    history = handler.memory.get(response.json['session_id'], 'conversation_history')
    assert history[-1]['content'] == response.json['reply']


def test_only_displayed_catalogue_choices_enter_numbered_followup_memory(app):
    from service.message_handler import MessageContext
    handler = app.container.for_tenant('EXAMPLE').handler
    ctx = MessageContext(tenant='EXAMPLE', session_id='SYNTHETIC_FORMATTING', channel='test', metadata={})
    facts = catalogue()
    handler._save_session(ctx, {}, {'reply': render(facts), 'facts': facts, 'entities': {}})
    assert handler.memory.get(ctx.session_id, 'last_items') == ['ITEM_1', 'ITEM_2', 'ITEM_3']
    assert len(handler.memory.get(ctx.session_id, 'last_product_names')) == 3


def test_comparisons_offers_and_alternatives_have_separate_entries():
    renderer = RendererV7(max_sentences=1)
    items = catalogue()['items'][:2]
    assert '\n\n' in renderer._comparison_reply({'comparison': {'items': items}})
    alternatives = renderer._alternatives_reply({'unavailable_product': {'name': 'Original'}, 'items': items})
    assert '\n• Option 2' in alternatives
    offers = renderer._offers_reply({'offers': {'items': [
        {'title': 'First', 'description': 'Existing customers only.', 'code': 'FIRST'},
        {'title': 'Second', 'description': 'New customers only.', 'code': 'SECOND'},
    ]}})
    assert '\n\n• Second' in offers and 'FIRST' in offers and 'SECOND' in offers
