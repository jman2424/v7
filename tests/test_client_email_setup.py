"""Client setup and retention never grant mailbox ownership or execute emails."""
from datetime import datetime, timezone
import json
import time
from types import SimpleNamespace

import pytest

from connectors import business_email as provider
from service import business_channels as channels, business_operations as operations, business_email_retention as retention
from service import business_email_setup as setup
from tests.test_business_channel_providers import configured as _configured
from tests.test_business_channel_providers import owner, intake, EMAIL_ID, signature, fake_answer, received

INBOX='00000000-0000-4000-8000-000000000002'
THREAD='00000000-0000-4000-8000-000000000003'
NEW_EMAIL='00000000-0000-4000-8000-000000000004'
configured = _configured


def handled(client, container, monkeypatch, *, opt_in=True, state='completed'):
    monkeypatch.setenv('V7_EMAIL_INBOX_ROUTES_JSON',json.dumps({INBOX:'business@example.com'}))
    # Create the operation directly: the standard-product event is intentionally
    # ignored for an address explicitly bound to the separate Inbox product.
    row,_=operations.enqueue('EXAMPLE','email',EMAIL_ID,'email:retention-test','visitor@example.net',{
        'email_id':EMAIL_ID,'inbox_id':INBOX,'thread_id':THREAD,'recipient':'business@example.com','text':'Private email text'})
    claim=operations.claim('EXAMPLE')
    operations.finish('EXAMPLE',row['id'],claim['lease'],state,reply='Private draft')
    old=time.time()-2*86400
    with operations.connection('EXAMPLE',write=True) as db:
        db.execute('UPDATE business_operations SET created=? WHERE tenant=? AND id=?',(old,'EXAMPLE',row['id']))
    prefs=channels.settings(container.storage,'EXAMPLE')
    prefs['email'].update(retention_days=1,provider_cleanup='trash_handled' if opt_in else 'keep',cleanup_confirmed=opt_in)
    container.storage.write_json('EXAMPLE',channels.FILENAME,prefs)
    message={'id':EMAIL_ID,'direction':'inbound','received_at':datetime.fromtimestamp(old,timezone.utc).isoformat()}
    return operations.get('EXAMPLE',row['id']),message


def test_owner_setup_is_a_scoped_request_not_mailbox_authority(client, configured):
    prefs=channels.settings(configured.storage,'EXAMPLE')
    prefs['email']['enabled']=False
    configured.storage.write_json('EXAMPLE',channels.FILENAME,prefs)
    owner(client)
    before=client.get('/admin/api/business-email-setup?tenant=EXAMPLE')
    assert before.status_code==200 and before.json['state']=='not_started'
    payload={'revision':before.json['revision'],'settings':{'address':'help@client.example','provider':'google_workspace','purpose':'support'}}
    saved=client.put('/admin/api/business-email-setup?tenant=EXAMPLE',json=payload)
    assert saved.status_code==200 and saved.json['state']=='requested'
    assert not saved.json['can_enable'] and saved.json['native_oauth_available'] is False
    assert channels.bindings('email').get('help@client.example') is None
    assert client.put('/admin/api/business-email-setup?tenant=EXAMPLE',json=payload).status_code==409
    assert client.get('/admin/api/business-email-setup?tenant=OTHER').status_code==403


def test_active_address_cannot_be_silently_repointed(client, configured):
    owner(client)
    before=client.get('/admin/api/business-email-setup?tenant=EXAMPLE').json
    response=client.put('/admin/api/business-email-setup?tenant=EXAMPLE',json={
        'revision':before['revision'],'settings':{'address':'other@client.example','provider':'hosted_email','purpose':'support'}})
    assert response.status_code==409 and response.json['error']=='email_setup_disable_before_change'


def test_setup_rejects_credentials_and_unverified_enable(client, configured):
    owner(client)
    before=client.get('/admin/api/business-email-setup?tenant=EXAMPLE').json
    response=client.put('/admin/api/business-email-setup?tenant=EXAMPLE',json={
        'revision':before['revision'],'settings':{'address':'business@example.com','provider':'hosted_email','purpose':'support','password':'NEVER_STORE'}})
    assert response.status_code==400
    prefs=channels.settings(configured.storage,'EXAMPLE')
    response=client.put('/admin/api/business-channels?tenant=EXAMPLE',json={'settings':prefs})
    assert response.status_code==409 and response.json['error']=='email_setup_verification_required'


def test_missing_queue_storage_does_not_hide_setup(client, configured, monkeypatch):
    owner(client)
    monkeypatch.setattr(operations,'cleanup_counts',lambda _:(_ for _ in ()).throw(RuntimeError('PRIVATE_CONNECTION_DETAIL')))
    response=client.get('/admin/api/business-email-setup?tenant=EXAMPLE')
    assert response.status_code==200 and not response.json['storage_available'] and not response.json['can_enable']
    assert 'PRIVATE' not in response.get_data(as_text=True)


def test_cleanup_requires_explicit_owner_confirmation():
    with pytest.raises(ValueError,match='email_cleanup_confirmation_required'):
        channels.validate({'email':{'provider_cleanup':'trash_handled'}})


def test_v7_retention_clears_email_body_draft_and_model_memory(client, configured, monkeypatch):
    from service.conversation_memory import ConversationMemory
    row,_=handled(client,configured,monkeypatch,opt_in=False)
    memory=ConversationMemory(configured.storage,'EXAMPLE')
    memory.set(row['conversation_id'],'conversation_history',[{'role':'user','content':'Private email text'}])
    monkeypatch.setattr(provider,'trash_thread',lambda *_:pytest.fail('Cleanup was not opted in'))
    retention.run(configured,'EXAMPLE')
    assert operations.purge('EXAMPLE','email',1)==1
    after=operations.get('EXAMPLE',row['id'])
    assert after['payload']=={} and after['reply']==after['source_address']==after['conversation_id']==''
    with memory._connection() as db:
        assert memory._execute(db,'SELECT COUNT(*) FROM conversation_memory WHERE tenant=?',('EXAMPLE',)).fetchone()[0]==0


def test_opted_cleanup_trashes_only_old_handled_bound_threads(client, configured, monkeypatch):
    row,message=handled(client,configured,monkeypatch)
    calls=[]
    monkeypatch.setattr(provider,'thread_emails',lambda *_:[message])
    monkeypatch.setattr(provider,'trash_thread',lambda *args:calls.append(args))
    retention.run(configured,'EXAMPLE')
    assert calls==[(INBOX,THREAD)]
    assert operations.get('EXAMPLE',row['id'])['error_code']=='retention_trashed'
    operations.purge('EXAMPLE','email',1)
    assert operations.previously_trashed('EXAMPLE',INBOX,THREAD)
    assert not operations.previously_trashed('OTHER',INBOX,THREAD)
    assert operations.cleanup_counts('EXAMPLE')=={'retention_trashed':1}


@pytest.mark.parametrize('kind',['recent','unrecognised','unhandled','action','revoked'])
def test_cleanup_preserves_mail_that_requires_attention(client, configured, monkeypatch, kind):
    row,message=handled(client,configured,monkeypatch,state='needs_review' if kind=='unhandled' else 'completed')
    if kind=='recent':
        message['received_at']=datetime.now(timezone.utc).isoformat()
    if kind=='unrecognised':
        message['id']=NEW_EMAIL
    if kind=='action':
        with operations.connection('EXAMPLE',write=True) as db:
            payload={**row['payload'],'approved_action':{'action':'quote'}}
            db.execute('UPDATE business_operations SET payload=? WHERE tenant=? AND id=?',(json.dumps(payload),'EXAMPLE',row['id']))
    if kind=='revoked':
        configured.storage.write_json('EXAMPLE',channels.GRANTS_FILE,{'email':False,'phone':True})
    monkeypatch.setattr(provider,'thread_emails',lambda *_:[message])
    monkeypatch.setattr(provider,'trash_thread',lambda *_:pytest.fail('Protected conversation was trashed'))
    retention.run(configured,'EXAMPLE')


def test_new_arrival_during_cleanup_is_reopened(client, configured, monkeypatch):
    row,message=handled(client,configured,monkeypatch)
    replies=iter([[message],[message,{**message,'id':NEW_EMAIL}]])
    restored=[]
    monkeypatch.setattr(provider,'thread_emails',lambda *_:next(replies))
    monkeypatch.setattr(provider,'trash_thread',lambda *_:None)
    monkeypatch.setattr(provider,'restore_thread',lambda *args:restored.append(args))
    retention.run(configured,'EXAMPLE')
    assert restored==[(INBOX,THREAD)]
    assert operations.get('EXAMPLE',row['id'])['error_code']=='retention_restored'
    assert not operations.previously_trashed('EXAMPLE',INBOX,THREAD)


def test_provider_failure_does_not_stop_v7_content_retention(client, configured, monkeypatch):
    row,_=handled(client,configured,monkeypatch)
    monkeypatch.setattr(provider,'thread_emails',lambda *_:(_ for _ in ()).throw(RuntimeError('PRIVATE_PROVIDER_BODY')))
    retention.run(configured,'EXAMPLE')
    assert operations.purge('EXAMPLE','email',1)==1
    result=operations.get('EXAMPLE',row['id'])
    assert result['error_code']=='retention_failed' and 'PRIVATE' not in json.dumps(result)


def test_new_inbound_to_v7_trashed_thread_is_restored_before_reply(client, configured, monkeypatch):
    row,message=handled(client,configured,monkeypatch)
    monkeypatch.setattr(provider,'thread_emails',lambda *_:[message])
    monkeypatch.setattr(provider,'trash_thread',lambda *_:None)
    retention.run(configured,'EXAMPLE')
    operations.purge('EXAMPLE','email',1)
    event={'type':'inbox.email.received','data':{'email_id':NEW_EMAIL,'inbox_id':INBOX,'thread_id':THREAD,
        'thread':{'folder':'trash'},'email':{'id':NEW_EMAIL,'direction':'inbound','from':'visitor@example.net','to':['business@example.com']}}}
    raw=json.dumps(event).encode()
    response=client.post('/channels/email/webhook',data=raw,content_type='application/json',headers=signature(raw))
    assert response.status_code==200 and response.json['queued']
    order=[]
    monkeypatch.setattr(provider,'restore_thread',lambda *_:order.append('restore'))
    monkeypatch.setattr(provider,'receive_inbox',lambda *_:order.append('receive') or received(id=NEW_EMAIL,direction='inbound'))
    fake_answer(monkeypatch,configured)
    from service.channel_worker import process_one
    process_one(configured,'EXAMPLE')
    assert order==['restore','receive']


def test_email_body_is_not_duplicated_into_crm_history():
    from service.message_handler import MessageHandler
    captured=[]
    handler=SimpleNamespace(crm=SimpleNamespace(upsert_lead=lambda *args,**kw:captured.append(kw)),
        analytics=SimpleNamespace(upsert_lead_session=lambda **kw:None),_analytics_lead_id=lambda ctx:'email:session')
    MessageHandler._log_crm(handler,SimpleNamespace(channel='email',tenant='EXAMPLE',session_id='email:session'),
                           'Private inbound mail',{'reply':'Private answer'})
    assert captured[0]['messages']==[] and 'Private' not in json.dumps(captured)


def test_forwarding_preserves_a_verified_business_sender(client, configured, monkeypatch):
    monkeypatch.setenv('V7_EMAIL_SENDERS_JSON','{"business@example.com":"support@client.example"}')
    owner(client)
    current=client.get('/admin/api/business-email-setup?tenant=EXAMPLE').json
    saved=client.put('/admin/api/business-email-setup?tenant=EXAMPLE',json={
        'revision':current['revision'],'settings':{'address':'support@client.example','provider':'microsoft_365','purpose':'support'}})
    assert saved.status_code==200 and saved.json['state']=='routing_configured'
    assert saved.json['forward_to']==['business@example.com']
    assert saved.json['can_enable']
    job=intake(client).json
    operation=operations.get('EXAMPLE',job['reference'])
    assert operation['payload']['sending_address']=='support@client.example'
    sent=[]
    monkeypatch.setattr(provider,'_request',lambda method,path,**kw:sent.append(kw['data']) or {'id':'provider-reference'})
    provider.send_reply(operation,'Approved public support answer')
    assert sent[0]['from']=='support@client.example' and sent[0]['to']==['visitor@example.net']


def test_sender_map_cannot_assign_one_business_identity_to_two_tenants(monkeypatch):
    monkeypatch.setenv('V7_EMAIL_ROUTES_JSON','{"one@example.com":"ONE","two@example.com":"TWO"}')
    monkeypatch.setenv('V7_EMAIL_SENDERS_JSON','{"one@example.com":"support@client.example","two@example.com":"support@client.example"}')
    assert channels.email_senders()=={}


def test_interrupted_cleanup_is_not_repeated_but_content_still_expires(client, configured, monkeypatch):
    row,_=handled(client,configured,monkeypatch)
    job=operations.claim_cleanup('EXAMPLE',row)
    job['payload'].update(cleanup_thread_hash=operations.cleanup_hash(INBOX,THREAD),cleanup_attempted=True)
    operations.save_payload('EXAMPLE',job['id'],job['lease'],job['payload'])
    with operations.connection('EXAMPLE',write=True) as db:
        db.execute('UPDATE business_operations SET lease_until=? WHERE tenant=? AND id=?',(time.time()-1,'EXAMPLE',job['id']))
    monkeypatch.setattr(provider,'trash_thread',lambda *_:pytest.fail('Ambiguous cleanup was repeated'))
    retention.run(configured,'EXAMPLE')
    assert operations.get('EXAMPLE',job['id'])['error_code']=='retention_failed'
    operations.purge('EXAMPLE','email',1)
    assert operations.previously_trashed('EXAMPLE',INBOX,THREAD)


def test_cleanup_accepts_only_its_own_old_reply(client, configured, monkeypatch):
    row,message=handled(client,configured,monkeypatch)
    with operations.connection('EXAMPLE',write=True) as db:
        db.execute('UPDATE business_operations SET provider_id=? WHERE tenant=? AND id=?',
                   (NEW_EMAIL,'EXAMPLE',row['id']))
    outgoing={**message,'id':NEW_EMAIL,'direction':'outbound'}
    calls=[]
    monkeypatch.setattr(provider,'thread_emails',lambda *_:[message,outgoing])
    monkeypatch.setattr(provider,'trash_thread',lambda *args:calls.append(args))
    retention.run(configured,'EXAMPLE')
    assert calls==[(INBOX,THREAD)]
    assert not retention._safe_messages([message,{**outgoing,'id':'manual-reply'}],
        operations.thread_operations('EXAMPLE',INBOX,THREAD),time.time()-86400)


def test_expired_cleanup_lease_cannot_commit_an_outcome(client, configured, monkeypatch):
    row,_=handled(client,configured,monkeypatch)
    job=operations.claim_cleanup('EXAMPLE',row)
    assert operations.claim_cleanup('EXAMPLE',row) is None
    with operations.connection('EXAMPLE',write=True) as db:
        db.execute('UPDATE business_operations SET lease_until=? WHERE tenant=? AND id=?',
                   (time.time()-1,'EXAMPLE',job['id']))
    assert not operations.cleanup_receipt('EXAMPLE',job,'trashed')
    operations.recover_cleanup('EXAMPLE')
    assert operations.get('EXAMPLE',job['id'])['error_code']=='retention_failed'


def test_purge_cannot_clear_memory_claimed_by_a_concurrent_reply(client, configured, monkeypatch):
    from contextlib import contextmanager
    from service.conversation_memory import ConversationMemory
    row,_=handled(client,configured,monkeypatch,opt_in=False)
    memory=ConversationMemory(configured.storage,'EXAMPLE')
    memory.set(row['conversation_id'],'conversation_history',[{'role':'user','content':'Keep active context'}])
    original=ConversationMemory._connection
    @contextmanager
    def raced(self):
        # Interleave a worker's successful claim after purge reads its candidate.
        with operations.connection('EXAMPLE',write=True) as db:
            db.execute("UPDATE business_operations SET state='processing',version=version+1 WHERE tenant=? AND id=?",
                       ('EXAMPLE',row['id']))
        with original(self) as db:
            yield db
    monkeypatch.setattr(ConversationMemory,'_connection',raced)
    assert operations.purge('EXAMPLE','email',1)==0
    with original(memory) as db:
        assert memory._execute(db,'SELECT COUNT(*) FROM conversation_memory WHERE tenant=?',('EXAMPLE',)).fetchone()[0]==1
    assert operations.get('EXAMPLE',row['id'])['state']=='processing'
