"""Native runtime fixtures restricted to explicitly named local disposable databases."""
import os
import secrets
from pathlib import Path

import pytest


@pytest.fixture(scope='session')
def native_database():
    dsn = os.getenv('V7_TEST_POSTGRES_DSN')
    if not dsn:
        pytest.skip('Set V7_TEST_POSTGRES_DSN to a local disposable PostgreSQL database')
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    details = conninfo_to_dict(dsn)
    if (details.get('host') not in {'localhost', '127.0.0.1'}
            or details.get('hostaddr', '') not in {'', '127.0.0.1', '::1'}
            or details.get('service')
            or not details.get('dbname', '').startswith('v7_disposable_')):
        pytest.fail('Native runtime tests require a named local disposable database')
    with psycopg.connect(dsn, autocommit=True) as admin:
        if admin.execute("SELECT to_regnamespace('v7_private')").fetchone()[0]:
            pytest.fail('Existing private schema will not be overwritten; supply a fresh disposable database')
        for name in ['anon', 'authenticated', 'service_role']:
            if not admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (name,)).fetchone():
                admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(name)))
        for path in sorted((Path(__file__).resolve().parents[1]/'supabase/migrations').glob('*.sql')):
            admin.execute(path.read_text(encoding='utf-8-sig'), prepare=False)
        name = 'v7_runtime_test_'+secrets.token_hex(5)
        password = secrets.token_urlsafe(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB '
                              'NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(
                                  sql.Identifier(name), sql.Literal(password)))
        admin.execute(sql.SQL('GRANT v7_backend TO {}').format(sql.Identifier(name)))
        runtime_dsn = make_conninfo(dsn, user=name, password=password)
        yield {'admin':admin, 'dsn':runtime_dsn, 'role':name,
               'ca_file':details.get('sslrootcert')}


@pytest.fixture
def pg_runtime(native_database, monkeypatch, tmp_path):
    """Each case receives two distinct legacy-active tenant records."""
    from psycopg.types.json import Jsonb
    from service.tenant_service import TenantService
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'postgres')
    monkeypatch.setenv('V7_POSTGRES_DSN', native_database['dsn'])
    if native_database['ca_file']:
        monkeypatch.setenv('V7_SUPABASE_CA_FILE', native_database['ca_file'])
    monkeypatch.delenv('ADMIN_USERS_FILE', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('V7_DATA_DIR', str(tmp_path))
    monkeypatch.chdir(tmp_path)
    suffix = secrets.token_hex(5).upper()
    tenants = ['PG_'+suffix+'_A', 'PG_'+suffix+'_B']
    admin = native_database['admin']
    for tenant in tenants:
        admin.execute('INSERT INTO v7_private.tenants(tenant) VALUES(%s)', (tenant,))
        documents = TenantService._starter_documents('Test '+tenant)
        for filename, payload in documents.items():
            admin.execute('INSERT INTO v7_private.business_documents(tenant,filename,payload) '
                          'VALUES(%s,%s,%s)', (tenant, filename, Jsonb(payload)))
    monkeypatch.setenv('BUSINESS_KEY', tenants[0])
    return {**native_database, 'tenant':tenants[0], 'other':tenants[1], 'root':tmp_path}
