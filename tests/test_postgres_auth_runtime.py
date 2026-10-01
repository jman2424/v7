"""Native PostgreSQL auth regressions using only a disposable local database."""
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from types import SimpleNamespace

import pytest
from flask import Flask, session

from retrieval.storage import Storage
from service import account_mfa, registration, registration_mail, session_store
from service.account_service import ACCOUNT_FILE, AccountService
from service.security import authenticate_user, generate_totp_token, hash_password, management_user, start_management_session


def _app(runtime):
    app = Flask(__name__)
    app.secret_key = 'Native-local-auth-test-secret-only-123'
    app.container = SimpleNamespace(storage=Storage(runtime['tenant']))
    return app


def _mailbox(monkeypatch):
    sent = {}
    monkeypatch.setattr(registration_mail, 'configured', lambda: True)
    monkeypatch.setattr(registration_mail, 'send_code', lambda email, code: sent.update({email: code}))
    return sent


def _join_request(runtime, email):
    request_id = secrets.token_urlsafe(24)
    runtime['admin'].execute(
        'INSERT INTO v7_private.registration_requests '
        '(id,email,password_hash,kind,tenant,business_name,code_hash,expires,status,created) '
        'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (request_id, email, hash_password('Native-staff-test-password-123'), 'join', runtime['tenant'], '',
         '', time.time() + 600, 'pending', time.time()),
    )
    return request_id


def test_postgres_owner_signup_and_mfa_roundtrip(pg_runtime, monkeypatch):
    app = _app(pg_runtime)
    sent = _mailbox(monkeypatch)
    tenant = pg_runtime['tenant'] + '_OWNER'
    email = tenant.lower() + '@example.test'
    password = 'Native-owner-test-password-123'
    with app.test_request_context():
        assert registration.start({'email': email, 'password': password, 'kind': 'owner',
                                   'tenant': tenant, 'business_name': 'Native test business'})['status'] == 'verification'
        assert registration.confirm(sent[email])['status'] == 'approved'
        user = authenticate_user(app.container, email=email, password=password, tenant=tenant)
        assert user is not None
        challenge = account_mfa.begin(user, tenant)
        assert challenge['enrollment'] is True
        secret = challenge['setup_key']
        assert secret not in str(dict(session))
        verified = account_mfa.confirm(generate_totp_token(secret))
        identity = start_management_session(verified, tenant, mfa_verified=True)
        assert management_user() == identity
        token = session['management_token']
        assert session_store.read(token)[0]['tenant'] == tenant
        session_store.revoke(token)
        assert session_store.read(token) is None


def test_postgres_verification_attempts_commit_and_clear_credentials(pg_runtime, monkeypatch):
    app = _app(pg_runtime)
    sent = _mailbox(monkeypatch)
    email = pg_runtime['tenant'].lower() + '@example.test'
    with app.test_request_context():
        registration.start({'email': email, 'password': 'Native-staff-test-password-123', 'kind': 'join',
                            'tenant': pg_runtime['tenant']})
        request_id = session['registration_request']
        wrong = '000000' if sent[email] != '000000' else '111111'
        for _ in range(5):
            with pytest.raises(ValueError, match='Code not accepted'):
                registration.confirm(wrong)
        with pytest.raises(ValueError, match='Verification expired'):
            registration.confirm(sent[email])
        assert registration.status()['status'] == 'expired'
    row = pg_runtime['admin'].execute(
        'SELECT attempts,password_hash,code_hash,status FROM v7_private.registration_requests WHERE id=%s',
        (request_id,),
    ).fetchone()
    assert row == (5, '', '', 'expired')


def test_postgres_join_approval_rolls_back_account_and_status_together(pg_runtime, monkeypatch):
    app = _app(pg_runtime)
    request_id = _join_request(pg_runtime, pg_runtime['tenant'].lower() + '@example.test')
    execute = registration._execute

    def fail_status(db, sql, params=()):
        if sql.startswith('UPDATE registration_requests SET status='):
            raise RuntimeError('Injected request status failure')
        return execute(db, sql, params)

    with app.app_context(), monkeypatch.context() as patch:
        patch.setattr(registration, '_execute', fail_status)
        with pytest.raises(RuntimeError, match='Injected request status failure'):
            registration.decide(pg_runtime['tenant'], request_id, True, 'test-owner')
    admin = pg_runtime['admin']
    assert admin.execute('SELECT status FROM v7_private.registration_requests WHERE id=%s',
                         (request_id,)).fetchone()[0] == 'pending'
    assert admin.execute('SELECT count(*) FROM v7_private.business_documents WHERE tenant=%s AND filename=%s',
                         (pg_runtime['tenant'], ACCOUNT_FILE)).fetchone()[0] == 0
    assert admin.execute('SELECT count(*) FROM v7_private.document_versions WHERE tenant=%s',
                         (pg_runtime['tenant'],)).fetchone()[0] == 0
    with app.app_context():
        registration.decide(pg_runtime['tenant'], request_id, True, 'test-owner')
        account = AccountService(app.container.storage).list_accounts(pg_runtime['tenant'])[0]
    assert account['roles'] == ['business_staff'] and account['permissions'] == []
    assert admin.execute('SELECT status,password_hash FROM v7_private.registration_requests WHERE id=%s',
                         (request_id,)).fetchone() == ('approved', '')


def test_postgres_concurrent_join_approvals_preserve_both_accounts(pg_runtime):
    app = _app(pg_runtime)
    emails = [pg_runtime['tenant'].lower() + suffix + '@example.test' for suffix in ('-one', '-two')]
    request_ids = [_join_request(pg_runtime, email) for email in emails]
    ready = Barrier(2)

    def approve(request_id):
        with app.app_context():
            ready.wait(timeout=10)
            registration.decide(pg_runtime['tenant'], request_id, True, 'test-owner')

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(approve, request_ids))
    assert {account['email'] for account in AccountService(app.container.storage).list_accounts(pg_runtime['tenant'])} == set(emails)


def test_postgres_concurrent_mfa_enrollment_rejects_the_losing_browser(pg_runtime, monkeypatch):
    app = _app(pg_runtime)
    user = {'id': 'native-mfa-' + pg_runtime['tenant'], 'email': pg_runtime['tenant'].lower() + '@example.test',
            'roles': ['business_owner'], 'tenant': pg_runtime['tenant'],
            '_credential_revision': 'native-test-revision', '_account_revision': 'native-account-test-revision'}
    # Keep both challenge revisions current so the test reaches the insert race.
    monkeypatch.setattr('service.security._revision', lambda identity: 'native-test-revision')
    challenges = []
    for _ in range(2):
        with app.test_request_context():
            challenge = account_mfa.begin(user, pg_runtime['tenant'])
            challenges.append((session['mfa_challenge'], challenge['setup_key']))
    ready = Barrier(2)
    execute = account_mfa._execute
    lookup_state = local()

    def concurrent_lookup(db, sql, params=()):
        result = execute(db, sql, params)
        if (sql == 'SELECT secret FROM account_authenticators WHERE account=?'
                and not getattr(lookup_state, 'synchronized', False)):
            # Race the initial enrollment lookup, then allow the winner's
            # post-commit credential-proof read to complete independently.
            lookup_state.synchronized = True
            ready.wait(timeout=10)
        return result

    monkeypatch.setattr(account_mfa, '_execute', concurrent_lookup)

    def confirm(challenge):
        token, secret = challenge
        with app.test_request_context():
            session['mfa_challenge'] = token
            try:
                account_mfa.confirm(generate_totp_token(secret))
                return ('approved', secret)
            except ValueError as exc:
                assert str(exc) == 'sign_in_again'
                return ('rejected', secret)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(confirm, challenges))
    assert sorted(status for status, _ in outcomes) == ['approved', 'rejected']
    winner = next(secret for status, secret in outcomes if status == 'approved')
    assert pg_runtime['admin'].execute('SELECT secret FROM v7_private.account_authenticators WHERE account=%s',
                                      (account_mfa.account_key(user),)).fetchone()[0] == winner


def test_postgres_login_limiter_is_shared_and_commits_attempts(pg_runtime):
    identifier = 'native-address-' + pg_runtime['tenant']
    assert [session_store.allow_login(identifier) for _ in range(6)] == [True] * 5 + [False]
    assert pg_runtime['admin'].execute('SELECT count(*) FROM v7_private.login_attempts WHERE ip_hash=%s',
                                      (session_store._digest(identifier),)).fetchone()[0] == 5


def test_postgres_owner_creation_rolls_back_when_final_status_fails(pg_runtime, monkeypatch):
    app = _app(pg_runtime)
    sent = _mailbox(monkeypatch)
    tenant = pg_runtime['tenant'] + '_ROLLBACK'
    email = tenant.lower() + '@example.test'
    execute = registration._execute
    with app.test_request_context():
        registration.start({'email':email, 'password':'Native-owner-test-password-123',
                            'kind':'owner', 'tenant':tenant, 'business_name':'Atomic owner'})
        request_id = session['registration_request']
        before = pg_runtime['admin'].execute('SELECT status,password_hash,code_hash FROM '
            'v7_private.registration_requests WHERE id=%s', (request_id,)).fetchone()
        def fail_status(db, sql, params=()):
            if sql.startswith("UPDATE registration_requests SET status='approved'"):
                raise RuntimeError('Injected owner approval failure')
            return execute(db, sql, params)
        with monkeypatch.context() as patch:
            patch.setattr(registration, '_execute', fail_status)
            with pytest.raises(RuntimeError, match='Injected owner approval failure'):
                registration.confirm(sent[email])
        admin = pg_runtime['admin']
        for table in ('tenants','business_documents','managed_businesses','document_versions'):
            assert admin.execute('SELECT count(*) FROM v7_private.'+table+' WHERE tenant=%s',
                                 (tenant,)).fetchone()[0] == 0
        assert admin.execute('SELECT status,password_hash,code_hash FROM '
            'v7_private.registration_requests WHERE id=%s', (request_id,)).fetchone() == before
        assert registration.confirm(sent[email])['status'] == 'approved'
        assert len(AccountService(app.container.storage).list_accounts(tenant)) == 1


def test_postgres_concurrent_owner_confirmations_create_one_complete_workspace(pg_runtime, monkeypatch):
    app = _app(pg_runtime)
    sent = _mailbox(monkeypatch)
    tenant = pg_runtime['tenant'] + '_CONCURRENT'
    requests = []
    for suffix in ('-one','-two'):
        email = tenant.lower() + suffix + '@example.test'
        with app.test_request_context():
            registration.start({'email':email, 'password':'Native-owner-test-password-123',
                                'kind':'owner', 'tenant':tenant, 'business_name':'Concurrent owner'})
            requests.append((session['registration_request'], sent[email], email))
    ready = Barrier(2)
    def confirm(request):
        request_id, code, email = request
        with app.test_request_context():
            session['registration_request'] = request_id
            ready.wait(timeout=10)
            try:
                return (registration.confirm(code)['status'], email)
            except ValueError as exc:
                assert 'workspace could not be created' in str(exc)
                return ('rejected', email)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(confirm, requests))
    assert sorted(status for status, _ in results) == ['approved','rejected']
    winner = next(email for status, email in results if status == 'approved')
    account = AccountService(app.container.storage).list_accounts(tenant)
    assert len(account) == 1 and account[0]['email'] == winner
    admin = pg_runtime['admin']
    assert admin.execute('SELECT count(*) FROM v7_private.tenants WHERE tenant=%s',
                         (tenant,)).fetchone()[0] == 1
    assert admin.execute('SELECT count(*) FROM v7_private.managed_businesses WHERE tenant=%s',
                         (tenant,)).fetchone()[0] == 1
    assert sorted(row[0] for row in admin.execute('SELECT status FROM '
        'v7_private.registration_requests WHERE tenant=%s', (tenant,)).fetchall()) == ['approved','verification']
