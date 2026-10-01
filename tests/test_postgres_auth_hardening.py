"""Authentication invariants with concurrent restricted PostgreSQL connections."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyotp
import pytest
from flask import Flask

from service import account_mfa, session_store
from service.login_limiter import LoginAttemptLimiter, LoginThrottled
from service.storage_readiness import validate_postgres_storage


def test_shared_account_limit_survives_different_workers_and_addresses(pg_runtime):
    app = Flask(__name__)
    app.secret_key = 'Native-auth-hardening-test-secret-only-123'
    ready = Barrier(6)

    def attempt(number):
        with app.app_context():
            limiter = LoginAttemptLimiter(max_attempts=3, window_seconds=900)
            subject = limiter.key(client_address=f'192.0.2.{number}',
                                  tenant=pg_runtime['tenant'], identifier='owner@example.test')
            ready.wait(timeout=10)
            try:
                return subject, limiter.begin(subject)
            except LoginThrottled as error:
                assert error.retry_after > 0
                return subject, None

    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(attempt, range(6)))
    subjects = {subject for subject, _ in outcomes}
    assert len(subjects) == 1
    subject = subjects.pop()
    assert sum(reservation is not None for _, reservation in outcomes) == 3
    with app.app_context():
        limiter = LoginAttemptLimiter(max_attempts=3, window_seconds=900)
        assert limiter.retry_after(subject) > 0
        limiter.reset(subject)
        assert limiter.retry_after(subject) == 0
    rows = pg_runtime['admin'].execute(
        'SELECT subject_hash FROM v7_private.auth_login_failures WHERE subject_hash=%s',
        (subject,),
    ).fetchall()
    assert rows == []


def test_same_authenticator_step_can_only_be_used_once_concurrently(pg_runtime):
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()
    account = 'native-code-use-' + pg_runtime['tenant']
    ready = Barrier(2)

    def consume(_number):
        ready.wait(timeout=10)
        try:
            with session_store.postgres_connection() as db:
                account_mfa._consume_code(db, account, secret, code)
            return 'accepted'
        except ValueError as error:
            assert str(error) == 'authenticator_code_reused'
            return 'rejected'

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(consume, range(2))) == ['accepted', 'rejected']
    rows = pg_runtime['admin'].execute(
        'SELECT secret_hash,timestep FROM v7_private.mfa_code_uses WHERE account=%s',
        (account,),
    ).fetchall()
    assert len(rows) == 1
    assert len(rows[0][0]) == 64 and secret not in rows[0][0]


def test_startup_rejects_missing_mfa_replay_constraint(pg_runtime):
    admin = pg_runtime['admin']
    try:
        admin.execute('ALTER TABLE v7_private.mfa_code_uses DROP CONSTRAINT mfa_code_uses_pkey')
        with pytest.raises(RuntimeError, match='authentication migrations are incomplete'):
            validate_postgres_storage(pg_runtime['tenant'])
    finally:
        admin.execute('ALTER TABLE v7_private.mfa_code_uses ADD PRIMARY KEY(account,secret_hash,timestep)')
    validate_postgres_storage(pg_runtime['tenant'])
