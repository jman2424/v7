"""A tenant's exact pricing policy works without replacing current catalog facts."""
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from retrieval.catalog_store import CatalogStore
from retrieval.faq_store import FAQStore


@pytest.fixture
def software_assistant(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    faqs = [
        {'q': 'What is MarketDesk?', 'a': 'MarketDesk is a configurable website assistant.'},
        {'q': 'Who is MarketDesk for?', 'a': 'It supports retailers and service businesses.'},
        {'q': 'How much does MarketDesk cost?', 'a': 'Contact the team for confirmed pricing.'},
        {'q': 'Can I add MarketDesk to my website?', 'a': 'Configure approved website origins before embedding the widget.'},
        {'q': 'Does MarketDesk support WhatsApp?', 'a': 'WhatsApp requires a configured provider connection.'},
        {'q': 'How can I request a demo?', 'a': 'Contact our team to discuss your business needs.'},
    ]
    return MessageHandlerV7(SimpleNamespace(
        catalog=CatalogStore(catalog={'version': 1, 'categories': []}),
        faq=FAQStore(faq=faqs), business_name='MarketDesk',
        business_profile={'name': 'MarketDesk', 'about': 'A configurable website assistant.'},
    ))


def reply(assistant, text):
    return assistant.handle(text, SimpleNamespace(tenant='SOFTWARE', session_id='test', channel='web'), {})


@pytest.mark.parametrize('question', ['How much does MarketDesk cost?', 'HOW MUCH DOES MarketDesk COST', 'How much does MarketDesk cost.'])
def test_exact_pricing_faq_answers_an_empty_catalog_without_an_ai_provider(software_assistant, question):
    result = reply(software_assistant, question)
    assert result['intent'] == 'faq'
    assert result['reply'] == 'Contact the team for confirmed pricing.'
    assert result['facts']['faq']['question'] == 'How much does MarketDesk cost?'
    assert result['ui']['catalog_items'] == []


@pytest.mark.parametrize('in_stock,expected_intent', [(True, 'price_check'), (False, 'unavailable_product')])
def test_named_catalog_price_and_availability_precede_a_conflicting_exact_faq(software_assistant, in_stock, expected_intent):
    software_assistant.catalog = CatalogStore(catalog={'version': 1, 'currency': 'USD', 'categories': [
        {'id': 'bags', 'name': 'Bags', 'items': [
            {'sku': 'PACK', 'name': 'Canvas Pack', 'price': 149, 'unit': 'each', 'in_stock': in_stock, 'tags': []},
        ]},
    ]})
    software_assistant.faq = FAQStore(faq=[{'q': 'How much is Canvas Pack?', 'a': 'A stale answer says it costs USD 1.'}])
    result = reply(software_assistant, 'How much is Canvas Pack?')
    assert result['intent'] == expected_intent
    assert 'stale answer' not in result['reply']
    if in_stock:
        assert result['facts']['price']['price'] == 149
        assert '$149.00' in result['reply']
    else:
        assert result['facts']['unavailable_product']['in_stock'] is False


def test_fuzzy_pricing_faq_does_not_override_an_explicit_shopping_question(software_assistant):
    result = reply(software_assistant, 'What is the MarketDesk price?')
    assert result['intent'] != 'faq'
    assert result['reply'] != 'Contact the team for confirmed pricing.'


def test_public_widget_uses_the_saved_exact_pricing_faq_with_no_provider(client, software_assistant):
    container = client.application.container
    storage = container.storage
    storage.write_json('EXAMPLE', 'catalog.json', {'version': 1, 'categories': []})
    storage.write_json('EXAMPLE', 'faq.json', [
        {'q': item['q'], 'a': item['a']} for item in software_assistant.faq.all()
    ])
    storage.write_json('EXAMPLE', 'store_info.json', {
        'name': 'MarketDesk', 'about': 'A configurable website assistant.',
    })
    container.invalidate_tenant('EXAMPLE')
    result = client.post('/chat_api', json={
        'tenant': 'EXAMPLE', 'message': 'How much does MarketDesk cost?',
    })
    assert result.status_code == 200
    assert result.json.get('error') is None
    assert 'Contact the team for confirmed pricing.' in result.json['reply']
