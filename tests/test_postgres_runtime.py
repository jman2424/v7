"""Native PostgreSQL storage, isolation and customer-channel regressions."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace

import pytest

from retrieval.storage import Storage
from service import analytics_db, api_usage, session_store, speech_transcription
from service.account_service import AccountService
from service.audit import AuditService
from service.crm_service import CRMService
from service.storage_readiness import validate_postgres_storage


def test_native_storage_scope_rollback_and_concurrent_accounts(pg_runtime):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    storage = Storage(tenant)
    validate_postgres_storage(tenant)
    with session_store.postgres_connection(tenant) as db:
        assert db.execute('SELECT count(*) FROM v7_private.business_documents '
                          'WHERE tenant=%s', (other,)).fetchone()[0] == 0
    with pytest.raises(RuntimeError, match='database operation failed'):
        with session_store.postgres_connection(tenant) as db:
            db.execute("INSERT INTO v7_private.business_documents(tenant,filename,payload) "
                       "VALUES(%s,'cross.json','{}')", (other,))
    with pytest.raises(ValueError, match='rollback'):
        with storage.write_lock(tenant):
            storage._write_json(tenant, 'notes.json', {'test':True})
            raise ValueError('rollback')
    with pytest.raises(FileNotFoundError):
        storage.read_json(tenant, 'notes.json')
    accounts = AccountService(storage)
    def create(number):
        return accounts.create_account(tenant, {'email':f'user{number}@example.test',
            'password':'A-long-test-password-'+str(number), 'roles':['business_staff']})
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert len(list(executor.map(create, [1,2]))) == 2
    assert len(accounts.list_accounts(tenant)) == 2
    assert accounts.list_accounts(other) == []
    assert not (pg_runtime['root']/'business').exists()
    assert not (pg_runtime['root']/'logs/security.db').exists()


def test_native_crm_persists_and_cannot_cross_tenants(pg_runtime):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    crm = CRMService()
    lead = crm.upsert_lead(tenant, name='Test lead', phone='01234567890',
                           session_id='test-chat', channel='web')
    crm.append_conversation(tenant, lead['id'], {'text':'Test message'})
    reopened = CRMService()
    assert reopened.get_lead(tenant, lead['id'])['name'] == 'Test lead'
    assert len(reopened.get_lead(tenant, lead['id'])['conversations']) == 1
    assert reopened.get_lead(other, lead['id']) is None
    assert reopened.update_status(other, lead['id'], 'Won') is False
    assert reopened.list_leads(tenant=other) == []
    assert not (pg_runtime['root']/'logs/crm_snapshot.json').exists()


def test_native_document_batch_preserves_tenant_scope_and_missing_values(pg_runtime):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    storage = Storage(tenant)
    storage.write_json(tenant, 'null.json', None)
    names = ('store_info.json', 'null.json', 'missing.json')
    assert storage.read_json_many(tenant, names) == {
        'store_info.json': storage.read_json(tenant, 'store_info.json'), 'null.json': None,
    }
    other_documents = storage.read_json_many(other, names)
    assert other_documents == {'store_info.json': storage.read_json(other, 'store_info.json')}
    assert other_documents['store_info.json']['name'] != storage.read_json(tenant, 'store_info.json')['name']
    with session_store.postgres_connection(tenant) as db:
        assert db.execute('SELECT filename, payload FROM v7_private.business_documents '
                          'WHERE tenant=%s AND filename=ANY(%s)', (other, list(names))).fetchall() == []


def test_native_events_usage_and_append_only_audit(pg_runtime, monkeypatch):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    analytics_db.log_message(tenant=tenant, channel='web', direction='inbound',
                             session_id='session', text='Test message', message_id='one')
    analytics_db.log_message(tenant=tenant, channel='web', direction='inbound',
                             session_id='session', text='Test message', message_id='one')
    assert analytics_db.get_kpis(tenant=tenant)['inbound'] == 1
    assert analytics_db.get_kpis(tenant=other)['inbound'] == 0
    class Provider:
        def __init__(self, **kwargs):
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=lambda **params:
                SimpleNamespace(text='Book a consultation', usage=SimpleNamespace(type='duration', seconds=12))))
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-placeholder')
    monkeypatch.setenv('V7_TRANSCRIPTION_MODEL', 'gpt-transcribe')
    monkeypatch.setattr(speech_transcription, 'OpenAI', Provider)
    assert speech_transcription.transcribe_audio(b'OggS'+b'\0'*32, 'audio/ogg',
        tenant=tenant, channel='web') == 'Book a consultation'
    assert api_usage.summary(tenant, 30)['totals']['audio_seconds'] == 12
    assert api_usage.summary(other, 30)['totals']['calls'] == 0
    AuditService().record(user='test', role='platform_admin', ip='127.0.0.1',
                          action='native_test', target=tenant)
    with session_store.postgres_connection() as db:
        assert db.execute('SELECT count(*) FROM v7_private.audit_records '
                          "WHERE payload->>'target'=%s", (tenant,)).fetchone()[0] == 1
    with pytest.raises(RuntimeError, match='database operation failed'):
        with session_store.postgres_connection() as db:
            db.execute('DELETE FROM v7_private.audit_records')
    assert not (pg_runtime['root']/'logs/selfrepair.log').exists()


def test_native_startup_and_widget_transcription_boundary(pg_runtime, monkeypatch):
    from app import create_app
    from routes import webchat_routes
    tenant = pg_runtime['tenant']
    app = create_app({'TESTING':True, 'BUSINESS_KEY':tenant, 'MODE':'V7',
                      'SECRET_KEY':'native-test-secret-with-at-least-32-characters'})
    client = app.test_client()
    assert client.get('/health').status_code == 200
    monkeypatch.setattr(webchat_routes, 'transcribe_audio', lambda *args, **kwargs:'Please call me')
    with app.app_context():
        signed = webchat_routes._transcription_signer().dumps({'tenant':tenant})
        wrong = webchat_routes._transcription_signer().dumps({'tenant':pg_runtime['other']})
    def post(token, origin=None):
        headers = {'X-V7-Transcription-Token':token}
        if origin:
            headers['Origin'] = origin
        return client.post('/chat/transcribe?tenant='+tenant, headers=headers,
            data={'audio':(BytesIO(b'\x1a\x45\xdf\xa3'+b'\0'*32),'voice.webm','audio/webm')})
    assert post(wrong).status_code == 403
    assert post(signed,'https://not-approved.example').status_code == 403
    assert post(signed).get_json() == {'text':'Please call me'}


def test_native_startup_rejects_missing_tenant_and_disabled_rls(pg_runtime):
    with pytest.raises(RuntimeError, match='must be imported'):
        validate_postgres_storage('UNKNOWN_TEST_TENANT')
    admin = pg_runtime['admin']
    constraint = admin.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='v7_private.document_versions'::regclass "
        "AND conname='document_versions_filename_check'").fetchone()[0]
    try:
        admin.execute('ALTER TABLE v7_private.document_versions DROP CONSTRAINT document_versions_filename_check')
        admin.execute("ALTER TABLE v7_private.document_versions ADD CONSTRAINT document_versions_filename_check "
                      "CHECK(filename ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$') NOT VALID")
        with pytest.raises(RuntimeError, match='migrations are incomplete'):
            validate_postgres_storage(pg_runtime['tenant'])
    finally:
        admin.execute('ALTER TABLE v7_private.document_versions DROP CONSTRAINT document_versions_filename_check')
        admin.execute('ALTER TABLE v7_private.document_versions ADD CONSTRAINT document_versions_filename_check '+constraint)
    try:
        admin.execute('ALTER TABLE v7_private.crm_records DISABLE ROW LEVEL SECURITY')
        with pytest.raises(RuntimeError, match='restricted PostgreSQL schema'):
            validate_postgres_storage(pg_runtime['tenant'])
    finally:
        admin.execute('ALTER TABLE v7_private.crm_records ENABLE ROW LEVEL SECURITY')
