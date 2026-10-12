"""Email verification preserves the account's existing security identity."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from service import account_email, account_mfa, registration_mail, session_store, tenant_access
from service.account_service import AccountService
from service.security import generate_totp_token, hash_password, verify_password
from tests.test_account_passwords import account, OLD, EMAIL, login  # noqa: F401

NEW_EMAIL = 'changed@example.test'


@pytest.fixture
def change_mail(monkeypatch):
    sent = []
    monkeypatch.setattr(registration_mail, 'send_email_change_code', lambda email, code: sent.append((email, code)))
    return sent


def start(client, email=NEW_EMAIL, password=OLD):
    return client.post('/auth/account/email', json={'email': email, 'current_password': password})


def confirm(client, code, ip='127.0.0.1'):
    return client.post('/auth/account/email/confirm', json={'code':code}, environ_overrides={'REMOTE_ADDR':ip})


def test_email_change_preserves_password_mfa_ownership_and_provider_links(client, app, account, change_mail, monkeypatch):
    import tests.test_account_passwords as password_tests
    used_codes = []
    def capture(secret):
        code = generate_totp_token(secret)
        used_codes.append(code)
        return code
    monkeypatch.setattr(password_tests, 'generate_totp_token', capture)
    assert login(client).status_code == 200
    with client.session_transaction() as sess:
        before_user = dict(sess['user'])
    with app.app_context():
        before = AccountService(app.container.storage).get_account('EXAMPLE', account[0]['id'])
        secret = account_mfa.enrolled_secret(before_user)
        tenant_access.register('OTHER', before_user)
        from service import oidc_login
        with session_store.connection() as db:
            oidc_login._tables(db)
            db.execute('INSERT INTO oidc_links VALUES (?,?,?,?,?,?,?)', ('google','synthetic-client','https://accounts.google.com','synthetic-subject',account_mfa.account_key(before_user),json.dumps(oidc_login._reference(before_user)),time.time()))
    assert start(client).status_code == 202
    with app.app_context():
        assert AccountService(app.container.storage).get_account('EXAMPLE', account[0]['id'])['email'] == EMAIL
    assert confirm(client, change_mail[0][1]).status_code == 200
    assert client.get('/auth/account').status_code == 401
    result = client.post('/auth/login', json={'email':NEW_EMAIL,'password':OLD,'tenant':'EXAMPLE'}, environ_overrides={'REMOTE_ADDR':'192.0.2.10'})
    assert result.status_code == 202 and result.json['mfa']['enrollment'] is False
    # The same authenticator step must stay spent across the email change.
    assert client.post('/auth/mfa/confirm', json={'code':used_codes[-1]}, environ_overrides={'REMOTE_ADDR':'192.0.2.11'}).status_code == 401
    new_user = {**before_user, 'email':NEW_EMAIL}
    with app.app_context():
        after = AccountService(app.container.storage).get_account('EXAMPLE', account[0]['id'])
        assert after['password_hash'] == before['password_hash'] and verify_password(OLD, after['password_hash'])
        assert after['roles'] == before['roles'] and after['permissions'] == before['permissions']
        assert account_mfa.enrolled_secret(new_user) == secret
        assert 'OTHER' in tenant_access.owned_tenants(new_user)
        with session_store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM trusted_devices').fetchone()[0] == 0
            linked = db.execute('SELECT account,identity FROM oidc_links').fetchone()
            assert linked[0] == account_mfa.account_key(new_user) and json.loads(linked[1])['email'] == NEW_EMAIL


def test_email_change_requires_authentication_current_password_and_csrf(client, account, change_mail):
    assert start(client).status_code == 401
    assert login(client).status_code == 200
    assert start(client, password='wrong').status_code == 400
    assert client.post('/auth/account/email', json={'email':NEW_EMAIL,'current_password':OLD}, headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert change_mail == []


def test_wrong_email_code_attempts_are_bounded(client, account, change_mail):
    assert login(client).status_code == 200
    assert start(client).status_code == 202
    code = change_mail[0][1]
    wrong = '000000' if code != '000000' else '999999'
    for number in range(5):
        assert confirm(client, wrong, f'192.0.2.{number+1}').status_code == 400
    assert confirm(client, code, '192.0.2.99').status_code == 400


def test_duplicate_email_is_rechecked_at_confirmation(client, app, account, change_mail):
    assert login(client).status_code == 200
    assert start(client).status_code == 202
    with app.app_context():
        AccountService(app.container.storage).create_account('EXAMPLE', {'email':NEW_EMAIL,'password':OLD,'roles':['business_staff']})
    assert confirm(client, change_mail[0][1]).status_code == 400
    assert client.get('/auth/account').json['email'] == EMAIL


def test_platform_registry_email_change_preserves_admin_and_authenticator(client, app, account, change_mail):
    path = Path(os.environ['ADMIN_USERS_FILE'])
    path.write_text(json.dumps({'users':[{'email':EMAIL,'password_hash':hash_password(OLD),'role':'platform_admin'}]}))
    assert login(client).status_code == 200
    with client.session_transaction() as sess:
        original = dict(sess['user'])
    with app.app_context():
        secret = account_mfa.enrolled_secret(original)
    assert start(client).status_code == 202
    assert confirm(client, change_mail[0][1]).status_code == 200
    row = json.loads(path.read_text())['users'][0]
    assert row['role'] == 'platform_admin' and row['email'] == NEW_EMAIL and verify_password(OLD,row['password_hash'])
    with app.app_context():
        assert account_mfa.enrolled_secret({**original,'id':NEW_EMAIL,'email':NEW_EMAIL}) == secret


def test_code_is_browser_and_account_bound(client, app, account, change_mail):
    assert login(client).status_code == 200
    assert start(client).status_code == 202
    assert confirm(app.test_client(), change_mail[0][1]).status_code == 401
    with client.session_transaction() as sess:
        request_id = sess['email_change_request']
    with app.app_context(), session_store.connection() as db:
        db.execute('UPDATE registration_requests SET expires=? WHERE id=?', (time.time()-1,request_id))
    assert confirm(client, change_mail[0][1]).status_code == 400


def test_delivery_failure_does_not_change_the_account(client, account, change_mail, monkeypatch):
    assert login(client).status_code == 200
    def fail(*args):
        raise RuntimeError('private-provider-detail')
    monkeypatch.setattr(registration_mail,'send_email_change_code',fail)
    response = start(client)
    assert response.status_code == 400 and 'private-provider-detail' not in response.get_data(as_text=True)
    assert client.get('/auth/account').json['email'] == EMAIL


def test_directory_case_authenticator_is_preserved(client, app, account, change_mail):
    assert login(client).status_code == 200
    with client.session_transaction() as sess:
        original = dict(sess['user'])
    with app.app_context():
        key = account_mfa.account_key(original)
        alias = account_mfa.account_key({**original,'tenant':'example'})
        secret = account_mfa.enrolled_secret(original)
        with session_store.connection() as db:
            db.execute('UPDATE account_authenticators SET account=? WHERE account=?', (alias,key))
    assert start(client).status_code == 202
    assert confirm(client, change_mail[0][1]).status_code == 200
    with app.app_context():
        assert account_mfa.enrolled_secret({**original,'email':NEW_EMAIL}) == secret


def test_registry_email_cannot_shadow_another_tenant(client, app, account, change_mail):
    path = Path(os.environ['ADMIN_USERS_FILE'])
    path.write_text(json.dumps({'users':[{'email':EMAIL,'password_hash':hash_password(OLD),'role':'platform_admin'}]}))
    with app.app_context():
        app.container.storage.tenant_dir('OTHER').mkdir(parents=True,exist_ok=True)
        AccountService(app.container.storage).create_account('OTHER', {'email':NEW_EMAIL,'password':OLD,'roles':['business_owner']})
    assert login(client).status_code == 200
    assert start(client).status_code == 400
    assert change_mail == []


def test_simultaneous_confirmation_is_single_use(client, app, account, change_mail):
    assert login(client).status_code == 200
    assert start(client).status_code == 202
    with client.session_transaction() as sess:
        request_id, user = sess['email_change_request'], dict(sess['user'])
    def spend(_):
        with app.test_request_context('/'):
            from flask import session
            session['email_change_request'] = request_id
            try:
                account_email.confirm(user, {'code':change_mail[0][1]})
                return True
            except ValueError:
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(spend, range(2))) == [False, True]
