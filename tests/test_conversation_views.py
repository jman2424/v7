from datetime import datetime, timezone

from service import analytics_db
from service.conversation_views import conversation_message
from service.tenant_service import TenantService
from tests.test_owner_console import sign_in


def test_reference_is_stable_secret_tenant_and_channel_scoped():
    row={'id':1,'session_id':'private-session-cookie','channel':'web','text':'Example'}
    result=conversation_message(row,'FIRST','test-only-secret')
    assert result==conversation_message(row,'FIRST','test-only-secret')
    assert 'session_id' not in result
    assert len(result['conversation_ref'])==32
    assert 'private-session-cookie' not in str(result)
    assert result['conversation_ref']!=conversation_message(row,'SECOND','test-only-secret')['conversation_ref']
    assert result['conversation_ref']!=conversation_message(row,'FIRST','other-secret')['conversation_ref']
    assert result['conversation_ref']!=conversation_message({**row,'channel':'email'},'FIRST','test-only-secret')['conversation_ref']
    assert row['session_id']=='private-session-cookie'


def test_legacy_messages_do_not_invent_a_shared_customer():
    assert conversation_message({'id':1,'session_id':None},'FIRST',b'test')['conversation_ref'] is None
    assert conversation_message({'id':2,'session_id':''},'FIRST',b'test')['conversation_ref'] is None


def test_authorised_reader_keeps_tenant_pagination_and_private_ids(client,app):
    TenantService(app.container.storage).create_tenant('OTHER','Other test business')
    analytics_db._ensure_ready()
    now=datetime.now(timezone.utc).isoformat()
    with analytics_db._conn() as db:
        for tenant in ['EXAMPLE','OTHER']:
            for index in range(55):
                db.execute("INSERT INTO events(ts_utc,tenant,event_type,channel,session_id,text) VALUES(?,?,'msg_in','web',?,?)",
                           (now,tenant,'session-'+str(index%2),tenant+' message '+str(index)))
    assert client.get('/admin/api/conversations').status_code==401
    sign_in(client)
    response=client.get('/admin/api/conversations?tenant=EXAMPLE')
    assert response.status_code==200
    assert response.headers['Cache-Control']=='no-store'
    result=response.get_json()
    assert len(result['messages'])==50 and result['has_more']
    assert len({row['conversation_ref'] for row in result['messages']})==2
    assert all(row['text'].startswith('EXAMPLE ') and 'session_id' not in row for row in result['messages'])
    next_page=client.get('/admin/api/conversations?tenant=EXAMPLE&before='+str(result['next_before'])).get_json()
    assert len(next_page['messages'])==5 and not next_page['has_more']
    assert not {row['id'] for row in result['messages']}&{row['id'] for row in next_page['messages']}
    assert client.get('/admin/api/conversations?tenant=OTHER').status_code==403


def test_native_postgres_conversation_reader_keeps_rls_and_opaque_references(pg_runtime,monkeypatch):
    from flask import Flask
    from routes import admin_api_routes
    from service import session_store
    runtime=pg_runtime
    now=datetime.now(timezone.utc).isoformat()
    for tenant in [runtime['tenant'],runtime['other']]:
        runtime['admin'].execute(
            "INSERT INTO v7_private.events(ts_utc,tenant,event_type,channel,session_id,text) "
            "VALUES(%s,%s,'msg_in','web','private-session',%s)",
            (now,tenant,tenant+' visible message'))
    app=Flask(__name__)
    app.secret_key='native-conversation-test-only-secret'
    monkeypatch.setattr(admin_api_routes,'_tenant',lambda:runtime['tenant'])
    with app.test_request_context('/?minutes=60'):
        result=admin_api_routes.api_conversations().get_json()
    assert len(result['messages'])==1
    assert result['messages'][0]['text']==runtime['tenant']+' visible message'
    assert 'session_id' not in result['messages'][0]
    assert 'private-session' not in str(result)
    with session_store.postgres_connection(runtime['tenant']) as db:
        assert db.execute('SELECT COUNT(*) FROM v7_private.events WHERE tenant=%s',
                          (runtime['other'],)).fetchone()[0]==0
    monkeypatch.setattr(admin_api_routes,'_tenant',lambda:runtime['other'])
    with app.test_request_context('/?minutes=60'):
        other=admin_api_routes.api_conversations().get_json()
    assert len(other['messages'])==1
    assert result['messages'][0]['conversation_ref']!=other['messages'][0]['conversation_ref']
