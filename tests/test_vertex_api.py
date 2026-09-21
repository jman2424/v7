"""REST/MCP parity, authorization and shared mutation regression coverage."""
import json

import pytest

from service import mcp_tools, tenant_access
from tests.test_mcp import mcp, issue, data, rpc  # noqa: F401
from tests.test_platform_security import platform  # noqa: F401


READS = {
    '/business-overview':'get_business_overview', '/statistics':'get_statistics',
    '/catalog':'get_catalog', '/offers':'get_offers', '/roles':'get_roles',
    '/health':'get_agent_health', '/errors':'get_error_summary',
    '/errors/recent':'get_recent_errors', '/users':'get_users',
}


def headers(token):
    return {'Authorization':'Bearer '+token}


def test_rest_and_mcp_share_authentication_and_read_results(mcp):
    client = mcp[0].test_client()
    token = issue(client)[0]['access_token']
    for path,tool in READS.items():
        # A valid dashboard cookie is insufficient, just as on MCP.
        denied = client.get('/api/v1'+path)
        assert denied.status_code == 401 and 'WWW-Authenticate' in denied.headers
        response = client.get('/api/v1'+path,headers=headers(token))
        assert response.status_code == 200, response.json
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.json == data(client,token,tool)
        assert 'password_hash' not in response.text
    assert client.get('/api/v1/catalog?tenant=BETA',headers=headers(token)).status_code == 400
    assert 'Beta tablet' not in client.get('/api/v1/catalog',headers=headers(token)).text
    assert client.get('/api/v1/catalog',headers={**headers(token),'Origin':'https://evil.test'}).status_code == 403


def test_rest_writes_are_visible_to_mcp_and_use_revision_checks(mcp):
    app = mcp[0]
    client = app.test_client()
    token = issue(client)[0]['access_token']
    catalog = data(client,token,'get_catalog')
    arguments = {'category':'Devices','name':'Alpha laptop','expected_revision':catalog['revision'],'changes':{'price':7.99}}
    response = client.patch('/api/v1/catalog/items',json=arguments,headers=headers(token))
    assert response.status_code == 200, response.json
    assert data(client,token,'get_catalog')['items'][0]['price'] == 7.99
    assert client.patch('/api/v1/catalog/items',json=arguments,headers=headers(token)).status_code == 409
    invalid = {**arguments,'expected_revision':response.json['revision'],'changes':{'price':-1}}
    assert client.patch('/api/v1/catalog/items',json=invalid,headers=headers(token)).status_code == 400
    assert client.patch('/api/v1/catalog/items?tenant=BETA',json=arguments,headers=headers(token)).status_code == 400
    from pathlib import Path
    entries = [json.loads(line) for line in Path('logs/selfrepair.log').read_text().splitlines()]
    assert any(row['extra'].get('source') == 'Vertex REST API' and row['extra'].get('result') == 'success' for row in entries)
    assert app.container.storage.read_json('BETA','catalog.json')['categories'][0]['items'][0]['price'] == 25


def test_read_only_token_cannot_write_through_either_transport(mcp):
    client = mcp[0].test_client()
    token = issue(client,'business:read')[0]['access_token']
    current = data(client,token,'get_catalog')
    arguments = {'category':'Devices','name':'Alpha laptop','expected_revision':current['revision']}
    assert client.post('/api/v1/catalog/items/disable',json=arguments,headers=headers(token)).status_code == 403
    response = rpc(client,token,params={'name':'disable_catalog_item','arguments':arguments})
    assert response.json['result']['structuredContent']['error']['code'] == 'forbidden'
    assert data(client,token,'get_catalog')['revision'] == current['revision']


def test_rest_calls_the_same_dispatcher(mcp,monkeypatch):
    client = mcp[0].test_client()
    token = issue(client)[0]['access_token']
    calls = []
    def execute(container,identity,scopes,name,args,**kwargs):
        calls.append((identity['tenant'],name,args,kwargs))
        return {'shared':True}
    monkeypatch.setattr(mcp_tools,'execute',execute)
    assert client.get('/api/v1/statistics?minutes=60',headers=headers(token)).json == {'shared':True}
    assert data(client,token,'get_statistics',{'minutes':60}) == {'shared':True}
    assert calls[0][:3] == calls[1][:3] == ('ALPHA','get_statistics',{'minutes':60})
    assert calls[0][3]['source'] == 'Vertex REST API'


@pytest.mark.parametrize('query',['minutes=nan','minutes=1&minutes=2','minutes=0','minutes=999999999999','tenant=BETA'])
def test_invalid_query_arguments_are_rejected(mcp,query):
    client = mcp[0].test_client()
    token = issue(client)[0]['access_token']
    assert client.get('/api/v1/statistics?'+query,headers=headers(token)).status_code == 400


def test_rest_and_mcp_offer_operations_use_current_offer_store(mcp):
    app = mcp[0]
    client = app.test_client()
    token = issue(client)[0]['access_token']
    original = data(client,token,'get_offers')
    offer = {'title':'Two for one','description':'One free matching product','deal_type':'buy_one_get_one','product_skus':['ALPHA_1']}
    response = client.post('/api/v1/offers',json={'expected_revision':original['revision'],'offer':offer},headers=headers(token))
    assert response.status_code == 200, response.json
    created = response.json
    assert data(client,token,'get_offers')['items'][0]['deal_type'] == 'buy_one_get_one'
    disabled = client.post('/api/v1/offers/'+created['item']['id']+'/disable',json={'expected_revision':created['revision']},headers=headers(token))
    assert disabled.status_code == 200
    assert app.container.storage.read_json('ALPHA','offers.json')[0]['active'] is False


def test_unpaid_business_cannot_bypass_activation_via_rest(mcp):
    client = mcp[0].test_client()
    token = issue(client)[0]['access_token']
    tenant_access.register('ALPHA')
    original = data(client,token,'get_catalog')
    arguments = {'category':'Devices','name':'Alpha laptop','expected_revision':original['revision']}
    assert client.post('/api/v1/catalog/items/disable',json=arguments,headers=headers(token)).status_code == 403


def test_revocation_and_quota_are_shared(mcp):
    client = mcp[0].test_client()
    token = issue(client)[0]['access_token']
    from service import mcp_auth, session_store
    with mcp[0].app_context(), mcp_auth.database() as db:
        db.execute("UPDATE mcp_grants SET expires=0 WHERE digest=?",(session_store._digest(token),))
    assert client.get('/api/v1/catalog',headers=headers(token)).status_code == 401
    assert rpc(client,token,'ping').status_code == 401


def test_openapi_contract_matches_shared_operations():
    import json
    from pathlib import Path
    from scripts.export_vertex_api import document
    contract = Path(__file__).resolve().parents[1] / 'schemas/vertex-api.openapi.json'
    assert json.loads(contract.read_text(encoding='utf-8')) == document()
