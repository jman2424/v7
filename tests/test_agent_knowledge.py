"""Current customer tasks retain relevant public facts under bounded context."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from service import grounded_conversation
from service.agent_knowledge import prioritize_knowledge
from service.business_core import BusinessCore, empty_core


def test_new_product_and_policy_facts_survive_large_website_context(monkeypatch):
    knowledge = {f'website:{index}': {'text': 'Unrelated background. ' * 150}
                 for index in range(30)}
    knowledge.update({'business': {'name': 'Fixture retailer'},
                      'product:quiet': {'name': 'Quiet office fan', 'price': 59, 'currency': 'GBP'},
                      'faq:returns': {'question': 'How do returns work?', 'answer': 'Return within 14 days.'}})
    seen = []
    def complete(*args, **kwargs):
        seen.append(json.loads(kwargs['messages'][1]['content']))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'kind': 'answer', 'answer': 'The Quiet office fan is £59. Return within 14 days.',
            'sources': ['product:quiet', 'faq:returns'],
        })))])
    monkeypatch.setattr(grounded_conversation, 'tracked_completion', complete)
    result = grounded_conversation.answer(Mock(), 'test-model',
        'What does the quiet office fan cost, and how do returns work?', knowledge, [], 'professional')
    assert result == 'The Quiet office fan is £59. Return within 14 days.'
    assert 'product:quiet' in seen[0]['knowledge'] and 'faq:returns' in seen[0]['knowledge']
    assert len(json.dumps(seen[0]['knowledge'], ensure_ascii=False)) <= 32000


def test_current_policy_beats_unrelated_prior_product_facts():
    knowledge = {'website:0': {'text': 'The gold package provides support and design.'},
                 'product:gold': {'name': 'Gold package'},
                 'faq:cancel': {'question': 'How can I cancel?', 'answer': 'Use account settings.'},
                 'business': {'name': 'Fixture business'}}
    ranked = list(prioritize_knowledge(knowledge, 'How can I cancel?', {}))
    assert ranked.index('faq:cancel') < ranked.index('website:0')
    assert ranked.index('faq:cancel') < ranked.index('product:gold')


def test_large_native_catalogue_keeps_current_and_remembered_offerings(monkeypatch):
    core = empty_core()
    core['offerings'] = [{'id': f'package-{index}', 'name': f'Package {index}', 'active': True}
                         for index in range(80)]
    core['offerings'] += [{'id': 'acoustic', 'name': 'Acoustic survey', 'active': True},
                          {'id': 'hidden', 'name': 'Acoustic secret', 'active': False}]
    core['work'] = [{'private': 'customer invoice and internal notes'}]
    business = BusinessCore(SimpleNamespace(tenant_exists=lambda tenant: tenant == 'ALPHA'), 'ALPHA')
    monkeypatch.setattr(business, 'document', lambda: core)
    rows = business.public_context(query='I need an acoustic survey', selected_ids=['package-79'])
    assert [row['id'] for row in rows['offerings'][:2]] == ['package-79', 'acoustic']
    assert 'hidden' not in {row['id'] for row in rows['offerings']}
    assert 'private' not in json.dumps(rows) and 'work' not in rows
    assert business.public_context()['offerings'][0]['id'] == 'package-0'


def test_policy_lookup_does_not_retrieve_old_assistant_pricing_vocabulary(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    handler = MessageHandlerV7(SimpleNamespace(rewriter=SimpleNamespace(_client=object(), _model='test-model')))
    handler.website_knowledge = {'pages': [
        {'url': 'https://fixture.example/pricing', 'title': 'Plans',
         'text': '\n'.join('Gold silver monthly annual subscription plan features upgrades pricing.' for _ in range(30))},
        {'url': 'https://fixture.example/cancel', 'title': 'Cancel',
         'text': 'Cancel future renewal from your account settings. Your access lasts until the period ends.'},
    ]}
    seen = []
    monkeypatch.setattr(grounded_conversation, 'answer', lambda *args, **kwargs: seen.append(args[3]))
    handler._grounded_answer('How can I cancel?', {'conversation_history': [
        {'role': 'assistant', 'content': 'Gold silver monthly annual subscription plan features upgrades pricing.'}]})
    pages = [row for key, row in seen[0].items() if key.startswith('website:')]
    assert pages and all(row['url'] == 'https://fixture.example/cancel' for row in pages)


def test_policy_interruption_can_recover_a_shortlist_outside_catalogue_preview(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from retrieval.catalog_store import CatalogStore
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    catalog = CatalogStore(catalog={'categories': [{'id': 'packages', 'name': 'Packages', 'items': [
        {'sku': f'pack-{index}', 'name': f'Package {index}', 'price': index + 1}
        for index in range(75)]}]})
    handler = MessageHandlerV7(SimpleNamespace(catalog=catalog,
        rewriter=SimpleNamespace(_client=object(), _model='test-model')))
    seen = []
    monkeypatch.setattr(grounded_conversation, 'answer', lambda *args, **kwargs: seen.append(args[3]))
    handler._grounded_answer('The second one', {'sales_agent': {
        'offering_ids': ['product:pack-74'],
        'last_offering_ids': ['product:pack-73', 'product:pack-74']}})
    assert seen[0]['product:pack-73']['price'] == 74
    assert seen[0]['product:pack-74']['price'] == 75
