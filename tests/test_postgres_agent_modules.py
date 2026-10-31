"""Module policy uses the existing private tenant-document port and native RLS."""
import pytest

from service import agent_modules as modules
from service.conversion_actions import ActionError, submit_action, list_action_requests
from retrieval.storage import Storage


def test_postgres_policy_and_execution_are_tenant_scoped(pg_runtime,monkeypatch):
    monkeypatch.setenv('V7_AGENT_MODULE_POLICY_JSON','{}')
    tenant,other=pg_runtime['tenant'],pg_runtime['other']
    storage=Storage(tenant)
    storage.write_json(tenant,'sales_actions.json',{
        'consultation':{'enabled':False,'slots':[]},'quote':{'enabled':True},'callback':{'enabled':False}})
    storage.write_json(tenant,modules.FILENAME,{'version':1,'modules':{
        name:{'granted':True,'enabled':name!='quote'} for name in modules.REGISTRY}})
    assert not modules.allowed(storage,tenant,'quote')
    assert modules.allowed(storage,other,'quote')
    assert modules.document(storage,other) is None
    with pytest.raises(ActionError,match='action_unavailable'):
        submit_action(storage,tenant,{'action':'quote','name':'Synthetic','contact':'visitor@example.net','consent':True},'module-pg')
    assert list_action_requests(tenant)==[]
