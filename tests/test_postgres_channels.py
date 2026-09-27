"""Native PostgreSQL voice channels and tenant-scoped sales requests.

Only provider media, transcription responses and external sends are mocked.
Flask startup, signatures, tenant routing, the agent and storage run normally.
"""
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace

import pytest
from twilio.request_validator import RequestValidator

from app import create_app
from retrieval.storage import Storage
from service import analytics_db, api_usage, session_store, speech_transcription
from service.account_service import AccountService
from service.conversion_actions import ActionError, list_action_requests, submit_action
from service.security import _revision, authenticate_user


def _app(runtime, monkeypatch):
    # Legacy-active fixture tenants have no billing ledger. Do not inherit a
    # developer's external billing credentials while exercising that path.
    for name in ('STRIPE_API_KEY', 'STRIPE_WEBHOOK_SECRET', 'STRIPE_TAX_RATE_ID'):
        monkeypatch.delenv(name, raising=False)
    return create_app({
        'TESTING': True, 'BUSINESS_KEY': runtime['tenant'], 'MODE': 'V7',
        'ENVIRONMENT': 'development', 'BASE_URL': 'http://localhost:10000',
        'SECRET_KEY': 'Native-channel-test-secret-' + runtime['tenant'],
        'WHATSAPP_APP_SECRET': 'native-test-signature-secret',
        'WHATSAPP_TOKEN': 'native-provider-placeholder', 'WHATSAPP_PHONE_ID': '10001',
        'WHATSAPP_TENANT_MAP_JSON': json.dumps({
            '10001': runtime['tenant'], '10002': runtime['other'],
            '447700900901': runtime['tenant'], '447700900902': runtime['other'],
        }),
    })


def _voice_app(runtime, monkeypatch):
    storage = Storage(runtime['tenant'])
    for tenant, marker in [(runtime['tenant'], 'Northstar'), (runtime['other'], 'Harbour')]:
        storage.write_json(tenant, 'faq.json', [{
            'q': 'Do you offer roof surveys?',
            'a': f'{marker} offers roof surveys.', 'tags': ['roof', 'surveys'],
        }])
    # Construct the real agent without a text-provider credential; the fake
    # transcription credential is installed only after construction.
    app = _app(runtime, monkeypatch)
    app.container.for_tenant(runtime['other'])
    downloads, transcriptions, sends = [], [], []

    def download(event, settings):
        downloads.append((event['source'], settings.BUSINESS_KEY))
        return b'OggS' + b'\0' * 32, 'audio/ogg'

    class Provider:
        def __init__(self, **kwargs):
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.transcribe))

        @staticmethod
        def transcribe(**kwargs):
            transcriptions.append(kwargs['model'])
            return SimpleNamespace(text='Do you offer roof surveys?',
                                   usage=SimpleNamespace(type='duration', seconds=9))

    def send(event, reply, settings):
        sends.append((settings.BUSINESS_KEY, settings.WHATSAPP_PHONE_ID, reply))

    monkeypatch.setattr('routes.whatsapp_routes.download_audio', download)
    monkeypatch.setattr('routes.whatsapp_routes.send_reply', send)
    monkeypatch.setattr(speech_transcription, 'OpenAI', Provider)
    monkeypatch.setenv('OPENAI_API_KEY', 'native-transcription-placeholder')
    monkeypatch.setenv('V7_TRANSCRIPTION_MODEL', 'gpt-transcribe')
    return app, downloads, transcriptions, sends


def _cloud_voice(client, phone_id, message_id, *, valid=True):
    body = json.dumps({'entry': [{'changes': [{'value': {
        'metadata': {'phone_number_id': phone_id},
        'messages': [{'id': message_id, 'from': '447700900123', 'type': 'audio',
                      'audio': {'id': '998877', 'mime_type': 'audio/ogg'}}],
    }}]}]}).encode()
    signature = hmac.new(b'native-test-signature-secret', body, hashlib.sha256).hexdigest()
    return client.post('/whatsapp/webhook', data=body, headers={
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': 'sha256=' + (signature if valid else '0' * 64),
    })


def _assert_messages(tenant, message_id):
    with session_store.postgres_connection(tenant) as db:
        rows = db.execute(
            'SELECT event_type,text FROM v7_private.events '
            'WHERE tenant=%s AND message_id IN (%s,%s) ORDER BY event_type',
            (tenant, message_id, message_id + ':out'),
        ).fetchall()
        assert len(rows) == 2
        assert rows[0] == ('msg_in', 'Do you offer roof surveys?')
        assert rows[1][0] == 'msg_out'
        assert db.execute(
            'SELECT state FROM v7_private.webhook_inbox WHERE tenant=%s AND message_id=%s',
            (tenant, message_id),
        ).fetchone()[0] == 'done'
    kpis = analytics_db.get_kpis(tenant=tenant)
    assert kpis['inbound'] == 1 and kpis['outbound'] == 1
    assert api_usage.summary(tenant, 30)['totals']['audio_seconds'] == 9


def test_native_cloud_voice_signature_tenant_map_and_duplicate_replay(pg_runtime, monkeypatch):
    app, downloads, transcriptions, sends = _voice_app(pg_runtime, monkeypatch)
    client = app.test_client()
    assert _cloud_voice(client, '10002', 'voice-bad', valid=False).status_code == 403
    assert _cloud_voice(client, '99999', 'voice-unmapped').status_code == 403
    assert downloads == transcriptions == sends == []

    # Reusing a provider ID in another mapped company must not suppress its reply.
    for phone, tenant, marker in [('10002', pg_runtime['other'], 'Harbour'),
                                 ('10001', pg_runtime['tenant'], 'Northstar')]:
        assert _cloud_voice(client, phone, 'wamid.native-voice').status_code == 200
        assert _cloud_voice(client, phone, 'wamid.native-voice').status_code == 200
        assert sends[-1][:2] == (tenant, phone)
        assert marker in sends[-1][2]
        _assert_messages(tenant, 'wamid.native-voice')
    assert len(downloads) == len(transcriptions) == len(sends) == 2
    assert downloads == [('cloud', pg_runtime['other']), ('cloud', pg_runtime['tenant'])]
    assert not (pg_runtime['root'] / 'logs/security.db').exists()
    assert not (pg_runtime['root'] / 'logs/crm_snapshot.json').exists()


def test_native_twilio_voice_signature_and_cached_reply(pg_runtime, monkeypatch):
    app, downloads, transcriptions, sends = _voice_app(pg_runtime, monkeypatch)
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'native-twilio-test-token')
    client = app.test_client()
    form = {'From': 'whatsapp:+447700900123', 'To': 'whatsapp:+447700900902',
            'Body': '', 'MessageSid': 'SMnative-voice', 'NumMedia': '1',
            'MediaContentType0': 'audio/ogg', 'MediaUrl0': 'https://api.twilio.com/test-media'}
    signature = RequestValidator('native-twilio-test-token').compute_signature(
        app.container.settings.BASE_URL + '/whatsapp/webhook', form)
    assert client.post('/whatsapp/webhook', data=form,
                       headers={'X-Twilio-Signature': 'invalid'}).status_code == 403
    assert downloads == transcriptions == []
    first = client.post('/whatsapp/webhook', data=form, headers={'X-Twilio-Signature': signature})
    repeated = client.post('/whatsapp/webhook', data=form, headers={'X-Twilio-Signature': signature})
    assert first.status_code == repeated.status_code == 200
    assert first.data == repeated.data and b'Harbour' in first.data
    assert downloads == [('twilio', pg_runtime['other'])]
    assert len(transcriptions) == 1 and sends == []  # Twilio replies are returned as TwiML.
    _assert_messages(pg_runtime['other'], 'SMnative-voice')
    assert analytics_db.get_kpis(tenant=pg_runtime['tenant'])['inbound'] == 0


def _configure_actions(runtime):
    start = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    config = {'consultation': {'enabled': True, 'slots': [
        {'id': 'consultation-one', 'start_at': start, 'label': 'Design consultation'},
    ]}, 'quote': {'enabled': True}, 'callback': {'enabled': True}}
    storage = Storage(runtime['tenant'])
    for tenant in (runtime['tenant'], runtime['other']):
        storage.write_json(tenant, 'sales_actions.json', config)
    return storage


def _booking(key='booking-one'):
    return {'action': 'consultation', 'slot_id': 'consultation-one', 'name': 'Test customer',
            'contact': 'customer@example.test', 'details': 'A design consultation',
            'consent': True, 'idempotency_key': key}


def _owner_client(app, runtime):
    email = runtime['tenant'].lower() + '@example.test'
    AccountService(app.container.storage).create_account(runtime['tenant'], {
        'email': email, 'password': 'Native-owner-test-password-123', 'roles': ['business_owner'],
    })
    with app.app_context():
        account = authenticate_user(app.container, email=email,
                                    password='Native-owner-test-password-123', tenant=runtime['tenant'])
        identity = {name: account[name] for name in ('id', 'email', 'roles', 'tenant')}
        token = session_store.create(identity, _revision(identity))
    client = app.test_client()
    # Seed a real revocable post-MFA session to isolate route authorization.
    with client.session_transaction() as state:
        state['user'], state['management_token'] = identity, token
    return client


def test_native_booking_routes_idempotency_conflict_and_owner_scope(pg_runtime, monkeypatch):
    _configure_actions(pg_runtime)
    app = _app(pg_runtime, monkeypatch)
    client = app.test_client()
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    available = client.get('/chat/actions?tenant=' + tenant).get_json()
    other_token = client.get('/chat/actions?tenant=' + other).get_json()['conversation_token']
    assert [slot['id'] for slot in available['consultation']['slots']] == ['consultation-one']
    payload = {**_booking(), 'tenant': tenant, 'conversation_token': available['conversation_token']}
    assert client.post('/chat/actions', json={**payload, 'conversation_token': other_token}).status_code == 403
    assert client.post('/chat/actions', json=payload,
                       headers={'Origin': 'https://unapproved.example'}).status_code == 403
    first = client.post('/chat/actions', json=payload)
    assert first.status_code == 200 and first.get_json()['status'] == 'confirmed'
    assert client.post('/chat/actions', json=payload).get_json() == first.get_json()
    conflict = client.post('/chat/actions', json={**payload, 'details': 'Changed details'})
    assert conflict.status_code == 409 and conflict.get_json()['error'] == 'idempotency_conflict'
    occupied = client.post('/chat/actions', json={**payload, 'idempotency_key': 'new-booking'})
    assert occupied.status_code == 409 and occupied.get_json()['error'] == 'slot_unavailable'
    assert client.get('/chat/actions?tenant=' + tenant).get_json()['consultation']['slots'] == []
    second = client.post('/chat/actions', json={**payload, 'tenant': other, 'conversation_token': other_token})
    assert second.status_code == 200 and second.get_json()['reference'] != first.get_json()['reference']
    assert len(list_action_requests(tenant)) == len(list_action_requests(other)) == 1

    owner = _owner_client(app, pg_runtime)
    own = owner.get('/admin/api/action-requests?tenant=' + tenant)
    assert own.status_code == 200
    assert [row['reference'] for row in own.get_json()['requests']] == [first.get_json()['reference']]
    assert owner.get('/admin/api/action-requests?tenant=' + other).status_code == 403
    with session_store.postgres_connection(tenant) as db:
        assert db.execute('SELECT reference FROM v7_private.sales_action_requests '
                          'WHERE tenant=%s', (other,)).fetchall() == []


@pytest.mark.parametrize('same_key', [False, True])
def test_native_concurrent_slot_requests_are_serialized(pg_runtime, same_key):
    storage = _configure_actions(pg_runtime)
    barrier = Barrier(2)
    tenant = pg_runtime['tenant']

    def reserve(number):
        barrier.wait(timeout=10)
        try:
            return submit_action(storage, tenant, _booking('same-key' if same_key else f'booking-{number}'),
                                 tenant + '-booking-client-' + str(number))
        except ActionError as error:
            return {'error': error.code, 'status_code': error.status}

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, [1, 2]))
    confirmed = [result for result in results if result.get('status') == 'confirmed']
    if same_key:
        assert len(confirmed) == 2 and confirmed[0] == confirmed[1]
    else:
        assert len(confirmed) == 1
        assert {'error': 'slot_unavailable', 'status_code': 409} in results
    rows = list_action_requests(tenant)
    assert len(rows) == 1 and rows[0]['reference'] == confirmed[0]['reference']
    assert list_action_requests(pg_runtime['other']) == []


def test_native_quote_callback_validation_and_tenant_scoped_keys(pg_runtime):
    storage = _configure_actions(pg_runtime)
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    quote = {**_booking('request-key'), 'action': 'quote'}
    quote.pop('slot_id')
    with pytest.raises(ActionError, match='consent_required'):
        submit_action(storage, tenant, {**quote, 'consent': False}, tenant + '-quote')
    with pytest.raises(ActionError, match='invalid_contact'):
        submit_action(storage, tenant, {**quote, 'action': 'callback'}, tenant + '-quote')
    first = submit_action(storage, tenant, quote, tenant + '-quote')
    repeated = submit_action(storage, tenant, quote, tenant + '-quote')
    second = submit_action(storage, other, quote, other + '-quote')
    callback = submit_action(storage, tenant, {**quote, 'action': 'callback',
                             'contact': '+447700900123', 'idempotency_key': 'callback-key'}, tenant + '-quote')
    assert first == repeated and first['status'] == second['status'] == callback['status'] == 'requested'
    assert first['reference'] != second['reference']
    assert {row['action'] for row in list_action_requests(tenant)} == {'quote', 'callback'}
    assert [row['reference'] for row in list_action_requests(other)] == [second['reference']]
