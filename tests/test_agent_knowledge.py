"""Current customer tasks retain relevant public facts under bounded context."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from service import grounded_conversation
from service.agent_knowledge import prioritize_knowledge, displayed_catalogue_ids
from service.business_core import BusinessCore, empty_core


def test_priced_faq_list_binds_only_unique_current_public_currency_and_name_matches():
    knowledge = {
        'product:entry-small':{'name':'Entry 2-Year Ceramic Coating Small starting price','price':250,'currency':'GBP'},
        'product:entry-large':{'name':'Entry 2-Year Ceramic Coating Large starting price','price':300,'currency':'GBP'},
        'product:premium-large':{'name':'Premium 3-Year Ceramic Coating Large starting price','price':350,'currency':'GBP'},
        'product:signature-large':{'name':'Signature 5-Year Ceramic Coating Large starting price','price':400,'currency':'GBP'}}
    text = '• Entry 2-Year Ceramic Coating: £300\n\n• Premium 3-Year Ceramic Coating: £350\n\n• Signature 5-Year Ceramic Coating: £400'
    assert displayed_catalogue_ids(text,knowledge)==['product:entry-large','product:premium-large','product:signature-large']
    assert displayed_catalogue_ids(text.replace('£350','$350'),knowledge)==[]
    assert displayed_catalogue_ids(text.replace('£400','£401'),knowledge)==[]
    assert displayed_catalogue_ids('```\n'+text+'\n```',knowledge)==[]
    assert displayed_catalogue_ids('````\n```\n'+text+'\n````',knowledge)==[]
    assert displayed_catalogue_ids(text,{**knowledge,'product:ambiguous':{
        'name':'Entry 2-Year Ceramic Coating Medium starting price','price':300,'currency':'GBP'}})==[]
    assert displayed_catalogue_ids(text,{**knowledge,'product:entry-large':{
        **knowledge['product:entry-large'],'public':False}})==[]
    assert displayed_catalogue_ids(text,{**knowledge,'product:entry-large':{
        **knowledge['product:entry-large'],'currency':None}})==[]


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
    assert 'Quiet office fan: £59.00.' in result
    assert result.endswith('Return within 14 days.')
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


def test_narrow_question_does_not_send_the_whole_catalogue_and_faq_collection():
    knowledge = {'business': {'name': 'Fixture'},
                 **{f'product:{i}': {'name': f'Unrelated package {i}', 'price': i} for i in range(80)},
                 'faq:location': {'question': 'Where are you located?', 'answer': 'Mobile service in London.'}}
    ranked = prioritize_knowledge(knowledge, 'Where are you located?', {})
    assert 'faq:location' in ranked and len(ranked) <= 24


def test_costs_and_pricing_share_retrieval_vocabulary_without_weakening_claim_checks():
    knowledge = {'business':{'name':'Fixture'},
                 **{f'faq:{i}':{'question':f'Background {i}','answer':'Unrelated information.'} for i in range(40)},
                 'faq:price':{'question':'What are the ceramic coating prices?',
                              'answer':'Small GBP 250, Medium GBP 275, Large GBP 300.'},
                 'faq:size':{'question':'How are SUVs sized?','answer':'A BMW X3 uses Large.'}}
    ranked = prioritize_knowledge(knowledge,'if i have a bmw x3 whats the costs',{})
    assert 'faq:price' in ranked and 'faq:size' in ranked


def test_variant_price_matches_cannot_crowd_out_public_classification_guide():
    knowledge={'business':{'name':'Fixture'},**{f'product:{i}':{
        'name':f'Ceramic coating variant {i}','price':i,'currency':'GBP'} for i in range(40)},
        'faq:guide':{'question':'How do we classify models?',
                     'answer':'Our size bands use the body type. SUVs use Large.'},
        'faq:background':{'question':'Where did we start?','answer':'A family business.'}}
    ranked=prioritize_knowledge(knowledge,'I have an unlisted SUV. Show ceramic coating prices.',{})
    assert 'faq:guide' in ranked and list(ranked).index('faq:guide')<3
    assert len(ranked)<=24 and 'faq:background' not in ranked
    assert len(ranked) <= 24


def test_costs_question_keeps_catalogue_prices_in_the_grounded_request(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from retrieval.catalog_store import CatalogStore
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    handler = MessageHandlerV7(SimpleNamespace(
        rewriter=SimpleNamespace(_client=object(),_model='test-model'),
        catalog=CatalogStore(catalog={'version':1,'currency':'GBP','categories':[{
            'id':'care','name':'Vehicle care','items':[
                {'sku':'LARGE','name':'Ceramic coating Large starting price','price':300}]}]})))
    seen = []
    monkeypatch.setattr(grounded_conversation,'answer',lambda *args,**kwargs:seen.append(args[3]))
    handler._grounded_answer('if i have a bmw x3 whats the costs',{})
    assert seen[0]['product:LARGE']['price']==300


def test_my_car_followup_retrieves_faqs_using_retained_customer_details(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from retrieval.faq_store import FAQStore
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    handler = MessageHandlerV7(SimpleNamespace(
        rewriter=SimpleNamespace(_client=object(),_model='test-model'),
        faq=FAQStore(faq=[{'q':'How are SUVs sized?',
                           'a':'A BMW X3 provisionally uses Large.'}])))
    queries = []
    original = handler._optional_faq_rows
    def faq_rows(question=None):
        queries.append(question)
        return original(question)
    monkeypatch.setattr(handler,'_optional_faq_rows',faq_rows)
    seen = []
    monkeypatch.setattr(grounded_conversation,'answer',lambda *args,**kwargs:seen.append(args[3]))
    handler._grounded_answer('so were would you put my car',{
        'conversation_history':[{'role':'assistant','content':'Unrelated assistant vocabulary must not drive retrieval.'}],
        'conversation_customer_statements':['if i have a bmw x3 whats the costs']})
    assert 'bmw x3' in queries[0]
    assert 'Unrelated assistant' not in queries[0]
    assert any(key.startswith('matched_faq:') and 'Large' in row['answer'] for key,row in seen[0].items())


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
