"""Generic records, retail compatibility and tenant/private-context boundaries."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError
from retrieval.storage import Storage
from service.business_core import BusinessCore, empty_core, validate_core
from tests.test_mcp import mcp, issue, data, rpc
from tests.test_platform_security import platform


def test_native_offering_rest_mcp_and_private_work(mcp):
    app = mcp[0]
    client = app.test_client()
    token = issue(client)[0]['access_token']
    headers = {'Authorization':'Bearer '+token}
    before = app.container.storage.read_json('ALPHA','catalog.json')
    initial = data(client,token,'get_offerings')
    result = client.post('/api/v1/offerings',headers=headers,json={'expected_revision':initial['revision'],
        'offering':{'name':'Document Translation','type':'service','price_type':'per_word','price':0.085,'active':True}})
    assert result.status_code == 200, result.json
    item = result.json['item']
    assert client.get('/api/v1/offerings/'+item['id'],headers=headers).json['price'] == 0.085
    assert client.get('/api/v1/offerings/'+item['id']+'?offering_id=other',headers=headers).status_code == 400
    assert data(client,token,'get_offering',{'offering_id':item['id']})['name'] == 'Document Translation'
    assert client.patch('/api/v1/offerings/'+item['id'],headers=headers,json={'expected_revision':initial['revision'],'changes':{'active':False}}).status_code == 409
    updated = client.patch('/api/v1/offerings/'+item['id'], headers=headers, json={
        'expected_revision':result.json['revision'], 'changes':{'price':0.095}})
    assert updated.status_code == 200
    assert data(client,token,'get_offering',{'offering_id':item['id']})['price'] == 0.095
    core = app.container.storage.read_json('ALPHA','business_core.json')
    core['locations'] = [{'id':'remote','name':'Online','type':'remote_only','service_area':'UK / international','active':True}]
    core['business_rules'] = [{'id':'quote','title':'Large translation','description':'Projects over 10,000 words require a manual quote.','active':True,'requires_manual_review':True}]
    core['work'] = [{'id':'project1','title':'Private customer document','type':'project','status':'requested','customer_reference':'PRIVATE-CUSTOMER'}]
    app.container.storage.write_json('ALPHA','business_core.json',core)
    assert data(client,token,'get_projects')['items'][0]['id'] == 'project1'
    assert data(client,token,'get_jobs')['items'] == []
    assert data(client,token,'get_service_areas')['items'][0]['type'] == 'remote_only'
    public = BusinessCore(app.container.storage,'ALPHA').public_context()
    assert 'PRIVATE-CUSTOMER' not in json.dumps(public)
    assert 'Private customer document' not in json.dumps(public)
    assert app.container.storage.read_json('ALPHA','catalog.json') == before
    beta = BusinessCore(app.container.storage,'BETA')
    assert beta.document()['offerings'] == []
    assert client.get('/api/v1/offerings?tenant=BETA',headers=headers).status_code == 400
    assert client.get('/api/v1/projects').status_code == 401


def test_retail_projection_updates_same_catalog(mcp):
    client = mcp[0].test_client()
    token = issue(client)[0]['access_token']
    item = data(client,token,'get_offerings')['items'][0]
    assert item['type'] == 'product' and item['source'] == 'catalog'
    result = data(client,token,'update_offering',{'offering_id':item['id'],'expected_revision':item['revision'],'changes':{'price':19.95}})
    assert result['ok']
    assert data(client,token,'get_catalog')['items'][0]['price'] == 19.95


def test_generic_write_scope_and_activation(mcp):
    client = mcp[0].test_client()
    token = issue(client,'business:read')[0]['access_token']
    args = {'expected_revision':data(client,token,'get_offerings')['revision'],'offering':{'name':'Detail','type':'service','price_type':'from','price':120,'active':True}}
    result = rpc(client,token,params={'name':'create_offering','arguments':args}).json['result']
    assert result['isError']
    from service import tenant_access
    token = issue(client)[0]['access_token']
    tenant_access.register('ALPHA')
    result = rpc(client,token,params={'name':'create_offering','arguments':args}).json['result']
    assert result['isError']


def test_core_validation_and_grounded_service_answer(tmp_path):
    (tmp_path/'DETAIL').mkdir()
    storage = Storage('DETAIL',business_root=tmp_path)
    core = empty_core()
    core['offerings'] = [{'id':'detail','name':'Full Interior Detail','type':'service','price_type':'from','price':120,'currency':'GBP','duration_minutes':180,'active':True}]
    core['business_rules'] = [{'id':'suv','title':'SUV surcharge','description':'SUVs cost GBP 20 more.','active':True}]
    storage.write_json('DETAIL','business_core.json',core)
    business = BusinessCore(storage,'DETAIL')
    answer = business.answer('Full Interior Detail')
    assert 'From GBP 120' in answer and '180 minutes' in answer and 'SUVs cost GBP 20' in answer
    assert business.answer('unrelated astronomy') is None
    invalid = copy.deepcopy(core)
    invalid['offerings'].append(invalid['offerings'][0])
    with pytest.raises(ValueError): storage.write_json('DETAIL','business_core.json',invalid)
    invalid = copy.deepcopy(core)
    del invalid['offerings'][0]['price']
    with pytest.raises(ValidationError): validate_core(invalid)
    from handlers.handler_v7 import MessageHandlerV7
    from retrieval.catalog_store import CatalogStore
    handler = MessageHandlerV7(SimpleNamespace(catalog=CatalogStore(storage)))
    result = handler.handle('Full Interior Detail',SimpleNamespace(tenant='DETAIL',session_id='a',channel='web'),{})
    assert result['intent'] == 'business_knowledge'
    assert 'From GBP 120' in result['reply']


def test_tariq_projection_does_not_rewrite_original_files():
    root = Path(__file__).resolve().parents[1]
    storage = Storage('TARIQ',business_root=root/'business')
    paths = [root/'business/TARIQ/catalog.json',root/'business/TARIQ/branches.json']
    before = [path.read_bytes() for path in paths]
    core = BusinessCore(storage,'TARIQ')
    assert core.offerings() and all(row['type']=='product' for row in core.offerings())
    assert core.locations() and all(row['type']=='store' for row in core.locations())
    assert before == [path.read_bytes() for path in paths]

def test_templates_are_valid_configuration():
    root = Path(__file__).resolve().parents[1]
    for path in (root/'business_templates').glob('*.json'):
        validate_core(json.loads(path.read_text(encoding='utf-8')))
