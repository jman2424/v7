"""Disposable PostgreSQL checks for one-use OIDC state and provider link ownership."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from flask import Flask, session

from retrieval.storage import Storage
from service import oidc_login


def _app(runtime, monkeypatch):
    app = Flask(__name__)
    app.secret_key = 'Native-OIDC-local-test-secret-only-123'
    app.container = SimpleNamespace(storage=Storage(runtime['tenant']), settings=SimpleNamespace(
        BUSINESS_KEY=runtime['tenant'], BASE_URL='http://localhost:10000', ENVIRONMENT='development'))
    monkeypatch.setenv('V7_GOOGLE_CLIENT_ID', 'native-google-unit-client')
    monkeypatch.setenv('V7_GOOGLE_CLIENT_SECRET', 'native-google-unit-secret')
    return app


def test_postgres_oidc_state_is_consumed_once_under_concurrent_callbacks(pg_runtime, monkeypatch):
    app = _app(pg_runtime, monkeypatch)
    with app.test_request_context():
        query = parse_qs(urlsplit(oidc_login.start('google', {
            'intent': 'login', 'tenant': pg_runtime['tenant'],
        })['authorization_url']).query)
        browser = session['oidc_browser']
        config = oidc_login._provider('google')
    ready = Barrier(2)
    def consume(_):
        with app.test_request_context():
            session['oidc_browser'] = browser
            ready.wait(timeout=10)
            try:
                oidc_login._consume_state(config, query['state'][0])
                return 'consumed'
            except ValueError as exc:
                assert str(exc) == 'invalid_oidc_state'
                return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == ['consumed', 'rejected']
    assert pg_runtime['admin'].execute('SELECT count(*) FROM v7_private.oidc_states WHERE state_hash=%s',
        (oidc_login._digest(query['state'][0]),)).fetchone()[0] == 0


def test_postgres_oidc_subject_link_cannot_move_between_accounts(pg_runtime, monkeypatch):
    app = _app(pg_runtime, monkeypatch)
    users = [{'id': name, 'email': name + '@example.test', 'roles': ['business_owner'],
              'tenant': pg_runtime['tenant']} for name in ('oidc-first', 'oidc-second')]
    subject = 'native-subject-' + pg_runtime['tenant']
    ready = Barrier(2)
    def link(user):
        with app.test_request_context():
            ready.wait(timeout=10)
            try:
                oidc_login._save_link(oidc_login._provider('google'), user,
                                      'https://accounts.google.com', subject)
                return 'linked'
            except ValueError as exc:
                assert str(exc) == 'provider_already_linked'
                return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(link, users)) == ['linked', 'rejected']
    row = pg_runtime['admin'].execute('SELECT account,identity FROM v7_private.oidc_links WHERE subject=%s',
                                    (subject,)).fetchall()
    assert len(row) == 1
    assert row[0][0] in {oidc_login.account_key(user) for user in users}
