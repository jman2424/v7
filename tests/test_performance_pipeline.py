"""Telemetry durability, scoped aggregates and verified streaming boundaries."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from service import analytics_db, telemetry_outbox, performance_metrics
from tests.test_owner_console import sign_in


def test_telemetry_survives_worker_restart_and_concurrent_replay_without_duplicates(app, monkeypatch):
    monkeypatch.setattr(telemetry_outbox, 'kick', lambda tenant: True)
    analytics_db.log_message(tenant='EXAMPLE', channel='web', direction='outbound',
                            session_id='durable-test', text='Important conversation history', message_id='durable-reply')
    telemetry_outbox.enqueue('EXAMPLE', 'web', 'durable-test', [
        {'event_type': 'pipeline_in', 'meta': {'mode': 'v7', 'text_len': 10, 'customer_message': 'never store'}},
        {'event_type': 'pipeline_out', 'meta': {'mode': 'v7', 'reply_len': 20}},
    ])
    with analytics_db._conn() as db:
        pending = db.execute("SELECT meta_json FROM events WHERE event_type='pipeline_pending'").fetchone()[0]
        assert 'never store' not in pending
    # No in-memory payload survives; independently reopened DB connections do.
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(workers.map(telemetry_outbox.drain, ['EXAMPLE', 'EXAMPLE'])) == 1
    assert telemetry_outbox.drain('EXAMPLE') == 0
    with analytics_db._conn() as db:
        assert db.execute("SELECT count(*) FROM events WHERE event_type='pipeline_in'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM events WHERE event_type='pipeline_out'").fetchone()[0] == 1
        assert db.execute("SELECT text FROM events WHERE message_id='durable-reply'").fetchone()[0] == 'Important conversation history'


def test_telemetry_other_tenants_and_important_audit_types_cannot_be_processed(app, monkeypatch):
    monkeypatch.setattr(telemetry_outbox, 'kick', lambda tenant: True)
    telemetry_outbox.enqueue('ALPHA', 'web', 'test', [{'event_type': 'pipeline_turn', 'meta': {'ok': True}}])
    assert telemetry_outbox.drain('BETA') == 0
    with pytest.raises(ValueError):
        telemetry_outbox.enqueue('ALPHA', 'web', 'test', [{'event_type': 'payment', 'meta': {}}])
    assert telemetry_outbox.drain('ALPHA') == 1


def test_metrics_require_permission_and_do_not_cross_tenants(app, client):
    performance_metrics.record('EXAMPLE', 'synthetic_test_ms', 10)
    performance_metrics.record('BETA', 'synthetic_test_ms', 999)
    assert client.get('/admin/api/performance?tenant=EXAMPLE').status_code == 401
    sign_in(client, tenant='EXAMPLE')
    data = client.get('/admin/api/performance?tenant=EXAMPLE').json
    assert data['metrics']['synthetic_test_ms']['p95'] == 10
    assert client.get('/admin/api/performance?tenant=BETA').status_code in (403, 404)


def test_browser_timings_require_valid_conversation_and_numeric_payload(app):
    # The shared test client auto-injects CSRF headers, unlike public widgets.
    from flask.testing import FlaskClient
    client = FlaskClient(app)
    issued = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'hello'}).json
    valid = {'tenant': 'EXAMPLE', 'conversation_token': issued['conversation_token'],
             'first_visible_ms': 500, 'total_ms': 800}
    assert client.post('/chat/performance', json=valid).status_code == 204
    assert client.post('/chat/performance', json={**valid, 'conversation_token': 'forged'}).status_code == 403
    assert client.post('/chat/performance', json={**valid, 'first_visible_ms': 'secret'}).status_code == 400
    assert client.post('/chat/performance', json={**valid, 'customer_message': 'do not retain'}).status_code == 400
    assert client.post('/chat/performance', json=valid,
                       headers={'Origin': 'https://unapproved.invalid'}).status_code == 403


def test_streaming_contains_only_complete_verified_reply_and_committed_history(client, app):
    response = client.post('/chat_api', headers={'Accept': 'text/event-stream'},
        json={'tenant': 'EXAMPLE', 'message': 'green means good'})
    assert response.status_code == 200 and response.mimetype == 'text/event-stream'
    assert response.headers['Cache-Control'] == 'no-store'
    events = response.text.strip().split('\n\n')
    chunks = [json.loads(row.split('data: ', 1)[1])['text'] for row in events if row.startswith('event: reply_chunk')]
    final = json.loads(events[-1].split('data: ', 1)[1])
    assert ''.join(chunks) == final['reply'] and 'good' in final['reply']
    followup = client.post('/chat_api', json={'tenant': 'EXAMPLE', 'message': 'What does green mean?',
                                              'conversation_token': final['conversation_token']})
    assert 'good' in followup.json['reply']


def test_stream_errors_keep_original_json_status_without_partial_content(client, monkeypatch, app):
    monkeypatch.setattr(app.container.handler, 'handle', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('synthetic')))
    response = client.post('/chat_api', headers={'Accept': 'text/event-stream'},
                           json={'tenant': 'EXAMPLE', 'message': 'A business question'})
    assert response.status_code == 503 and response.mimetype == 'application/json'
    assert 'reply_chunk' not in response.text


def test_native_telemetry_outbox_uses_tenant_rls_and_commits_once(pg_runtime, monkeypatch):
    monkeypatch.setattr(telemetry_outbox, 'kick', lambda tenant: True)
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    telemetry_outbox.enqueue(tenant, 'web', 'synthetic', [{'event_type': 'pipeline_turn', 'meta': {'ok': True}}])
    assert telemetry_outbox.drain(other) == 0
    assert telemetry_outbox.drain(tenant) == 1
    assert telemetry_outbox.drain(tenant) == 0


def test_ambiguous_enqueue_commit_and_recovery_do_not_duplicate(app, monkeypatch):
    monkeypatch.setenv('V7_ASYNC_TELEMETRY', 'true')
    monkeypatch.setattr(telemetry_outbox, 'kick', lambda tenant: True)
    original = telemetry_outbox.enqueue

    def ambiguous(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError('synthetic lost commit acknowledgement')

    monkeypatch.setattr(telemetry_outbox, 'enqueue', ambiguous)
    with telemetry_outbox.collect('EXAMPLE', 'web', 'synthetic'):
        assert telemetry_outbox.defer('pipeline_turn', {'ok': True})
    assert telemetry_outbox.drain('EXAMPLE') == 1
    with analytics_db._conn() as db:
        assert db.execute("SELECT count(*) FROM events WHERE event_type='pipeline_turn'").fetchone()[0] == 1


def test_scheduling_failure_after_commit_preserves_durable_job(app, monkeypatch):
    def broken(tenant):
        raise OSError('synthetic scheduler failure')
    monkeypatch.setattr(telemetry_outbox, 'kick', broken)
    telemetry_outbox.enqueue('EXAMPLE', 'web', 'test', [{'event_type': 'pipeline_turn', 'meta': {'ok': True}}])
    assert telemetry_outbox.drain('EXAMPLE') == 1


def test_recovery_retries_without_new_traffic_or_in_memory_payload(app, monkeypatch):
    from threading import Event
    monkeypatch.setattr(telemetry_outbox, '_stop', Event())
    monkeypatch.setattr(telemetry_outbox, 'kick', lambda tenant: True)
    telemetry_outbox.enqueue('EXAMPLE', 'web', 'test', [{'event_type': 'pipeline_turn', 'meta': {'ok': True}}])
    original = telemetry_outbox.recover
    attempts = []
    def transient():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError('synthetic transient connection failure')
        original()
        telemetry_outbox._stop.set()
    monkeypatch.setattr(telemetry_outbox, 'recover', transient)
    import itertools
    clock = itertools.count(0, 100)
    monkeypatch.setattr('time.monotonic', lambda: next(clock))
    telemetry_outbox._run()
    assert len(attempts) == 2 and telemetry_outbox.drain('EXAMPLE') == 0


def test_native_recovery_covers_legacy_tenants_and_index_cannot_mutate_other_scope(pg_runtime, monkeypatch):
    from threading import Event
    from service import session_store
    monkeypatch.setattr(telemetry_outbox, '_stop', Event())
    monkeypatch.setattr(telemetry_outbox, 'kick', lambda tenant: True)
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    telemetry_outbox.enqueue(tenant, 'web', 'test', [{'event_type': 'pipeline_turn', 'meta': {'ok': True}}])
    with session_store.postgres_connection(other) as db:
        assert db.execute('DELETE FROM v7_private.telemetry_pending_tenants WHERE tenant=%s RETURNING tenant', (tenant,)).fetchone() is None
        assert db.execute('SELECT count(*) FROM v7_private.events WHERE tenant=%s', (tenant,)).fetchone()[0] == 0
    telemetry_outbox.recover()
    assert telemetry_outbox.drain(tenant) == 0
    with session_store.postgres_connection(tenant) as db:
        assert db.execute("SELECT count(*) FROM v7_private.events WHERE tenant=%s AND event_type='pipeline_turn'", (tenant,)).fetchone()[0] == 1


def test_restart_recovery_paginates_beyond_first_hundred_ownership_keys(app, monkeypatch):
    from threading import Event
    monkeypatch.setattr(telemetry_outbox, '_stop', Event())
    monkeypatch.setattr(telemetry_outbox, 'kick', lambda tenant: True)
    for number in range(103):
        telemetry_outbox.enqueue('QUEUE_' + str(number).zfill(3), 'web', 'test',
                                 [{'event_type': 'pipeline_turn', 'meta': {'ok': True}}])
    telemetry_outbox.recover()
    with analytics_db._conn() as db:
        assert db.execute("SELECT count(*) FROM events WHERE event_type='pipeline_pending'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM events WHERE event_type='pipeline_turn'").fetchone()[0] == 103


def test_native_enqueue_racing_drain_keeps_every_job_and_cleans_index(pg_runtime, monkeypatch):
    from service import session_store
    monkeypatch.setattr(telemetry_outbox, 'kick', lambda tenant: True)
    tenant = pg_runtime['tenant']
    def enqueue(number):
        telemetry_outbox.enqueue(tenant, 'web', 'test', [{'event_type': 'pipeline_turn', 'meta': {'text_len': number}}])
        telemetry_outbox.drain(tenant)
    with ThreadPoolExecutor(max_workers=3) as workers:
        list(workers.map(enqueue, range(12)))
    assert telemetry_outbox.drain(tenant) == 0
    with session_store.postgres_connection(tenant) as db:
        assert db.execute("SELECT count(*) FROM v7_private.events WHERE tenant=%s AND event_type='pipeline_turn'", (tenant,)).fetchone()[0] == 12
        assert db.execute('SELECT count(*) FROM v7_private.telemetry_pending_tenants WHERE tenant=%s', (tenant,)).fetchone()[0] == 0
