from datetime import datetime, timedelta, timezone
import json

import pytest

from service import analytics_db
from service.product_metrics import record_sale, void_sale, record_inventory, matched_products
from service.statistics import get_statistics
from tests.conftest import set_test_identity


CATALOG={'categories':[{'id':'items','name':'Items','items':[
    {'sku':'A','name':'Product A','price':10,'unit':'each','stock_quantity':3,'low_stock_threshold':5,'in_stock':True},
    {'sku':'B','name':'Product B','price':20,'unit':'each','in_stock':True}]}],'version':1,'currency':'GBP'}


def sale_payload(**kwargs):
    return {'id':'test-sale-reference-0001','sku':'A','quantity':2,'amount_gbp':'19.99',
            'occurred_utc':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),'channel':'web',**kwargs}


def test_reply_rates_match_message_and_company_not_just_counts(app):
    now=datetime.now(timezone.utc)
    analytics_db._ensure_ready()
    with analytics_db._conn() as db:
        def event(mid,kind,offset,tenant='EXAMPLE',channel='web',session='one',intent='price_check',fallback=False):
            db.execute('INSERT INTO events(ts_utc,tenant,channel,session_id,event_type,message_id,intent,meta_json) VALUES(?,?,?,?,?,?,?,?)',
                       ((now-timedelta(seconds=offset)).isoformat(),tenant,channel,session,kind,mid,intent,json.dumps({'fallback':fallback})))
        event('a','msg_in',100)
        event('a:reply','msg_out',96)
        event('b','msg_in',90)
        event('b:reply','msg_out',85,fallback=True)
        event('c','msg_in',80)
        event('c:reply','msg_out',75,tenant='OTHER')
        event('d','msg_in',70,channel='whatsapp')
        event('d:out','msg_out',65,channel='whatsapp')
        event('e','msg_in',60)
        event('e:reply','msg_out',55,session='different-person')
        event('f','msg_in',40)
        event('f:reply','msg_out',-10)  # Not recorded by the report end.
        event('','msg_in',30)
    report=get_statistics(tenant='EXAMPLE',days=1,now=now)
    assert report['replies']['total']['eligible']==6
    assert report['replies']['total']['replied']==3
    assert report['replies']['total']['answered']==2
    assert report['replies']['total']['inbound']==7
    assert report['replies']['total']['response_seconds']==pytest.approx(14,abs=.001)
    wa=get_statistics(tenant='EXAMPLE',days=1,channel='whatsapp',now=now)
    assert wa['replies']['total']['replied']==1


def test_product_interest_dedupes_and_sales_are_real_records(app):
    assert matched_products({'intent':'faq','items':[{'sku':'A'}]}) is None
    assert matched_products({'intent':'price_check','items':None}) == []
    assert matched_products({'intent':'search_product','items':[{'sku':'A'},{'sku':'A'}]})==['A']
    for _ in range(2):
        analytics_db.log_message(tenant='EXAMPLE',channel='web',direction='outbound',session_id='one',
                                 message_id='enquiry:reply',products=['A','A'],intent='search_product')
    analytics_db.log_message(tenant='OTHER',channel='web',direction='outbound',session_id='one',products=['A'])
    payload=sale_payload()
    assert record_sale('EXAMPLE',payload,CATALOG)['duplicate'] is False
    assert record_sale('EXAMPLE',payload,CATALOG)['duplicate'] is True
    record_sale('OTHER',sale_payload(id='different-sale-reference'),CATALOG)
    report=get_statistics(tenant='EXAMPLE',days=7,catalog=CATALOG)['commerce']
    products={p['sku']:p for p in report['products']}
    assert products['A']['interest']==1 and products['B']['interest']==0
    assert products['A']['units']==2 and products['A']['amount_pence']==1999
    assert not get_statistics(tenant='EXAMPLE',days=7,channel='whatsapp',catalog=CATALOG)['commerce']['recent_sales']
    assert void_sale('OTHER','unknown') is False
    assert void_sale('EXAMPLE',payload['id']) is True
    assert get_statistics(tenant='EXAMPLE',days=7,catalog=CATALOG)['commerce']['products'][0]['units']==0
    with pytest.raises(ValueError):
        record_sale('EXAMPLE',payload,CATALOG)


@pytest.mark.parametrize('change',[{'quantity':0},{'quantity':-1},{'quantity':'NaN'},{'quantity':1.0001},
    {'amount_gbp':'Infinity'},{'amount_gbp':'1.001'},{'amount_gbp':-1},{'sku':'OTHER_PRODUCT'},
    {'occurred_utc':'2039-01-01T00:00:00Z'},{'occurred_utc':'2026-01-01'}, {'channel':'injected'}, {'id':'bad'}])
def test_sale_validation(app,change):
    with pytest.raises(ValueError):
        record_sale('EXAMPLE',sale_payload(**change),CATALOG)


def test_stock_history_preserves_unknown_and_ignores_unchanged_saves(app):
    record_inventory('EXAMPLE',{},CATALOG)
    record_inventory('EXAMPLE',CATALOG,CATALOG)
    record_inventory('OTHER',{},CATALOG)
    result=get_statistics(tenant='EXAMPLE',days=365,catalog=CATALOG)['commerce']
    assert len(result['inventory'])==2
    levels={row['sku']:row['quantity'] for row in result['inventory']}
    assert levels=={'A':3,'B':None}
    assert len(get_statistics(tenant='EXAMPLE',days=365)['daily'])==366


def test_owner_sales_routes_and_stock_validation(client,app):
    assert client.post('/admin/api/recorded-sales',json=sale_payload()).status_code==401
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'owner','roles':['business_owner'],'tenant':'EXAMPLE'})
    assert client.post('/admin/api/recorded-sales?tenant=OTHER',json=sale_payload()).status_code==403
    assert client.post('/admin/api/recorded-sales',json=sale_payload(),headers={'X-CSRF-Token':''}).status_code==403
    assert client.put('/admin/api/catalog',json=CATALOG).status_code==200
    assert client.post('/admin/api/recorded-sales',json=sale_payload()).status_code==200
    assert client.post('/admin/api/recorded-sales/test-sale-reference-0001/void?tenant=OTHER',json={}).status_code==403
    zero=json.loads(json.dumps(CATALOG))
    zero['categories'][0]['items'][0]['stock_quantity']=0
    assert client.put('/admin/api/catalog',json=zero).status_code==200
    assert client.get('/admin/api/catalog').json['categories'][0]['items'][0]['in_stock'] is False
    from retrieval.catalog_store import CatalogStore
    assert CatalogStore(catalog=client.get('/admin/api/catalog').json).in_stock('A') is False
    for bad in [-1,float('nan'),True]:
        zero['categories'][0]['items'][0]['stock_quantity']=bad
        assert client.put('/admin/api/catalog',json=zero).status_code==400
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'staff','roles':['business_staff'],'tenant':'EXAMPLE'})
    assert client.post('/admin/api/recorded-sales',json=sale_payload()).status_code==403
