"""A failed renewal keeps service for seven days from the first failure, then pauses it."""
import time

import pytest

from service import payment_recovery as recovery, subscriptions, tenant_access
from tests import test_subscriptions

stripe = test_subscriptions.stripe
DAY = 86400


def _paid_business(status='active'):
    tenant_access.register('EXAMPLE', {'id': 'owner', 'email': 'owner@example.test', 'tenant': 'EXAMPLE',
                                       'roles': ['business_owner']})
    subscriptions.select_plan('EXAMPLE', 'starter')
    subscriptions._contract('EXAMPLE', 'platform')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_plan_state SET active_plan='starter' WHERE tenant='EXAMPLE'")
        db.execute("UPDATE billing_contracts SET status=?,subscription='sub_grace' WHERE tenant='EXAMPLE' AND kind='platform'",
                   (status,))
        db.execute("INSERT INTO billing_invoices VALUES ('in_first','EXAMPLE','platform','2026-10',1,NULL,9900,9900,0,'paid','[]',NULL)")


def _status(status):
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_contracts SET status=? WHERE tenant='EXAMPLE' AND kind='platform'", (status,))
        recovery.observe(db, 'EXAMPLE', 'sub_grace', status)


def test_service_continues_for_seven_days_then_pauses(client, monkeypatch):
    _paid_business()
    assert tenant_access.activation('EXAMPLE') == {'active': True, 'status': 'active'}
    start = time.time()
    monkeypatch.setattr(time, 'time', lambda: start)
    _status('past_due')
    during = tenant_access.activation('EXAMPLE')
    assert during['active'] is True and during['status'] == 'payment_recovery'
    assert during['grace_ends'] == int(start) + 7 * DAY
    monkeypatch.setattr(time, 'time', lambda: start + 7 * DAY + 1)
    after = tenant_access.activation('EXAMPLE')
    assert after['active'] is False and after['status'] == 'billing_suspended'


def test_repeated_failures_never_extend_the_window(client, monkeypatch):
    _paid_business()
    start = time.time()
    monkeypatch.setattr(time, 'time', lambda: start)
    _status('past_due')
    monkeypatch.setattr(time, 'time', lambda: start + 5 * DAY)
    _status('past_due')
    _status('unpaid')
    assert recovery.current('EXAMPLE')['started'] == int(start)


def test_payment_ends_the_window_and_a_later_failure_starts_a_new_one(client, monkeypatch):
    _paid_business()
    start = time.time()
    monkeypatch.setattr(time, 'time', lambda: start)
    _status('past_due')
    _status('active')
    assert recovery.current('EXAMPLE') is None
    assert tenant_access.activation('EXAMPLE')['status'] == 'active'
    monkeypatch.setattr(time, 'time', lambda: start + 40 * DAY)
    _status('past_due')
    assert recovery.current('EXAMPLE')['started'] == int(start + 40 * DAY)


def test_failure_without_a_window_is_not_given_free_service(client):
    _paid_business(status='past_due')
    assert tenant_access.activation('EXAMPLE')['status'] == 'billing_suspended'


def test_never_paid_business_is_not_treated_as_a_renewal_failure(client):
    tenant_access.register('EXAMPLE')
    subscriptions.select_plan('EXAMPLE', 'starter')
    subscriptions._contract('EXAMPLE', 'platform')
    with subscriptions.connection('EXAMPLE') as db:
        db.execute("UPDATE billing_contracts SET status='past_due' WHERE tenant='EXAMPLE' AND kind='platform'")
        recovery.observe(db, 'EXAMPLE', 'sub_grace', 'past_due')
    result = tenant_access.activation('EXAMPLE')
    assert result['active'] is False and result['status'] not in {'payment_recovery', 'billing_suspended'}


def test_suspended_business_gets_no_widget_and_no_ai(client, monkeypatch):
    _paid_business()
    start = time.time()
    monkeypatch.setattr(time, 'time', lambda: start)
    _status('past_due')
    assert 'chat_ui' in client.get('/widget.js?tenant=EXAMPLE').text
    monkeypatch.setattr(time, 'time', lambda: start + 8 * DAY)
    assert 'chat_ui' not in client.get('/widget.js?tenant=EXAMPLE').text


def test_each_notice_is_sent_once_in_order(client, monkeypatch):
    _paid_business()
    sent = []
    monkeypatch.setattr('service.registration_mail.send_transactional',
                        lambda email, subject, text, html, **kw: sent.append((email, subject, kw['idempotency_key'])))
    start = time.time()
    monkeypatch.setattr(time, 'time', lambda: start)
    _status('past_due')
    container = client.application.container
    with client.application.app_context():
        assert recovery.remind_all(container, now=start) == 1
        assert recovery.remind_all(container, now=start + 60) == 0
        assert recovery.remind_all(container, now=start + 5 * DAY + 1) == 1
        assert recovery.remind_all(container, now=start + 7 * DAY + 1) == 1
        assert recovery.remind_all(container, now=start + 8 * DAY) == 0
    assert [row[0] for row in sent] == ['owner@example.test'] * 3
    assert [row[1] for row in sent] == [recovery.NOTICES[stage][0] for stage in (1, 2, 3)]
    assert len({row[2] for row in sent}) == 3


def test_failed_send_is_retried_later(client, monkeypatch):
    _paid_business()
    attempts = []

    def flaky(email, subject, text, html, **kw):
        attempts.append(subject)
        if len(attempts) == 1:
            raise RuntimeError('mail down')

    monkeypatch.setattr('service.registration_mail.send_transactional', flaky)
    start = time.time()
    monkeypatch.setattr(time, 'time', lambda: start)
    _status('past_due')
    with client.application.app_context():
        assert recovery.remind_all(client.application.container, now=start) == 0
        assert recovery.remind_all(client.application.container, now=start + 3600) == 1
    assert len(attempts) == 2


@pytest.mark.parametrize('owner,expected', [
    (None, ''), ({'id': 'o', 'email': 'other@example.test', 'tenant': 'OTHER', 'roles': ['business_owner']}, '')])
def test_notice_goes_only_to_this_business_owner(client, owner, expected):
    tenant_access.register('EXAMPLE', owner)
    assert recovery.owner_email('EXAMPLE') == expected
