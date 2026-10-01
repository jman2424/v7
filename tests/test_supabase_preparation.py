"""Offline migration safety checks and optional real PostgreSQL policy checks."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scripts import prepare_supabase as preparation
from scripts.prepare_supabase import prepare, import_bundle, verify, connection


@pytest.fixture
def source(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    with closing(sqlite3.connect(logs / 'security.db')) as db, db:
        db.execute('CREATE TABLE billing_discounts (tenant TEXT PRIMARY KEY, campaign TEXT NOT NULL)')
        db.execute("INSERT INTO billing_discounts VALUES ('ALPHA','platform-recurring-half-v1')")
        db.execute('CREATE TABLE managed_businesses (tenant TEXT PRIMARY KEY, owner TEXT)')
        db.execute('INSERT INTO managed_businesses VALUES (?,?)', ('ALPHA','owner-identity'))
        db.execute('CREATE TABLE management_sessions (token_hash TEXT PRIMARY KEY, identity TEXT, revision TEXT, expires REAL)')
        db.execute("INSERT INTO management_sessions VALUES ('session-hash','{}','revision',99)")
        db.execute('CREATE TABLE account_authenticators (account TEXT PRIMARY KEY, secret TEXT NOT NULL)')
        db.execute("INSERT INTO account_authenticators VALUES ('account-id','test-authenticator-secret')")
        db.execute('CREATE TABLE auth_login_failures (attempt TEXT PRIMARY KEY, subject_hash TEXT NOT NULL, attempted REAL NOT NULL)')
        db.execute('INSERT INTO auth_login_failures VALUES (?,?,?)', ('test-attempt', 'a' * 64, 123.0))
        db.execute('CREATE TABLE mfa_code_uses (account TEXT, secret_hash TEXT, timestep INTEGER, PRIMARY KEY(account,secret_hash,timestep))')
        db.execute('INSERT INTO mfa_code_uses VALUES (?,?,?)', ('account-id', 'b' * 64, 123))
        db.execute('CREATE TABLE trusted_devices (token_hash TEXT PRIMARY KEY, account TEXT, revision TEXT, expires REAL)')
        db.execute('INSERT INTO trusted_devices VALUES (?,?,?,?)', ('c' * 64, 'account-id', 'd' * 64, 999))
        db.execute('CREATE TABLE oidc_states (state_hash TEXT PRIMARY KEY, verifier TEXT)')
        db.execute('INSERT INTO oidc_states VALUES (?,?)', ('e' * 64, 'test-only-verifier'))
        db.execute('CREATE TABLE oidc_links (provider TEXT, client_id TEXT, issuer TEXT, subject TEXT, account TEXT, identity TEXT, created REAL)')
        db.execute('INSERT INTO oidc_links VALUES (?,?,?,?,?,?,?)',
                   ('google', 'test-client', 'https://accounts.google.com', 'test-subject', 'account-id', '{}', 123))
    with closing(sqlite3.connect(logs / 'analytics.db')) as db, db:
        db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, tenant TEXT NOT NULL, channel TEXT NOT NULL, session_id TEXT NOT NULL, event_type TEXT NOT NULL, meta_json TEXT)')
        db.execute("INSERT INTO events VALUES (7,'2026-09-16T00:00:00Z','ALPHA','web','chat-id','msg_in','{}')")
    for tenant in ['ALPHA','BETA']:
        folder = tmp_path / 'business' / tenant
        folder.mkdir(parents=True)
        (folder / 'catalog.json').write_text(json.dumps({'products':[tenant]}))
        (folder / 'owner_accounts.json').write_text(json.dumps([{'id':tenant,'password_hash':'test-only-hash','roles':['business_owner']}]))
    version = tmp_path / 'business/versions/2026-09-26/ALPHA'
    version.mkdir(parents=True)
    (version / 'catalog.json').write_text(json.dumps({'products': ['previous-alpha']}))
    (version / '_snapshot.json').write_text(json.dumps({
        'tenant': 'ALPHA', 'created_at': '2026-09-26T00:00:00Z', 'source': 'business/ALPHA',
    }))
    (logs / 'selfrepair.log').write_text(json.dumps({'action':'test','target':'ALPHA'})+'\n')
    return tmp_path


def test_offline_inventory_preserves_sources_and_redacts_sessions(source):
    before = {str(path):path.read_bytes() for path in source.rglob('*') if path.is_file()}
    bundle = prepare(source)
    assert bundle.counts()['tenants'] == 2
    assert bundle.counts()['business_documents'] == 4
    assert bundle.counts()['document_versions'] == 2
    assert next(row for row in bundle.rows['document_versions']
                if row['filename'] == '_snapshot.json')['payload'] == {
        'tenant': 'ALPHA', 'created_at': '2026-09-26T00:00:00Z', 'source': 'business/ALPHA',
    }
    assert bundle.rows['management_sessions'] == []
    assert bundle.skipped['management_sessions'] == 1
    assert bundle.rows['account_authenticators'][0]['secret'] == 'test-authenticator-secret'
    assert bundle.rows['auth_login_failures'] == [{'attempt': 'test-attempt', 'subject_hash': 'a' * 64, 'attempted': 123.0}]
    assert bundle.rows['mfa_code_uses'] == [{'account': 'account-id', 'secret_hash': 'b' * 64, 'timestep': 123}]
    assert bundle.rows['trusted_devices'] == [] and bundle.skipped['trusted_devices'] == 1
    assert bundle.rows['oidc_states'] == [] and bundle.skipped['oidc_states'] == 1
    assert bundle.rows['oidc_links'][0]['subject'] == 'test-subject'
    assert before == {str(path):path.read_bytes() for path in source.rglob('*') if path.is_file()}


def test_preparation_captures_frozen_wal_without_changing_database_or_shm(source):
    database = source / 'logs/analytics.db'
    with closing(sqlite3.connect(database)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO events VALUES (8,'2026-09-26T00:00:00Z','ALPHA','web','chat-id','msg_out','{}')")
        writer.commit()
        before = {str(path): path.read_bytes() for path in source.rglob('*') if path.is_file()}
        bundle = prepare(source)
        assert bundle.counts()['events'] == 2
        assert before == {str(path): path.read_bytes() for path in source.rglob('*') if path.is_file()}


def test_preparation_stops_if_sqlite_source_changes_during_staging(source, monkeypatch):
    original_copy = preparation.shutil.copyfileobj
    changed = False
    def change_after_copy(incoming, outgoing, length):
        nonlocal changed
        original_copy(incoming, outgoing, length)
        if not changed:
            with (source / 'logs/security.db').open('ab') as handle:
                handle.write(b'changed-source')
            changed = True
    monkeypatch.setattr(preparation.shutil, 'copyfileobj', change_after_copy)
    with pytest.raises(ValueError, match='source changed'):
        prepare(source)


@pytest.fixture
def mixed_source(source):
    (source / 'business/ALPHA').rename(source / 'business/Alpha')
    version = source / 'business/versions/2026-09-26'
    (version / 'ALPHA').rename(version / 'Alpha')
    marker = version / 'Alpha/_snapshot.json'
    payload = json.loads(marker.read_text())
    payload.update(tenant='Alpha', source='business/Alpha')
    marker.write_text(json.dumps(payload))
    with closing(sqlite3.connect(source / 'logs/security.db')) as db, db:
        db.execute("UPDATE managed_businesses SET tenant='Alpha' WHERE tenant='ALPHA'")
        db.execute("UPDATE billing_discounts SET tenant='Alpha' WHERE tenant='ALPHA'")
    with closing(sqlite3.connect(source / 'logs/analytics.db')) as db, db:
        db.execute('CREATE TABLE api_usage (id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, tenant TEXT NOT NULL, channel TEXT NOT NULL, purpose TEXT NOT NULL, requested_model TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL, cost_nano_usd INTEGER, price_version TEXT NOT NULL)')
        db.execute("INSERT INTO api_usage VALUES (2,'2026-09-26T00:00:00Z','ALPHA','web','chat','test-model','test-model','ok',200000,'test-price')")
    (source / 'logs/crm_snapshot.json').write_text(json.dumps([
        {'id': 'example-lead', 'tenant': 'ALPHA', 'conversations': [{'text': 'Preserved conversation'}]},
    ]))
    return source


def test_unique_casefold_reconciliation_preserves_rows_and_source_hashes(mixed_source):
    before = {str(path): path.read_bytes() for path in mixed_source.rglob('*') if path.is_file()}
    bundle = prepare(mixed_source)
    assert bundle.rows['events'][0]['tenant'] == 'Alpha'
    assert bundle.rows['api_usage'][0]['tenant'] == 'Alpha'
    assert bundle.rows['api_usage'][0]['cost_nano_usd'] == 200000
    assert bundle.rows['crm_records'][0]['tenant'] == 'Alpha'
    assert bundle.rows['crm_records'][0]['payload']['tenant'] == 'Alpha'
    assert bundle.rows['crm_records'][0]['payload']['conversations'] == [{'text': 'Preserved conversation'}]
    assert bundle.reconciled == {'events': 1, 'api_usage': 1, 'crm_records': 1}
    assert before == {str(path): path.read_bytes() for path in mixed_source.rglob('*') if path.is_file()}


@pytest.mark.parametrize('table', ['events', 'api_usage', 'crm_records'])
def test_orphan_analytics_or_crm_tenant_references_stop_preparation(mixed_source, table):
    if table == 'crm_records':
        path = mixed_source / 'logs/crm_snapshot.json'
        rows = json.loads(path.read_text())
        rows[0]['tenant'] = 'MISSING'
        path.write_text(json.dumps(rows))
    else:
        with closing(sqlite3.connect(mixed_source / 'logs/analytics.db')) as db, db:
            db.execute('UPDATE '+table+" SET tenant='MISSING'")
    with pytest.raises(ValueError, match='no source business'):
        prepare(mixed_source)


def test_ambiguous_casefold_business_directories_stop_reconciliation(source):
    try:
        (source / 'business/Alpha').mkdir()
    except FileExistsError:
        pytest.skip('Filesystem cannot contain business directories differing only by case')
    with pytest.raises(ValueError, match='Case-ambiguous'):
        prepare(source)


def test_missing_security_db_fails_instead_of_losing_activation(source):
    (source / 'logs/security.db').unlink()
    with pytest.raises(ValueError, match='Required SQLite'):
        prepare(source)


def test_unknown_source_tables_fail_closed(source):
    with closing(sqlite3.connect(source / 'logs/security.db')) as db, db:
        db.execute('CREATE TABLE future_accounts (id TEXT)')
    with pytest.raises(ValueError, match='Unknown SQLite'):
        prepare(source)


def test_ambiguous_tenants_rejected(source):
    with closing(sqlite3.connect(source / 'logs/security.db')) as db, db:
        db.execute("INSERT INTO managed_businesses VALUES ('MISSING','owner')")
    with pytest.raises(ValueError, match='no source documents'):
        prepare(source)


@pytest.mark.parametrize('content', ['{"a":1,"a":2}', '{"a":NaN}', '{"a":1e309}', '{"a":-1e309}'])
def test_json_that_would_change_during_import_rejected(source, content):
    (source / 'business/ALPHA/catalog.json').write_text(content)
    with pytest.raises(ValueError):
        prepare(source)


def test_canonical_export_registry_is_preserved_without_repeating_accounts_argument(source):
    registry = {'users': [{
        'email': 'operator@example.invalid', 'password_hash': 'preserved-operator-hash',
        'totp_secret': 'preserved-operator-authenticator', 'role': 'platform_admin',
    }]}
    (source / 'accounts.json').write_text(json.dumps(registry))
    bundle = prepare(source)
    assert bundle.rows['operator_accounts'] == [{
        'email': 'operator@example.invalid', 'payload': registry['users'][0],
    }]


def test_linked_source_root_is_rejected_before_resolving_or_opening_database(source, monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path == source or original(path))
    with pytest.raises(ValueError, match='Linked source'):
        prepare(source)


@pytest.mark.parametrize('change', [
    {'tenant': 'BETA'}, {'created_at': '2026-09-26'},
    {'created_at': '2026-09-26T00:00:00'}, {'created_at': 'invalid'},
    {'created_at': '2026-09-26T01:00:00+01:00'}, {'source': ''},
    {'source': None}, {'unexpected': 'private-source-record'},
])
def test_generated_snapshot_metadata_must_match_runtime_shape(source, change):
    marker = source / 'business/versions/2026-09-26/ALPHA/_snapshot.json'
    payload = json.loads(marker.read_text())
    payload.update(change)
    marker.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='Unexpected snapshot metadata'):
        prepare(source)


def test_snapshot_exception_does_not_allow_arbitrary_underscore_documents(source):
    (source / 'business/versions/2026-09-26/ALPHA/_private.json').write_text('{}')
    with pytest.raises(ValueError, match='Unexpected version file'):
        prepare(source)


def test_tls_cannot_be_downgraded(monkeypatch):
    psycopg = pytest.importorskip('psycopg')
    received = {}
    monkeypatch.setenv('V7_SUPABASE_MIGRATION_DSN','postgresql://example.invalid/database?sslmode=disable')
    monkeypatch.setenv('V7_SUPABASE_CA_FILE','test-ca.crt')
    monkeypatch.setattr(psycopg,'connect',lambda *args,**kwargs: received.update(kwargs))
    connection()
    assert received['sslmode'] == 'verify-full'
    assert received['sslrootcert'] == 'test-ca.crt'


@pytest.fixture
def pg():
    """Only a disposable, empty database explicitly supplied for this test."""
    dsn = os.getenv('V7_TEST_POSTGRES_DSN')
    if not dsn:
        pytest.skip('Set V7_TEST_POSTGRES_DSN to a disposable PostgreSQL database')
    psycopg = pytest.importorskip('psycopg')
    from psycopg.conninfo import conninfo_to_dict
    details = conninfo_to_dict(dsn)
    if (details.get('host') not in {'localhost', '127.0.0.1'}
            or details.get('hostaddr') not in {None, '127.0.0.1', '::1'}
            or details.get('service')
            or not details.get('dbname', '').startswith('v7_disposable_')):
        pytest.fail('Migration tests require a named local disposable database')
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5, options='-c statement_timeout=10000') as conn:
        if conn.execute("SELECT to_regnamespace('v7_private')").fetchone()[0]:
            pytest.fail('Integration test requires an empty disposable database; existing schema will not be deleted')
        for role in ['anon','authenticated','service_role']:
            if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
                conn.execute('CREATE ROLE '+role+' NOLOGIN')
        for migration in sorted((Path(__file__).resolve().parents[1] / 'supabase/migrations').glob('*.sql')):
            conn.execute(migration.read_text(encoding='utf-8-sig'), prepare=False)
        yield conn


def test_postgres_copy_verification_and_row_security(pg, mixed_source, monkeypatch):
    psycopg = pytest.importorskip('psycopg')
    bundle = prepare(mixed_source)
    def failed_verification(conn, imported):
        raise ValueError('Injected verification failure after inserts')
    with monkeypatch.context() as patch:
        patch.setattr('scripts.prepare_supabase.verify', failed_verification)
        with pytest.raises(ValueError, match='Injected verification failure'):
            import_bundle(pg,bundle)
    assert pg.execute('SELECT count(*) FROM v7_private.tenants').fetchone()[0] == 0
    import_bundle(pg,bundle)
    verify(pg,bundle)
    assert pg.execute("SELECT payload FROM v7_private.document_versions WHERE filename='_snapshot.json'").fetchone()[0] == {
        'tenant': 'Alpha', 'created_at': '2026-09-26T00:00:00Z', 'source': 'business/Alpha',
    }
    assert pg.execute('SELECT id FROM v7_private.events').fetchone()[0] == 7
    assert pg.execute("SELECT nextval('v7_private.events_id_seq')").fetchone()[0] == 8
    with pytest.raises(ValueError, match='must be empty'):
        import_bundle(pg,bundle)
    verify(pg,bundle)
    for role in ['anon','authenticated','service_role']:
        assert pg.execute("SELECT has_schema_privilege(%s,'v7_private','USAGE')",(role,)).fetchone()[0] is False
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with pg.transaction():
                pg.execute('SET LOCAL ROLE '+role)
                pg.execute('SELECT * FROM v7_private.business_documents')
    with pg.transaction():
        pg.execute('SET LOCAL ROLE v7_backend')
        assert pg.execute('SELECT count(*) FROM v7_private.business_documents').fetchone()[0] == 0
        assert pg.execute('SELECT count(*) FROM v7_private.billing_discounts').fetchone()[0] == 0
        pg.execute("SELECT set_config('v7.tenant','Alpha',true)")
        assert {row[0] for row in pg.execute('SELECT tenant FROM v7_private.business_documents')} == {'Alpha'}
        assert {row[0] for row in pg.execute('SELECT tenant FROM v7_private.billing_discounts')} == {'Alpha'}
        assert {row[0] for row in pg.execute('SELECT tenant FROM v7_private.events')} == {'Alpha'}
        assert pg.execute('SELECT sum(cost_nano_usd) FROM v7_private.api_usage').fetchone()[0] == 200000
        assert pg.execute('SELECT tenant, payload FROM v7_private.crm_records').fetchone() == (
            'Alpha', {'id': 'example-lead', 'tenant': 'Alpha', 'conversations': [{'text': 'Preserved conversation'}]},
        )
        assert pg.execute("UPDATE v7_private.business_documents SET payload='{}' WHERE tenant='BETA'").rowcount == 0
        assert pg.execute('SELECT count(*) FROM v7_private.account_authenticators').fetchone()[0] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with pg.transaction():
            pg.execute('SET LOCAL ROLE v7_backend')
            pg.execute("SELECT set_config('v7.tenant','Alpha',true)")
            pg.execute("INSERT INTO v7_private.business_documents VALUES ('BETA','leak.json','{}')")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with pg.transaction():
            pg.execute('SET LOCAL ROLE v7_backend')
            pg.execute('DELETE FROM v7_private.audit_records')
    verify(pg,bundle)
