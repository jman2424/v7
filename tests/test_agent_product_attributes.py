"""Customer-visible product attributes reach grounded answers without private metadata."""
import json
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from retrieval.catalog_store import CatalogStore
from service import grounded_conversation


def _handler(monkeypatch, items):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    catalog = CatalogStore(catalog={'currency': 'GBP', 'categories': [
        {'id': 'outdoor', 'name': 'Outdoor', 'items': items},
    ]})
    return MessageHandlerV7(SimpleNamespace(catalog=catalog,
        rewriter=SimpleNamespace(_client=object(), _model='test-model')))


def _provider(monkeypatch, source='product:tent', *, agent=None):
    seen = []

    def complete(*args, **kwargs):
        seen.append(json.loads(kwargs['messages'][1]['content']))
        payload = {'kind': 'answer', 'answer': 'The catalog lists this tent.', 'sources': [source]}
        if agent is not None:
            payload['agent'] = agent
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    return seen


def test_grounded_provider_receives_public_product_options_and_quantity(monkeypatch):
    handler = _handler(monkeypatch, [
        {'sku': 'tent', 'name': 'Family Tent', 'price': 79, 'in_stock': True,
         'stock_quantity': 7, 'tags': [' camping ', 'waterproof', 'camping',
                                     {'internal_notes': 'tag-secret'}],
         'options': [{'name': ' Size ', 'value': ' Four person ', 'internal_notes': 'option-secret'},
                     {'name': 'Colour', 'value': 'Blue', 'supplier': {'token': 'nested-secret'}},
                     {'name': 'Internal', 'value': 'hidden-option', 'public': False},
                     {'name': 'Old', 'value': 'inactive-option', 'active': False},
                     {'name': 'Unsafe', 'value': {'password': 'object-secret'}}, 'invalid'],
         'internal_notes': 'product-secret', 'low_stock_threshold': 5},
        {'sku': 'hidden', 'name': 'hidden-product', 'price': 1, 'public': False},
        {'sku': 'inactive', 'name': 'inactive-product', 'price': 1, 'active': False},
    ])
    seen = _provider(monkeypatch)
    result = handler._grounded_answer('Which sizes and colours does the Family Tent have?', {})
    assert result and result['reply'] == 'The catalog lists this tent.'
    facts = seen[0]['knowledge']['product:tent']
    assert facts['tags'] == ['camping', 'waterproof']
    assert facts['options'] == [{'name': 'Size', 'value': 'Four person'},
                                {'name': 'Colour', 'value': 'Blue'}]
    assert facts['stock_quantity'] == 7 and facts['in_stock'] is True
    assert facts['price'] == 79 and facts['currency'] == 'GBP'
    encoded = json.dumps(seen)
    for private in ('secret', 'hidden-option', 'inactive-option', 'hidden-product',
                    'inactive-product', 'low_stock_threshold', 'internal_notes', 'supplier'):
        assert private not in encoded


@pytest.mark.parametrize('stock_fields,expected_quantity,expected_stock', [
    ({}, None, None),
    ({'in_stock': True}, None, True),
    ({'in_stock': False}, None, False),
    ({'in_stock': 'true', 'stock_quantity': '7'}, None, None),
    ({'in_stock': 1, 'stock_quantity': True}, None, None),
    ({'stock_quantity': None}, None, None),
    ({'stock_quantity': -1}, None, None),
    ({'stock_quantity': float('inf')}, None, None),
    ({'stock_quantity': float('nan')}, None, None),
    ({'stock_quantity': 10 ** 1000}, None, None),
    ({'stock_quantity': 2.5}, 2.5, None),
    ({'in_stock': True, 'stock_quantity': 0}, 0, False),
    ({'in_stock': False, 'stock_quantity': 9}, 9, False),
])
def test_stock_facts_are_typed_and_never_default_unknown_to_available(
        monkeypatch, stock_fields, expected_quantity, expected_stock):
    handler = _handler(monkeypatch, [
        {'sku': 'tent', 'name': 'Family Tent', 'price': 79, **stock_fields},
    ])
    seen = _provider(monkeypatch)
    assert handler._grounded_answer('Is the Family Tent in stock?', {})
    facts = seen[0]['knowledge']['product:tent']
    assert facts.get('stock_quantity') == expected_quantity
    assert facts['in_stock'] is expected_stock
    if expected_quantity is None:
        assert 'stock_quantity' not in facts


def test_product_attribute_collections_and_strings_are_bounded(monkeypatch):
    handler = _handler(monkeypatch, [
        {'sku': 'tent', 'name': 'Family Tent', 'price': 79,
         'tags': [f'{index}-' + 'x' * 300 for index in range(100)],
         'options': [{'name': f'{index}-' + 'n' * 300, 'value': 'v' * 500}
                     for index in range(100)]},
    ])
    seen = _provider(monkeypatch)
    assert handler._grounded_answer('What options does the Family Tent have?', {})
    facts = seen[0]['knowledge']['product:tent']
    assert len(facts['tags']) == 20 and all(len(tag) <= 80 for tag in facts['tags'])
    assert len(facts['options']) == 20
    assert all(len(option['name']) <= 80 and len(option['value']) <= 160
               for option in facts['options'])
    assert len(json.dumps(seen[0]['knowledge'], ensure_ascii=False)) <= 32000


@pytest.mark.parametrize('stock,expected', [
    (None, None), ('', None), ('Unknown', None), ('Pending', None),
    ('In Stock', True), ('Available', True), ('Out of Stock', False), ('Sold Out', False),
])
def test_legacy_catalogue_preserves_unknown_stock_through_grounding(monkeypatch, stock, expected):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    item = {'name': 'Family Tent', 'price_str': '£79'}
    if stock is not None:
        item['stock'] = stock
    catalog = CatalogStore(catalog={'product_catalog': [{'name': 'Outdoor', 'items': [item]}]})
    handler = MessageHandlerV7(SimpleNamespace(catalog=catalog,
        rewriter=SimpleNamespace(_client=object(), _model='test-model')))
    source = 'product:' + catalog.list_all_items()[0]['sku']
    seen = _provider(monkeypatch, source)
    assert handler._grounded_answer('Is the Family Tent in stock?', {})
    assert seen[0]['knowledge'][source]['in_stock'] is expected
    assert catalog.in_stock(source.removeprefix('product:')) is expected


@pytest.mark.parametrize('legacy', [True, False])
def test_unknown_stock_fallback_answers_price_without_claiming_unavailable(monkeypatch, legacy):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    raw = ({'product_catalog': [{'name': 'Outdoor', 'items': [
        {'name': 'Family Tent', 'price_str': '£79'}]}]} if legacy else
        {'categories': [{'id': 'outdoor', 'name': 'Outdoor', 'items': [
            {'sku': 'tent', 'name': 'Family Tent', 'price': 79}]}]})
    handler = MessageHandlerV7(SimpleNamespace(catalog=CatalogStore(catalog=raw)))
    handler.brain.client = None
    result = handler.handle('How much is the Family Tent?',
        SimpleNamespace(tenant='EXAMPLE', session_id='unknown-stock', channel='web'), {})
    assert result['intent'] == 'price_check'
    assert result['facts']['price']['in_stock'] is None
    assert '79.00' in result['reply']
    assert 'availability needs confirmation' in result['reply']
    assert 'out of stock' not in result['reply']


def test_comparison_does_not_convert_unknown_availability_to_out_of_stock():
    from renderer_v7 import RendererV7

    reply = RendererV7()._comparison_reply({'comparison': {'items': [
        {'name': 'Basic', 'price': 10, 'in_stock': None},
        {'name': 'Pro', 'price': 20, 'in_stock': True},
    ]}})
    assert 'Basic: £10.00, availability needs confirmation' in reply
    assert 'Pro: £20.00, in stock' in reply


def test_selected_product_outside_preview_keeps_options_across_follow_up(monkeypatch):
    items = [{'sku': f'tent-{index}', 'name': f'Tent {index}', 'price': 79,
              'options': [{'name': 'Size', 'value': f'Size {index}'}]}
             for index in range(75)]
    handler = _handler(monkeypatch, items)
    agent = {'intent': 'recommend', 'stage': 'recommend', 'next_action': 'recommend_option',
             'offering_ids': ['product:tent-74'], 'selected_offering_id': 'product:tent-74',
             'requirements': []}
    seen = _provider(monkeypatch, 'product:tent-74', agent=agent)
    result = handler._grounded_answer('The second one', {'sales_agent': {
        'offering_ids': ['product:tent-73', 'product:tent-74'],
        'selected_offering_id': 'product:tent-73',
    }})
    assert result and result['agent']['selected_offering_id'] == 'product:tent-74'
    assert seen[0]['knowledge']['product:tent-74']['options'] == [{'name': 'Size', 'value': 'Size 74'}]
    follow_up = handler._grounded_answer('What size is it?', {'sales_agent': result['agent']})
    assert follow_up and follow_up['agent']['selected_offering_id'] == 'product:tent-74'
    assert seen[1]['agent_context']['selected_offering_id'] == 'product:tent-74'
    assert seen[1]['knowledge']['product:tent-74']['options'] == [{'name': 'Size', 'value': 'Size 74'}]
