"""Recovery must never act as a tenant, role or authenticator bypass."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from service import account_passwords, registration_mail, session_store
from service.account_service import AccountService
from service.security import generate_totp_token, hash_password, verify_password

OLD = 'Original-password-123!'
NEW = 'Replacement-password-456!'
EMAIL = 'owner@example.test'


@pytest.fixture
def account(app, monkeypatch):
    with app.app_context():
        record = AccountService(app.container.storage).create_account('EXAMPLE', {
            'email': EMAIL, 'password': OLD, 'roles': ['business_owner']})
    messages = []
    monkeypatch.setattr(registration_mail, 'configured', lambda: True)
    monkeypatch.setattr(registration_mail, 'send_reset_code', lambda email, code: messages.append((email, code)))
    return record, messages


def begin(client, email=EMAIL, tenant='EXAMPLE'):
    return client.post('/auth/password/reset', json={'email': email, 'tenant': tenant})


def complete(client, code, ip='127.0.0.1'):
    return client.post('/auth/password/reset/confirm', json={'code': code, 'password': NEW}, environ_overrides={'REMOTE_ADDR': ip})


def login(client, password=OLD):
    result = client.post('/auth/login', json={'email': EMAIL, 'tenant': 'EXAMPLE', 'password': password})
    assert result.status_code == 202
    return client.post('/auth/mfa/confirm', json={'code': generate_totp_token(result.json['mfa']['setup_key']), 'remember_device': True})


def test_recovery_changes_only_password_and_invalidates_sessions(client, app, account):
    assert login(client).status_code == 200
    other = app.test_client()
    assert begin(other).status_code == 202
    with app.app_context():
        before = AccountService(app.container.storage).get_account('EXAMPLE', account[0]['id'])
    assert complete(other, account[1][0][1]).status_code == 200
    assert complete(other, account[1][0][1]).status_code == 400
    assert client.get('/auth/account').status_code == 401
    assert client.post('/auth/login', json={'email': EMAIL, 'tenant': 'EXAMPLE', 'password': OLD}, environ_overrides={'REMOTE_ADDR': '192.0.2.10'}).status_code == 401
    signed = other.post('/auth/login', json={'email': EMAIL, 'tenant': 'EXAMPLE', 'password': NEW}, environ_overrides={'REMOTE_ADDR': '192.0.2.11'})
    assert signed.status_code == 202 and signed.json['mfa']['enrollment'] is False
    with app.app_context():
        after = AccountService(app.container.storage).get_account('EXAMPLE', account[0]['id'])
        assert verify_password(NEW, after['password_hash'])
        for field in ('id', 'email', 'roles', 'permissions', 'active'):
            assert after[field] == before[field]
        with session_store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM trusted_devices').fetchone()[0] == 0


def test_recovery_cannot_cross_tenant_or_reveal_missing_accounts(client, app, account):
    with app.app_context():
        app.container.storage.tenant_dir('OTHER').mkdir(parents=True, exist_ok=True)
    wrong = begin(client, tenant='OTHER')
    unknown = begin(app.test_client(), email='missing@example.test')
    assert wrong.status_code == unknown.status_code == 202
    assert wrong.json == unknown.json == {'message': account_passwords.GENERIC_NOTICE}
    assert account[1] == []
    assert complete(client, '123456').status_code == 400


def test_code_is_bound_to_requesting_browser_and_attempts_are_bounded(client, app, account):
    assert begin(client).status_code == 202
    code = account[1][0][1]
    assert complete(app.test_client(), code).status_code == 400
    wrong = '000000' if code != '000000' else '999999'
    for number in range(5):
        assert complete(client, wrong, ip=f'192.0.2.{number+1}').status_code == 400
    assert complete(client, code, ip='192.0.2.99').status_code == 400


def test_expired_and_stale_credential_codes_are_rejected(client, app, account):
    assert begin(client).status_code == 202
    with client.session_transaction() as sess:
        request_id = sess['password_reset_request']
    with app.app_context(), session_store.connection() as db:
        db.execute('UPDATE registration_requests SET expires=? WHERE id=?', (time.time()-1, request_id))
    assert complete(client, account[1][0][1]).status_code == 400


def test_admin_password_change_invalidates_recovery(client, app, account):
    assert begin(client).status_code == 202
    with app.app_context():
        AccountService(app.container.storage).update_account('EXAMPLE', account[0]['id'], {'password': 'Administrator-changed-789!'})
    assert complete(client, account[1][0][1]).status_code == 400


def test_self_change_requires_current_password_and_ignores_client_identity(client, app, account):
    assert client.post('/auth/password/change', json={'current_password': OLD, 'password': NEW}).status_code == 401
    assert login(client).status_code == 200
    details = client.get('/auth/account').json
    assert details['password_change_available'] and 'password_hash' not in details
    assert client.post('/auth/password/change', json={'current_password': 'wrong', 'password': NEW}).status_code == 400
    assert client.post('/auth/password/change', json={'current_password': OLD, 'password': NEW,
        'tenant': 'OTHER', 'email': 'victim@example.test', 'roles': ['platform_admin']}).status_code == 200
    assert client.get('/auth/account').status_code == 401
    with app.app_context():
        changed = AccountService(app.container.storage).get_account('EXAMPLE', account[0]['id'])
        assert changed['roles'] == ['business_owner'] and verify_password(NEW, changed['password_hash'])


def test_recovery_cooldown_and_delivery_errors_do_not_leak_details(client, app, account, monkeypatch):
    monkeypatch.setattr(registration_mail, 'send_reset_code', lambda *args: (_ for _ in ()).throw(RuntimeError('secret-provider-data')))
    result = begin(client)
    assert result.status_code == 202 and result.json == {'message': account_passwords.GENERIC_NOTICE}
    assert 'secret-provider-data' not in result.get_data(as_text=True)
    assert begin(app.test_client()).status_code == 400


def test_platform_registry_password_can_be_changed(client, app, monkeypatch):
    path = Path(os.environ['ADMIN_USERS_FILE'])
    path.write_text(json.dumps({'users': [{'email': EMAIL, 'password_hash': hash_password(OLD), 'role': 'platform_admin'}]}))
    assert login(client).status_code == 200
    assert client.post('/auth/password/change', json={'current_password': OLD, 'password': NEW}).status_code == 200
    row = json.loads(path.read_text())['users'][0]
    assert row['role'] == 'platform_admin' and verify_password(NEW, row['password_hash'])
    assert 'password' not in row
    with app.app_context(), session_store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM trusted_devices').fetchone()[0] == 0


def test_simultaneous_reset_consumes_code_only_once(app, account):
    client = app.test_client()
    assert begin(client).status_code == 202
    with client.session_transaction() as sess:
        request_id = sess['password_reset_request']
    def spend():
        with app.test_request_context('/'):
            from flask import session
            session['password_reset_request'] = request_id
            try:
                account_passwords.confirm({'code': account[1][0][1], 'password': NEW})
                return True
            except ValueError:
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: spend(), range(2))) == [False, True]


def test_reset_and_change_require_csrf(client, account):
    assert client.post('/auth/password/reset', json={'email': EMAIL, 'tenant': 'EXAMPLE'}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert login(client).status_code == 200
    assert client.post('/auth/password/change', json={'current_password': OLD, 'password': NEW}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
