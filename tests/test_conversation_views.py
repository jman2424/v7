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


def test_workspace_search_finds_older_records_and_respects_the_tenant(client, app):
    TenantService(app.container.storage).create_tenant('OTHER', 'Other')
    now = datetime.now(timezone.utc).isoformat()
    for tenant in ('EXAMPLE', 'OTHER'):
        analytics_db.upsert_lead(tenant=tenant, lead_id=tenant+'-lead', name='Order 10% off')
    with analytics_db._conn() as db:
        for tenant in ('EXAMPLE', 'OTHER'):
            for i in range(55):
                text = 'Order 10% off' if i == 0 else 'Another message'
                db.execute("INSERT INTO events(ts_utc,tenant,event_type,channel,session_id,text) VALUES(?,?,'msg_in','web',?,?)",
                           (now, tenant, 'session', text))
    sign_in(client)
    params = {'tenant': 'EXAMPLE', 'q': '10% order'}
    messages = client.get('/admin/api/conversations', query_string=params).json['messages']
    assert len(messages) == 1 and messages[0]['text'] == 'Order 10% off'
    direct = client.get('/admin/api/conversations', query_string={'tenant':'EXAMPLE','before':messages[0]['id']+1}).json
    assert direct['messages'][0] == messages[0]
    leads = client.get('/admin/api/leads', query_string=params).json
    assert [row['lead_id'] for row in leads] == ['EXAMPLE-lead']
    assert client.get('/admin/api/leads?tenant=EXAMPLE&lead_id=OTHER-lead').json == []


def test_contact_search_checks_permission_channel_date_and_retained_history(client, app):
    analytics_db.upsert_lead(tenant='EXAMPLE', lead_id='buyer', name='Amelia Brown', phone='555123456')
    with analytics_db._conn() as db:
        db.execute("INSERT INTO events(ts_utc,tenant,event_type,channel,lead_id,session_id,text) "
                   "VALUES('2022-02-18T11:15:00Z','EXAMPLE','msg_in','whatsapp','buyer','thread-one','Delivery enquiry')")
    sign_in(client)
    def search(query, channel='whatsapp'):
        return client.get('/admin/api/conversations', query_string={'q':query,'period':'all','channel':channel}).json['messages']
    for query in ['AmEL','12345','deliv 2022-02','WhatsApp']:
        assert [row['text'] for row in search(query)] == ['Delivery enquiry']
    assert not search('Brown','email')
    sign_in(client,'business_staff',permissions=['conversations.read'])
    assert not search('12345')
    assert len(search('delivery')) == 1
