"""Offline migration safety checks and optional real PostgreSQL policy checks."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

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
    with closing(sqlite3.connect(logs / 'analytics.db')) as db, db:
        db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, tenant TEXT NOT NULL, channel TEXT NOT NULL, session_id TEXT NOT NULL, event_type TEXT NOT NULL, meta_json TEXT)')
        db.execute("INSERT INTO events VALUES (7,'2026-09-16T00:00:00Z','ALPHA','web','chat-id','msg_in','{}')")
    for tenant in ['ALPHA','BETA']:
        folder = tmp_path / 'business' / tenant
        folder.mkdir(parents=True)
        (folder / 'catalog.json').write_text(json.dumps({'products':[tenant]}))
        (folder / 'owner_accounts.json').write_text(json.dumps([{'id':tenant,'password_hash':'test-only-hash','roles':['business_owner']}]))
    (logs / 'selfrepair.log').write_text(json.dumps({'action':'test','target':'ALPHA'})+'\n')
    return tmp_path


def test_offline_inventory_preserves_sources_and_redacts_sessions(source):
    before = {str(path):path.read_bytes() for path in source.rglob('*') if path.is_file()}
    bundle = prepare(source)
    assert bundle.counts()['tenants'] == 2
    assert bundle.counts()['business_documents'] == 4
    assert bundle.rows['management_sessions'] == []
    assert bundle.skipped['management_sessions'] == 1
    assert bundle.rows['account_authenticators'][0]['secret'] == 'test-authenticator-secret'
    assert before == {str(path):path.read_bytes() for path in source.rglob('*') if path.is_file()}


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


@pytest.mark.parametrize('content', ['{"a":1,"a":2}', '{"a":NaN}'])
def test_json_that_would_change_during_import_rejected(source, content):
    (source / 'business/ALPHA/catalog.json').write_text(content)
    with pytest.raises(ValueError):
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
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5, options='-c statement_timeout=10000') as conn:
        if conn.execute("SELECT to_regnamespace('v7_private')").fetchone()[0]:
            pytest.fail('Integration test requires an empty disposable database; existing schema will not be deleted')
        for role in ['anon','authenticated','service_role']:
            if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
                conn.execute('CREATE ROLE '+role+' NOLOGIN')
        for migration in sorted((Path(__file__).resolve().parents[1] / 'supabase/migrations').glob('*.sql')):
            conn.execute(migration.read_text(encoding='utf-8-sig'), prepare=False)
        yield conn


def test_postgres_copy_verification_and_row_security(pg, source, monkeypatch):
    psycopg = pytest.importorskip('psycopg')
    bundle = prepare(source)
    def failed_verification(conn, imported):
        raise ValueError('Injected verification failure after inserts')
    with monkeypatch.context() as patch:
        patch.setattr('scripts.prepare_supabase.verify', failed_verification)
        with pytest.raises(ValueError, match='Injected verification failure'):
            import_bundle(pg,bundle)
    assert pg.execute('SELECT count(*) FROM v7_private.tenants').fetchone()[0] == 0
    import_bundle(pg,bundle)
    verify(pg,bundle)
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
        pg.execute("SELECT set_config('v7.tenant','ALPHA',true)")
        assert {row[0] for row in pg.execute('SELECT tenant FROM v7_private.business_documents')} == {'ALPHA'}
        assert {row[0] for row in pg.execute('SELECT tenant FROM v7_private.billing_discounts')} == {'ALPHA'}
        assert pg.execute("UPDATE v7_private.business_documents SET payload='{}' WHERE tenant='BETA'").rowcount == 0
        assert pg.execute('SELECT count(*) FROM v7_private.account_authenticators').fetchone()[0] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with pg.transaction():
            pg.execute('SET LOCAL ROLE v7_backend')
            pg.execute("SELECT set_config('v7.tenant','ALPHA',true)")
            pg.execute("INSERT INTO v7_private.business_documents VALUES ('BETA','leak.json','{}')")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with pg.transaction():
            pg.execute('SET LOCAL ROLE v7_backend')
            pg.execute('DELETE FROM v7_private.audit_records')
    verify(pg,bundle)
