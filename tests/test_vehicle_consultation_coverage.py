"""Published service coverage tests retrieval, separately from live model quality."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from retrieval.catalog_store import CatalogStore
from retrieval.faq_store import FAQStore
from service import grounded_conversation
from service.agent_knowledge import prioritize_knowledge, size_variant_family


CATALOG=json.loads((Path(__file__).parent/'fixtures/vehicle_consultation_catalog.json').read_text(encoding='utf-8'))
ITEMS=[item for category in CATALOG['categories'] for item in category['items']]
CARS=['VW Polo','VW Golf R 4Motion','Toyota Yaris','BMW 3 Series','Mercedes C-Class',
      'Audi A5','Range Rover','BMW X5','Toyota Yaris Cross']
GUIDE={'q':'Which vehicle size band applies?',
       'a':'Small: Polo, Golf and Yaris. Medium: 3 Series, C-Class and A5. Large: SUVs, X5 and Range Rover. Unlisted models are provisional.'}


def make_handler(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    return MessageHandlerV7(SimpleNamespace(catalog=CatalogStore(catalog=CATALOG),
        faq=FAQStore(faq=[GUIDE]),rewriter=SimpleNamespace(_client=object(),_model='synthetic-model')))


@pytest.fixture(scope='module')
def consultation_handler():
    # The tested method takes a fresh session every time and only reads these
    # stores. Reuse their indexes instead of rebuilding them for each vehicle.
    with pytest.MonkeyPatch.context() as patch:
        return make_handler(patch)


@pytest.mark.parametrize('car',CARS)
@pytest.mark.parametrize('item',ITEMS,ids=lambda item:item['sku'])
def test_each_published_service_can_reach_provider_context_for_varied_cars(monkeypatch,car,item,consultation_handler):
    handler=consultation_handler
    seen=[]
    def completion(*args,**kwargs):
        seen.append(json.loads(kwargs['messages'][1]['content']))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            'kind':'clarification','answer':'What is the main concern?', 'sources':['business']})))])
    monkeypatch.setattr(grounded_conversation,'tracked_completion',completion)
    question=f'For my {car}, what is the starting price for {item["name"]}?'
    handler._grounded_answer(question,{})
    assert seen and 'product:'+item['sku'] in seen[0]['knowledge']
    row=seen[0]['knowledge']['product:'+item['sku']]
    assert row['price']==item['price'] and row['currency']=='GBP' and row['unit']==item['unit']
    assert any('size band' in row.get('question','') for row in seen[0]['knowledge'].values() if isinstance(row,dict))


def test_changed_vehicle_keeps_all_current_engine_bay_size_prices_beyond_preview(monkeypatch):
    handler=make_handler(monkeypatch)
    seen=[]
    monkeypatch.setattr(grounded_conversation,'answer',lambda *args,**kwargs:seen.append(args[3]))
    handler._grounded_answer('What about my BMW X5 instead?',{
        'sales_agent':{'selected_offering_id':'product:ENGINE_BAY_SMALL','offering_ids':['product:ENGINE_BAY_SMALL']},
        'conversation_customer_statements':['My Toyota Yaris needs an Engine Bay Detail.']})
    ranked=prioritize_knowledge(seen[0],'What about my BMW X5 instead?',{
        'selected_offering_id':'product:ENGINE_BAY_SMALL','offering_ids':['product:ENGINE_BAY_SMALL']})
    assert {key for key in ranked if key.startswith('product:ENGINE_BAY_')}=={
        'product:ENGINE_BAY_SMALL','product:ENGINE_BAY_MEDIUM','product:ENGINE_BAY_LARGE'}


def test_late_public_suitability_guide_is_not_lost_at_faq_preview_boundary(monkeypatch):
    handler=make_handler(monkeypatch)
    rows=[{'q':f'Background {i}','a':'Ordinary public information.'} for i in range(55)]
    rows.append({'q':'How are vehicle size bands classified?','a':'SUVs use Large. Unusual models need confirmation.'})
    handler.faq=FAQStore(faq=rows)
    # Force the full-list projection to supply this guide, independently of fuzzy matching.
    monkeypatch.setattr(handler.faq,'best_match',lambda *args,**kwargs:[])
    seen=[]
    monkeypatch.setattr(grounded_conversation,'answer',lambda *args,**kwargs:seen.append(args[3]))
    handler._grounded_answer('How much is Engine Bay Detail?',{})
    ranked=prioritize_knowledge(seen[0],'How much is Engine Bay Detail?',{})
    assert any('SUVs use Large' in row.get('answer','') for row in ranked.values() if isinstance(row,dict))


def test_sibling_prices_exclude_private_inactive_other_currency_and_other_jobs():
    knowledge={'product:small':{'name':'Engine Bay Detail Small','currency':'GBP'},
        'product:large':{'name':'Engine Bay Detail Large','currency':'GBP'},
        'product:hidden':{'name':'Engine Bay Detail Medium','currency':'GBP','public':False},
        'product:inactive':{'name':'Engine Bay Detail Large','currency':'GBP','active':False},
        'product:usd':{'name':'Engine Bay Detail Medium','currency':'USD'},
        'product:other':{'name':'Full Restoration Large','currency':'GBP'}}
    from service.agent_knowledge import remembered_size_variants
    assert remembered_size_variants(knowledge,{'selected_offering_id':'product:small'})==['product:small','product:large']
    assert size_variant_family('Engine Bay Detail — Small (starting price)')=='Engine Bay Detail'
    assert size_variant_family('One-to-one training course')==''
