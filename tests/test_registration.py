import pytest

from service import registration, registration_mail, session_store, tenant_access
from service.account_service import AccountService
from service.security import generate_totp_token, verify_password
from tests.test_business_access import owner


@pytest.fixture
def mailbox(monkeypatch):
    messages = {}
    monkeypatch.setattr(registration_mail, 'configured', lambda: True)
    monkeypatch.setattr(registration_mail, 'send_code', lambda email, code: messages.update({email: code}))
    return messages


def request_account(client, kind='owner', tenant='NEWCO'):
    return client.post('/auth/register', json={
        'email':'new@testing.test', 'password':'Signup-test-password-123',
        'kind':kind, 'tenant':tenant, 'business_name':'New company',
        'roles':['platform_admin'], 'active':True, 'permissions':['view_costs']})


def test_signup_disabled_without_mail(client, monkeypatch):
    monkeypatch.setattr(registration_mail, 'configured', lambda: False)
    assert client.get('/auth/registration').json['enabled'] is False
    assert request_account(client).status_code == 503
    assert not client.application.container.storage.tenant_dir('NEWCO').exists()


def test_verified_owner_requires_mfa_and_payment(client, mailbox):
    storage = client.application.container.storage
    assert request_account(client).status_code == 202
    assert not storage.tenant_dir('NEWCO').exists()
    assert client.post('/auth/register/confirm', json={'code':mailbox['new@testing.test']}).json['request']['status'] == 'approved'
    account = AccountService(storage)._accounts('NEWCO')[0]
    assert account['roles'] == ['business_owner'] and account['permissions'] == []
    assert verify_password('Signup-test-password-123', account['password_hash'])
    assert tenant_access.activation('NEWCO')['active'] is False
    assert client.get('/admin/api/catalog?tenant=NEWCO').status_code == 401
    assert client.post('/auth/register/confirm', json={'code':mailbox['new@testing.test']}).status_code == 400
    login = client.post('/auth/login', json={'tenant':'NEWCO','email':account['email'],'password':'Signup-test-password-123'})
    assert login.status_code == 202
    assert client.get('/admin/api/catalog?tenant=NEWCO').status_code == 401
    assert client.post('/auth/mfa/confirm', json={'code':generate_totp_token(login.json['mfa']['setup_key'])}).status_code == 200
    assert client.get('/billing/subscription?tenant=NEWCO').status_code == 200
    assert client.put('/admin/api/profile?tenant=NEWCO', json={'about':'blocked'}).status_code == 403
    assert client.put('/files/raw/catalog.json?tenant=NEWCO', json=[]).status_code == 403
    assert client.get('/admin/api/platform').status_code == 403


def test_join_approval_is_scoped_and_least_privilege(client, app, mailbox):
    assert request_account(client, 'join', 'EXAMPLE').status_code == 202
    assert client.post('/auth/register/confirm', json={'code':mailbox['new@testing.test']}).json['request']['status'] == 'pending'
    assert not AccountService(app.container.storage).list_accounts('EXAMPLE')
    operator = app.test_client()
    assert operator.get('/auth/registration').json['request'] is None
    owner(operator)
    rows = operator.get('/admin/api/join-requests').json['requests']
    assert len(rows) == 1 and set(rows[0]) == {'id','email','created'}
    path = '/admin/api/join-requests/' + rows[0]['id']
    assert operator.post(path+'?tenant=OTHER', json={'decision':'approve'}).status_code == 403
    assert operator.post(path, json={'decision':'approve','roles':['platform_admin']}).status_code == 200
    assert operator.post(path, json={'decision':'approve'}).status_code == 409
    account = AccountService(app.container.storage)._accounts('EXAMPLE')[0]
    assert account['roles'] == ['business_staff'] and account['permissions'] == []
    assert client.get('/auth/registration').json['request']['status'] == 'approved'
    login = client.post('/auth/login', json={'tenant':'EXAMPLE','email':account['email'],'password':'Signup-test-password-123'})
    assert login.status_code == 202
    assert client.post('/auth/mfa/confirm', json={'code':generate_totp_token(login.json['mfa']['setup_key'])}).status_code == 200
    assert client.get('/admin/api/join-requests').status_code == 403
    assert client.get('/billing/subscription').status_code == 403


def test_code_attempt_limit_and_expiry(client, mailbox):
    assert request_account(client).status_code == 202
    wrong = '000000' if mailbox['new@testing.test'] != '000000' else '111111'
    # Call the service directly to exercise the per-code limit independently of IP throttling.
    with client.session_transaction() as state:
        request_id = state['registration_request']
    with client.application.test_request_context():
        from flask import session
        session['registration_request'] = request_id
        for _ in range(5):
            with pytest.raises(ValueError):
                registration.confirm(wrong)
        with pytest.raises(ValueError):
            registration.confirm(mailbox['new@testing.test'])
        assert registration.status()['status'] == 'expired'
    assert not client.application.container.storage.tenant_dir('NEWCO').exists()


def test_expired_code_cannot_create_tenant(client, mailbox):
    request_account(client)
    with session_store.connection() as db:
        db.execute('UPDATE registration_requests SET expires=0')
    assert client.post('/auth/register/confirm', json={'code':mailbox['new@testing.test']}).status_code == 400
    assert not client.application.container.storage.tenant_dir('NEWCO').exists()


def test_existing_tenant_not_overwritten(client, mailbox):
    storage = client.application.container.storage
    original = storage.read_json('EXAMPLE', 'catalog.json')
    request_account(client, tenant='EXAMPLE')
    assert client.post('/auth/register/confirm', json={'code':mailbox['new@testing.test']}).status_code == 400
    assert storage.read_json('EXAMPLE', 'catalog.json') == original
    assert not AccountService(storage).list_accounts('EXAMPLE')


def test_rejected_join_creates_no_account(client, app, mailbox):
    request_account(client, 'join', 'EXAMPLE')
    client.post('/auth/register/confirm', json={'code':mailbox['new@testing.test']})
    operator = app.test_client()
    owner(operator)
    row = operator.get('/admin/api/join-requests').json['requests'][0]
    assert operator.post('/admin/api/join-requests/'+row['id'], json={'decision':'reject'}).status_code == 200
    assert client.get('/auth/registration').json['request']['status'] == 'rejected'
    assert not AccountService(app.container.storage).list_accounts('EXAMPLE')


def test_mail_failure_never_creates_account(client, mailbox, monkeypatch):
    def unavailable(*args):
        raise OSError('private SMTP error')
    monkeypatch.setattr(registration_mail, 'send_code', unavailable)
    response = request_account(client)
    assert response.status_code == 503 and 'private SMTP error' not in response.text
    with session_store.connection() as db:
        row = db.execute('SELECT password_hash,code_hash FROM registration_requests').fetchone()
    assert tuple(row) == ('','')


@pytest.mark.parametrize('email', ['one,two@example.test', 'Name<one@example.test>', 'one@example.test\r\nBcc:other@example.test'])
def test_mail_header_injection_rejected(client, mailbox, email):
    response = client.post('/auth/register', json={'email':email,'password':'Signup-test-password-123','kind':'join','tenant':'EXAMPLE'})
    assert response.status_code == 400 and not mailbox


def test_signup_requires_csrf_and_same_origin(app, mailbox):
    from flask.testing import FlaskClient
    browser = FlaskClient(app)
    assert browser.post('/auth/register', json={}).status_code == 403
    csrf = browser.get('/auth/session').json['csrf_token']
    assert browser.post('/auth/register', json={}, headers={'X-CSRF-Token':csrf,'Origin':'https://attacker.example'}).status_code == 403
    assert not mailbox
