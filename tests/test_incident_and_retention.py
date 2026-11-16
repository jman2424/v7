"""Emergency sign-out is scoped to the business; ended businesses are kept 30 days and then reviewed, never auto-deleted."""
import json
import time

from service import business_retention, mcp_auth, session_store, subscriptions, tenant_access, trusted_devices
from service.incident_response import revoke_business_access
from tests.test_payment_recovery import _paid_business
from tests.test_subscriptions import identity

DAY = 86400


def _people():
    for user_id, tenant in (('owner-a', 'EXAMPLE'), ('owner-b', 'OTHER'), ('admin', None)):
        person = {'id': user_id, 'email': user_id + '@example.test', 'roles': ['platform_admin' if tenant is None else 'business_owner'],
                  'tenant': tenant}
        session_store.create(person, 'r1')
        with trusted_devices._database() as db:
            trusted_devices._tables(db)
            db.execute('INSERT INTO trusted_devices VALUES (?,?,?,?)',
                       (user_id + '-device', json.dumps([user_id, person['email'], tenant or '']), 'r1', time.time() + DAY))
        with mcp_auth.database() as db:
            db.execute('INSERT INTO mcp_grants VALUES (?,?,?,?)',
                       (user_id + '-grant', 'access', json.dumps({'identity': person}), time.time() + DAY))


def _left():
    with session_store.connection() as db:
        sessions = sorted(json.loads(row[0])['id'] for row in db.execute('SELECT identity FROM management_sessions'))
        devices = sorted(json.loads(row[0])[0] for row in db.execute('SELECT account FROM trusted_devices'))
        grants = sorted(json.loads(row[0])['identity']['id'] for row in db.execute('SELECT payload FROM mcp_grants'))
    return sessions, devices, grants


def test_emergency_sign_out_is_limited_to_one_business_and_spares_platform_admins(client):
    _people()
    counts = revoke_business_access('EXAMPLE')
    assert counts == {'sessions': 1, 'trusted_devices': 1, 'mcp_connections': 1}
    assert all('owner-a' not in names and 'owner-b' in names and 'admin' in names for names in _left())
    revoke_business_access(None)
    assert _left() == (['admin'], ['admin'], ['admin'])


def test_only_platform_admins_can_sign_businesses_out_and_must_say_why(client):
    identity(client, 'business_owner')
    assert client.post('/admin/api/platform/revoke-access', json={'tenant': 'EXAMPLE', 'reason': 'Leaked password'}).status_code == 403
    identity(client)
    assert client.post('/admin/api/platform/revoke-access', json={'tenant': 'EXAMPLE', 'reason': ''}).json == {'error': 'revocation_reason_required'}
    assert client.post('/admin/api/platform/revoke-access', json={'tenant': 'NOPE', 'reason': 'Leaked password'}).status_code == 404
    response = client.post('/admin/api/platform/revoke-access', json={'tenant': 'EXAMPLE', 'reason': 'Leaked password'})
    assert response.status_code == 200 and response.json['ok'] is True


def test_ended_business_is_kept_thirty_days_then_awaits_review(client):
    _paid_business('canceled')
    ended = int(time.time()) - 5
    business_retention.observe('EXAMPLE', 'canceled', ended)
    state = tenant_access.activation('EXAMPLE')
    assert state == {'active': False, 'status': 'subscription_ended', 'ended': ended, 'retention_ends': ended + 30 * DAY}
    assert [row['tenant'] for row in business_retention.review_queue()['retained']] == ['EXAMPLE']
    later = business_retention.review_queue(now=ended + 30 * DAY)
    assert [row['tenant'] for row in later['awaiting_review']] == ['EXAMPLE'] and not later['retained']
    # Repeated provider events never move the end date.
    business_retention.observe('EXAMPLE', 'canceled', ended + 10 * DAY)
    assert business_retention.current('EXAMPLE')['ended'] == ended
    business_retention.decide('EXAMPLE', 'keep', 'admin')
    assert [row['tenant'] for row in business_retention.review_queue(now=ended + 40 * DAY)['kept']] == ['EXAMPLE']
    # Business data is still there: nothing was deleted.
    assert client.application.container.storage.tenant_exists('EXAMPLE')


def test_subscribing_again_ends_the_retention_clock(client):
    business_retention.observe('EXAMPLE', 'canceled', int(time.time()))
    business_retention.observe('EXAMPLE', 'active')
    assert business_retention.current('EXAMPLE') is None


def test_untrusted_end_dates_are_replaced_by_now(client):
    business_retention.observe('EXAMPLE', 'canceled', int(time.time()) + 90 * DAY)
    assert abs(business_retention.current('EXAMPLE')['ended'] - time.time()) < 60


def test_stripe_sync_starts_retention_for_the_current_subscription(client, monkeypatch):
    _paid_business('active')
    with subscriptions.connection('EXAMPLE') as db:
        ref = db.execute("SELECT ref FROM billing_contracts WHERE tenant='EXAMPLE' AND kind='platform'").fetchone()['ref']
        db.execute("INSERT INTO billing_references VALUES (?,?,?) ON CONFLICT DO NOTHING", (ref, 'EXAMPLE', 'platform'))
    data = {'id': 'sub_grace', 'status': 'canceled', 'ended_at': int(time.time()) - 60, 'customer': 'cus_x',
            'metadata': {'tenant': 'EXAMPLE', 'kind': 'platform', 'billing_ref': ref}, 'items': {'data': []}}
    monkeypatch.setattr(subscriptions.BillingClient, 'stripe_request', lambda *args, **kwargs: dict(data))
    monkeypatch.setattr('service.business_applications.verify_payment', lambda *args, **kwargs: None)
    subscriptions.sync_subscription('sub_grace')
    assert business_retention.current('EXAMPLE')['ended'] == data['ended_at']


def test_retention_review_is_for_platform_admins_only(client):
    business_retention.observe('EXAMPLE', 'canceled', int(time.time()))
    identity(client, 'business_owner')
    assert client.get('/admin/api/platform/retention').status_code == 403
    assert client.put('/admin/api/platform/retention', json={'tenant': 'EXAMPLE', 'decision': 'keep'}).status_code == 403
    identity(client)
    assert client.get('/admin/api/platform/retention').json['retention_days'] == 30
    assert client.put('/admin/api/platform/retention', json={'tenant': 'EXAMPLE', 'decision': 'delete'}).json == {
        'error': 'invalid_retention_decision'}
    assert client.put('/admin/api/platform/retention', json={'tenant': 'EXAMPLE', 'decision': 'keep'}).status_code == 200
