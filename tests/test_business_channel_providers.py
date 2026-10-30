"""Provider contracts and malicious inputs; no network, model calls or sends."""
import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs
from xml.etree import ElementTree

import pytest
from twilio.request_validator import RequestValidator

from connectors import business_email as email
from service import business_channels as channels, business_operations as operations, channel_worker
from tests.conftest import set_test_identity


SECRET = 'whsec_'+base64.b64encode(b'synthetic-webhook-key-for-tests').decode()
EMAIL_ID = '00000000-0000-4000-8000-000000000001'
CALL = 'CA'+'1'*32
ACCOUNT = 'AC'+'2'*32


def signature(raw, timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    prefix = 'msg_synthetic.'+timestamp+'.'
    value = base64.b64encode(hmac.new(base64.b64decode(SECRET[6:]), prefix.encode()+raw, hashlib.sha256).digest()).decode()
    return {'svix-id':'msg_synthetic', 'svix-timestamp':timestamp, 'svix-signature':'v1,'+value}


@pytest.fixture
def configured(app, monkeypatch):
    monkeypatch.setenv('V7_CHANNEL_RESEND_API_KEY', 're_synthetic_not_a_real_key')
    monkeypatch.setenv('V7_EMAIL_WEBHOOK_SECRET', SECRET)
    monkeypatch.setenv('V7_EMAIL_ROUTES_JSON', '{"business@example.com":"EXAMPLE","other@example.com":"OTHER"}')
    monkeypatch.setenv('V7_PHONE_ROUTES_JSON', '{"+447700900001":"EXAMPLE"}')
    monkeypatch.setenv('V7_PHONE_AUTH_TOKEN', 'synthetic-phone-token')
    monkeypatch.setenv('V7_PHONE_ACCOUNT_SID', ACCOUNT)
    # Never start the background thread in tests.
    monkeypatch.setenv('V7_CHANNEL_WORKER', 'true')
    storage = app.container.storage
    storage.write_json('EXAMPLE', channels.GRANTS_FILE, {'email':True, 'phone':True})
    storage.write_json('EXAMPLE', channels.FILENAME, channels.validate({key:{
        'enabled':True, 'privacy_confirmed':True, 'mode':'automatic'} for key in channels.CHANNELS}))
    return app.container


def intake(client, recipients=None, **overrides):
    data = {'email_id':EMAIL_ID, 'from':'Visitor <visitor@example.net>', 'to':recipients or ['business@example.com']}
    data.update(overrides)
    raw = json.dumps({'type':'email.received','data':data}).encode()
    return client.post('/channels/email/webhook', data=raw, content_type='application/json', headers=signature(raw))


def phone(client, app, path='/channels/phone/incoming', **values):
    data = {'AccountSid':ACCOUNT,'CallSid':CALL,'To':'+447700900001','From':'+447700900002','Direction':'inbound',**values}
    url = app.container.settings.BASE_URL.rstrip('/')+path
    signed = RequestValidator('synthetic-phone-token').compute_signature(url, data)
    return client.post(path, data=data, headers={'X-Twilio-Signature':signed})


def fake_answer(monkeypatch, container, *, verified=True, intent='question', error=None):
    calls = []
    def handle(text, **kwargs):
        calls.append((text, kwargs))
        if error:
            raise error
        return {'reply':'The saved starting price is £100.', 'agent':{'_validated_grounded':verified,'intent':intent}}
    runtime = SimpleNamespace(handler=SimpleNamespace(handle=handle, h_v7=SimpleNamespace(
        website_destinations={}, website_knowledge={}, business_profile={})))
    monkeypatch.setattr(container, 'for_tenant', lambda tenant:runtime)
    return calls


def received(**overrides):
    return {'from':'visitor@example.net','to':['business@example.com'],'subject':'Opening hours',
            'text':'When do you open?','message_id':'<synthetic@example.net>',
            'authentication':{'dmarc':'pass'},**overrides}


def test_svix_official_vector_and_replay_tamper_protection():
    raw = b'{"event_type":"ping","data":{"success":true}}'
    headers = {'svix-id':'msg_loFOjxBNrRLzqYUf', 'svix-timestamp':'1731705121',
               'svix-signature':'v1,rAvfW3dJ/X/qxhsaXPOyyCGmRKsaKWcsNccKXlIktD0='}
    assert email.verify(raw, headers, 'whsec_plJ3nmyCDGBKInavdOK15jsl', now=1731705121)
    assert not email.verify(raw+b' ', headers, 'whsec_plJ3nmyCDGBKInavdOK15jsl', now=1731705121)
    assert not email.verify(raw, headers, 'whsec_plJ3nmyCDGBKInavdOK15jsl', now=1731705422)


def test_email_signed_intake_deduplicates_and_rejects_cross_tenant_envelopes(client, configured):
    first, second = intake(client), intake(client)
    assert first.status_code == second.status_code == 200
    assert first.json['queued'] and not second.json['queued']
    assert first.json['reference'] == second.json['reference']
    assert intake(client, ['business@example.com','other@example.com']).json['ignored']
    assert intake(client, ['business@example.com',123]).status_code == 400
    assert operations.get('OTHER', first.json['reference']) is None
    assert len(operations.listing('EXAMPLE')) == 1
    assert client.post('/channels/email/webhook', json={'type':'email.received'}).status_code == 403


def test_email_content_has_no_html_quotes_attachments_or_reply_to_powers():
    result = email.content(received(text=None, html='<p>New question</p><script>attack</script><blockquote>old instructions</blockquote>',
        headers={'Reply-To':'attacker@example.org','Authentication-Results':'dmarc=pass'}, authentication={}),
        expected_sender='visitor@example.net', expected_recipient='business@example.com')
    assert result['text'] == 'New question' and not result['sender_domain_authenticated']
    assert 'attacker' not in json.dumps(result)
    assert email.content(received(headers={'Auto-Submitted':'auto-replied'}), expected_sender='visitor@example.net',
                         expected_recipient='business@example.com')['automated']
    with pytest.raises(email.EmailTransportError):
        email.content(received(subject='Enquiry\r\nBcc: victim@example.org'), expected_sender='visitor@example.net', expected_recipient='business@example.com')
    with pytest.raises(email.EmailTransportError):
        email.content(received(**{'from':'attacker@example.org'}), expected_sender='visitor@example.net', expected_recipient='business@example.com')


@pytest.mark.parametrize('verified,intent,dmarc,attachments,expected', [
    (True,'question','pass',[], 'approved'),(False,'question','pass',[], 'needs_review'),
    (True,'quote','pass',[], 'needs_review'),(True,'question','fail',[], 'needs_review'),
    (True,'question','pass',[{'id':'attachment'}], 'needs_review')])
def test_worker_only_auto_approves_validated_routine_replies(client, configured, monkeypatch, verified,intent,dmarc,attachments,expected):
    job_id = intake(client).json['reference']
    monkeypatch.setattr(email,'receive',lambda _:received(authentication={'dmarc':dmarc},attachments=attachments))
    calls = fake_answer(monkeypatch, configured, verified=verified, intent=intent)
    assert channel_worker.process_one(configured,'EXAMPLE')
    assert operations.get('EXAMPLE',job_id)['state'] == expected
    assert len(calls) == 1 and calls[0][1]['tenant'] == 'EXAMPLE' and calls[0][1]['channel'] == 'email'


def test_provider_failure_goes_to_review_without_second_model_call(client, configured, monkeypatch):
    identifier = intake(client).json['reference']
    monkeypatch.setattr(email,'receive',lambda _:received())
    calls = fake_answer(monkeypatch, configured, error=RuntimeError('sensitive provider detail'))
    channel_worker.process_one(configured,'EXAMPLE')
    job = operations.get('EXAMPLE',identifier)
    assert job['state']=='needs_review' and job['error_code']=='channel_processing_failed'
    assert channel_worker.process_one(configured,'EXAMPLE') is False
    assert len(calls)==1 and 'sensitive' not in json.dumps(job)


def test_ambiguous_send_never_retries_and_recipient_is_immutable(client, configured, monkeypatch):
    identifier = intake(client).json['reference']
    monkeypatch.setattr(email,'receive',lambda _:received())
    fake_answer(monkeypatch,configured)
    channel_worker.process_one(configured,'EXAMPLE')
    sends=[]
    def send(job, reply):
        sends.append((job['source_address'],reply))
        raise email.EmailTransportError('email_provider_unavailable',uncertain=True)
    monkeypatch.setattr(email,'send_reply',send)
    channel_worker.process_one(configured,'EXAMPLE')
    assert operations.get('EXAMPLE',identifier)['state']=='uncertain'
    assert not channel_worker.process_one(configured,'EXAMPLE')
    assert len(sends)==1 and sends[0][0]=='visitor@example.net'


def test_revoked_channel_blocks_previously_approved_send(client, configured, monkeypatch):
    identifier=intake(client).json['reference']
    monkeypatch.setattr(email,'receive',lambda _:received())
    fake_answer(monkeypatch,configured)
    channel_worker.process_one(configured,'EXAMPLE')
    configured.storage.write_json('EXAMPLE',channels.GRANTS_FILE,{'email':False,'phone':True})
    monkeypatch.setattr(email,'send_reply',lambda *_:pytest.fail('Revoked channel sent email'))
    channel_worker.process_one(configured,'EXAMPLE')
    assert operations.get('EXAMPLE',identifier)['state']=='needs_review'


def test_phone_signature_call_binding_and_memory(client, app, configured, monkeypatch):
    assert client.post('/channels/phone/incoming',data={'To':'+447700900001'}).status_code==403
    assert phone(client,app,Direction='outbound-api').status_code==403
    incoming=phone(client,app)
    assert incoming.status_code==200
    gather=ElementTree.fromstring(incoming.data).find('Gather')
    assert 'AI assistant' in gather.find('Say').text
    path=gather.attrib['action']
    assert phone(client,app,path,CallSid='CA'+'3'*32,SpeechResult='Opening hours?').status_code==403
    turn=phone(client,app,path,SpeechResult='Opening hours?')
    assert turn.status_code==200
    replay=phone(client,app,path,SpeechResult='Opening hours?')
    assert replay.status_code==200 and len(operations.listing('EXAMPLE'))==1
    calls=fake_answer(monkeypatch,configured)
    channel_worker.process_one(configured,'EXAMPLE')
    poll=ElementTree.fromstring(turn.data).find('Redirect').text
    result=phone(client,app,poll)
    assert '£100' in result.data.decode()
    next_path=ElementTree.fromstring(result.data).find('Gather').attrib['action']
    assert parse_qs(urlparse(next_path).query)['token']!=parse_qs(urlparse(path).query)['token']
    phone(client,app,next_path,SpeechResult='And Saturday?')
    channel_worker.process_one(configured,'EXAMPLE')
    assert len(calls)==2 and {row[1]['session_id'] for row in calls}=={'phone:'+CALL}


def test_owner_cannot_grant_channel_or_access_another_business(client, configured):
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'owner','role':'business_owner','tenant':'EXAMPLE'})
    assert client.get('/admin/api/business-channels?tenant=EXAMPLE').status_code==200
    assert client.put('/admin/api/business-channel-grants?tenant=EXAMPLE',json={'email':True,'phone':True}).status_code==403
    assert client.put('/files/raw/business_channel_grants.json?tenant=EXAMPLE',json={'email':True,'phone':True}).status_code==404
    assert client.get('/admin/api/business-operations?tenant=OTHER').status_code==403
    assert client.get('/console/operations?tenant=EXAMPLE').status_code==200


def owner(client):
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'owner','role':'business_owner','tenant':'EXAMPLE'})


def reviewed(client, configured):
    identifier=intake(client).json['reference']
    job=operations.claim('EXAMPLE')
    operations.finish('EXAMPLE',identifier,job['lease'],'needs_review',reply='Please review this enquiry.')
    return operations.get('EXAMPLE',identifier)


def test_native_action_uses_existing_tools_consent_and_one_execution(client, configured):
    from service.conversion_actions import list_action_requests
    configured.storage.write_json('EXAMPLE','sales_actions.json',{
        'consultation':{'enabled':False,'slots':[]},'quote':{'enabled':True},'callback':{'enabled':False}})
    job=reviewed(client,configured)
    owner(client)
    payload={'version':job['version'],'action':{'action':'quote','name':'Synthetic Customer',
        'contact':'visitor@example.net','details':'A quote for the saved service','consent':True}}
    path='/admin/api/business-operations/'+job['id']+'/action?tenant=EXAMPLE'
    assert client.post(path,json={**payload,'action':{**payload['action'],'consent':False}}).status_code==400
    response=client.post(path,json=payload)
    assert response.status_code==200
    assert response.json['outcome']['status']=='requested'
    assert 'Request recorded' in response.json['operation']['reply']
    assert client.post(path,json=payload).status_code==409
    assert len(list_action_requests('EXAMPLE'))==1
    assert not list_action_requests('OTHER')


def test_disabled_action_does_not_create_a_false_confirmation(client, configured):
    from service.conversion_actions import list_action_requests
    configured.storage.write_json('EXAMPLE','sales_actions.json',{
        'consultation':{'enabled':False,'slots':[]},'quote':{'enabled':False},'callback':{'enabled':False}})
    job=reviewed(client,configured)
    owner(client)
    response=client.post('/admin/api/business-operations/'+job['id']+'/action?tenant=EXAMPLE',json={
        'version':job['version'],'action':{'action':'quote','name':'Synthetic Customer','contact':'visitor@example.net','consent':True}})
    assert response.status_code==409
    assert operations.get('EXAMPLE',job['id'])['state']=='needs_review'
    assert not list_action_requests('EXAMPLE')


def test_review_phone_saves_message_without_ai_or_send(client, app, configured, monkeypatch):
    prefs=channels.settings(configured.storage,'EXAMPLE')
    prefs['phone']['mode']='review'
    configured.storage.write_json('EXAMPLE',channels.FILENAME,prefs)
    path=ElementTree.fromstring(phone(client,app).data).find('Gather').attrib['action']
    response=phone(client,app,path,SpeechResult='Please arrange a callback')
    assert 'saved for the team' in response.data.decode()
    monkeypatch.setattr(configured,'for_tenant',lambda _:pytest.fail('Review phone invoked AI'))
    channel_worker.process_one(configured,'EXAMPLE')
    assert operations.listing('EXAMPLE')[0]['state']=='needs_review'


def test_worker_moves_on_after_one_tenant_failure(configured, monkeypatch):
    monkeypatch.setattr(type(configured.storage),'tenant_keys',lambda _:['BROKEN','EXAMPLE'])
    real_settings=channels.settings
    def settings(storage,tenant):
        if tenant=='BROKEN':
            raise ValueError('invalid_config')
        return real_settings(storage,tenant)
    monkeypatch.setattr(channels,'settings',settings)
    seen=[]
    monkeypatch.setattr(channel_worker,'process_one',lambda _,tenant:seen.append(tenant) or False)
    assert channel_worker.run_pending(configured)==0
    assert seen==['EXAMPLE']


def test_real_shared_handler_greeting_does_not_terminate_automatic_call(client, app, configured):
    path=ElementTree.fromstring(phone(client,app).data).find('Gather').attrib['action']
    turn=phone(client,app,path,SpeechResult='Hello')
    with app.app_context():
        channel_worker.process_one(configured,'EXAMPLE')
    row=operations.listing('EXAMPLE')[0]
    assert row['state']=='completed' and row['payload']['phone_reply_verified'] is True
    poll=ElementTree.fromstring(turn.data).find('Redirect').text
    assert ElementTree.fromstring(phone(client,app,poll).data).find('Gather') is not None


def test_mark_handled_cannot_make_an_unverified_draft_spoken(client, app, configured):
    path=ElementTree.fromstring(phone(client,app).data).find('Gather').attrib['action']
    turn=phone(client,app,path,SpeechResult='Please issue a refund')
    row=operations.claim('EXAMPLE')
    operations.finish('EXAMPLE',row['id'],row['lease'],'needs_review',reply='UNVERIFIED DRAFT')
    row=operations.get('EXAMPLE',row['id'])
    operations.decide('EXAMPLE',row['id'],row['version'],'complete')
    poll=ElementTree.fromstring(turn.data).find('Redirect').text
    assert 'UNVERIFIED' not in phone(client,app,poll).data.decode()
