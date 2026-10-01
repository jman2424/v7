"""Tenant creation preserves existing business identities on every filesystem."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

import pytest

from service import session_store, tenant_access
from service.account_service import AccountService
from service.security import generate_totp_secret, generate_totp_token
from service.tenant_service import TenantService
from tests.test_business_access import owner
from werkzeug.security import generate_password_hash


def test_owner_cannot_create_case_variant_of_existing_business(client, monkeypatch):
    storage = client.application.container.storage
    original = storage.read_json('EXAMPLE', 'catalog.json')
    exists = Path.exists

    def case_sensitive_exists(path):
        # Exercise Linux's case-sensitive existence check on Windows as well.
        if path.parent == storage.business_root:
            return any(entry.name == path.name for entry in path.parent.iterdir())
        return exists(path)

    monkeypatch.setattr(Path, 'exists', case_sensitive_exists)
    owner(client)
    response = client.post('/admin/api/tenants', json={'key': 'example', 'name': 'Different company'})
    assert response.status_code == 400
    assert response.json['error'] == 'tenant_exists'
    assert storage.read_json('EXAMPLE', 'catalog.json') == original
    assert storage.tenant_keys() == ['EXAMPLE']
    with session_store.connection() as db:
        tenant_access._schema(db)
        assert db.execute('SELECT COUNT(*) FROM managed_businesses').fetchone()[0] == 0


def test_concurrent_case_variants_reserve_only_one_workspace(client, monkeypatch):
    storage = client.application.container.storage
    barrier = Barrier(2)
    write_starter_files = TenantService._write_starter_files

    def write_together(service, target, name):
        write_starter_files(service, target, name)
        # Both callers passed the directory precheck before either reserves it.
        barrier.wait(timeout=10)

    monkeypatch.setattr(TenantService, '_write_starter_files', write_together)

    def create(key):
        try:
            TenantService(storage).create_tenant(key, key + ' company')
            return key
        except ValueError as error:
            assert str(error) == 'tenant_exists'
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ['NEWCO', 'newco']))
    winner = next(key for key in results if key is not None)
    assert results.count(None) == 1
    assert storage.tenant_exists(winner)
    assert storage.tenant_keys() == sorted(['EXAMPLE', winner], key=str.casefold)
    assert not list(storage.business_root.glob('.tenant-*'))
    with session_store.connection() as db:
        assert db.execute('SELECT tenant FROM managed_businesses').fetchall() == [(winner,)]


@pytest.mark.parametrize('key', ['NEWCO', 'newco'])
def test_creation_rejects_an_existing_casefold_reservation(client, key):
    tenant_access.register('NewCo')
    with pytest.raises(ValueError, match='^tenant_exists$'):
        TenantService(client.application.container.storage).create_tenant(key, 'Another company')
    with session_store.connection() as db:
        assert db.execute('SELECT tenant FROM managed_businesses').fetchall() == [('NewCo',)]
    assert client.application.container.storage.tenant_keys() == ['EXAMPLE']


def test_canonical_key_uses_existing_sqlite_spelling_and_exact_postgres_keys(client, monkeypatch):
    storage = client.application.container.storage
    assert storage.canonical_tenant_key('example') == 'EXAMPLE'
    assert storage.canonical_tenant_key('MissingCo') == 'MissingCo'
    assert client.application.container.for_tenant('example') is client.application.container
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'postgres')
    assert storage.canonical_tenant_key('example') == 'example'
    assert storage.canonical_tenant_key('Example') == 'Example'


def test_canonical_key_rejects_ambiguous_sqlite_directories(client, monkeypatch):
    storage = client.application.container.storage
    entries = Path.iterdir
    is_dir = Path.is_dir

    def ambiguous_entries(path):
        if path == storage.business_root:
            return iter([path / 'EXAMPLE', path / 'example'])
        return entries(path)

    def ambiguous_directory(path):
        if path.parent == storage.business_root and path.name.casefold() == 'example':
            return True
        return is_dir(path)

    monkeypatch.setattr(Path, 'iterdir', ambiguous_entries)
    monkeypatch.setattr(Path, 'is_dir', ambiguous_directory)
    with pytest.raises(ValueError, match='^ambiguous_tenant$'):
        storage.canonical_tenant_key('example')


def test_case_alias_login_retains_the_managed_business_activation_boundary(client):
    storage = client.application.container.storage
    password = 'Isolated-owner-password-42!'
    TenantService(storage).create_tenant('NEWCO', 'New company', initial_account={
        'id': 'case-owner', 'email': 'case-owner@example.test',
        'password_hash': generate_password_hash(password),
        'roles': ['business_owner'], 'active': True, 'permissions': [],
    })
    response = client.post('/auth/login', json={
        'tenant': 'newco', 'email': 'case-owner@example.test', 'password': password,
    })
    if response.status_code == 404:
        # Case-sensitive filesystems may reject an alias rather than resolve it.
        return
    assert response.status_code == 202
    confirmed = client.post('/auth/mfa/confirm', json={
        'code': generate_totp_token(response.json['mfa']['setup_key']),
    })
    assert confirmed.status_code == 200
    assert confirmed.json['user']['tenant'] == 'NEWCO'
    assert client.get('/admin/api/activation').json['active'] is False
    assert client.put('/admin/api/profile', json={'name': 'Changed company'}).status_code == 403


@pytest.mark.parametrize('path', ['/chat_ui', '/widget.js', '/chat/actions'])
def test_case_alias_cannot_enable_an_inactive_public_business(client, path):
    TenantService(client.application.container.storage).create_tenant('NEWCO', 'New company')
    assert client.get(path + '?tenant=NEWCO').status_code == 403
    assert client.get(path + '?tenant=newco').status_code in {403, 404}


def test_case_alias_cannot_replace_an_existing_authenticator(client):
    password = 'Isolated-mfa-password-42!'
    AccountService(client.application.container.storage).create_account('EXAMPLE', {
        'email': 'alias-mfa@example.test', 'password': password, 'roles': ['business_owner'],
    })
    credentials = {'email': 'alias-mfa@example.test', 'password': password, 'tenant': 'EXAMPLE'}
    setup = client.post('/auth/login', json=credentials)
    assert setup.status_code == 202 and setup.json['mfa']['enrollment']
    assert client.post('/auth/mfa/confirm', json={
        'code': generate_totp_token(setup.json['mfa']['setup_key']),
    }).status_code == 200
    assert client.post('/auth/logout').status_code == 200
    alias = client.post('/auth/login', json={**credentials, 'tenant': 'example'})
    if alias.status_code == 404:
        return
    assert alias.status_code == 202
    assert alias.json['mfa']['enrollment'] is False
    assert 'setup_key' not in alias.json['mfa']


def test_legacy_alias_authenticator_is_not_treated_as_missing(client):
    from service import account_mfa

    password = 'Isolated-legacy-mfa-password-42!'
    account = AccountService(client.application.container.storage).create_account('EXAMPLE', {
        'email': 'legacy-alias@example.test', 'password': password, 'roles': ['business_owner'],
    })
    # Preserve a protected authenticator recorded under the old alias identity.
    legacy_key = json.dumps([account['id'], account['email'], 'example'], separators=(',', ':'))
    secret = generate_totp_secret()
    with session_store.connection() as db:
        account_mfa._tables(db)
        db.execute('INSERT INTO account_authenticators VALUES (?,?)', (legacy_key, secret))
    response = client.post('/auth/login', json={
        'email': account['email'], 'password': password, 'tenant': 'EXAMPLE',
    })
    assert response.status_code == 202
    assert response.json['mfa']['enrollment'] is False
    assert 'setup_key' not in response.json['mfa']
    confirmed = client.post('/auth/mfa/confirm', json={'code': generate_totp_token(secret)})
    assert confirmed.status_code == 200
    assert confirmed.json['user']['tenant'] == 'EXAMPLE'
    with session_store.connection() as db:
        assert db.execute('SELECT account,secret FROM account_authenticators').fetchall() == [(legacy_key, secret)]


def test_conflicting_legacy_alias_authenticators_fail_closed(client):
    from service import account_mfa

    password = 'Isolated-conflicting-mfa-password-42!'
    account = AccountService(client.application.container.storage).create_account('EXAMPLE', {
        'email': 'conflicting-alias@example.test', 'password': password, 'roles': ['business_owner'],
    })
    entries = [(json.dumps([account['id'], account['email'], tenant], separators=(',', ':')),
                generate_totp_secret()) for tenant in ('example', 'Example')]
    with session_store.connection() as db:
        account_mfa._tables(db)
        db.executemany('INSERT INTO account_authenticators VALUES (?,?)', entries)
    response = client.post('/auth/login', json={
        'email': account['email'], 'password': password, 'tenant': 'EXAMPLE',
    })
    assert response.status_code in {401, 403, 409}
    assert 'setup_key' not in response.text
    assert client.get('/admin/api/catalog').status_code == 401
    with session_store.connection() as db:
        assert set(db.execute('SELECT account,secret FROM account_authenticators')) == set(entries)


def test_legacy_case_alias_ownership_remains_available_only_to_the_same_owner(client):
    from tests.conftest import set_test_identity

    user = {'id': 'legacy-owner', 'email': 'legacy-owner@example.test',
            'roles': ['business_owner'], 'tenant': 'EXAMPLE'}
    legacy = {**user, 'tenant': 'example'}
    storage = client.application.container.storage
    TenantService(storage).create_tenant('SHOP', 'Owned company', owner=legacy)
    with session_store.connection() as db:
        before = db.execute('SELECT tenant,owner FROM managed_businesses').fetchall()
    with client.session_transaction() as state:
        set_test_identity(client, state, user)
    assert client.get('/admin/api/catalog?tenant=SHOP').status_code == 200
    assert {row['key'] for row in client.get('/admin/api/tenants').json['tenants']} == {'EXAMPLE', 'SHOP'}
    with session_store.connection() as db:
        assert db.execute('SELECT tenant,owner FROM managed_businesses').fetchall() == before
    with client.session_transaction() as state:
        set_test_identity(client, state, {**user, 'id': 'other-owner', 'email': 'other@example.test'})
    assert client.get('/admin/api/catalog?tenant=SHOP').status_code == 403
