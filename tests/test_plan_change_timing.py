"""Higher plans start now; lower plans and shorter billing wait for renewal; cancellation can be undone."""
import copy

import pytest

from service import billing_management, subscriptions
from tests.test_billing_management import confirm_plan, managed_subscription  # noqa: F401
from tests.test_subscriptions import identity, stripe as stripe_fixture

stripe = stripe_fixture
SCHEDULE = 'sub_sched_managed'


def _fake_schedules(subject, stripe, *, fail_update=False):
    """Extend the managed subscription's fake Stripe with schedules and reactivation."""
    original, data, store = stripe.side_effect, subject['data'], {}

    def provider(method, path, body=None, **kwargs):
        if method == 'POST' and path == '/v1/subscription_schedules':
            assert body == {'from_subscription': 'sub_managed'}
            item = data['items']['data'][0]
            start = subject['now'] - 100
            store[SCHEDULE] = {'id': SCHEDULE, 'subscription': 'sub_managed', 'status': 'active', 'metadata': {},
                               'current_phase': {'start_date': start},
                               'phases': [{'start_date': start, 'end_date': item['current_period_end'],
                                           'items': [{'price': item['price']['id'], 'quantity': 1}],
                                           'default_tax_rates': [{'id': 'txr_test'}],
                                           'discounts': [{'coupon': None, 'discount': 'di_half', 'promotion_code': None}]}]}
            data['schedule'] = SCHEDULE
            return copy.deepcopy(store[SCHEDULE])
        if method == 'POST' and path == '/v1/subscription_schedules/' + SCHEDULE:
            if fail_update:
                raise ValueError('stripe_request_failed')
            schedule = store[SCHEDULE]
            schedule['metadata'] = {'v7_plan_change': body['metadata[v7_plan_change]']}
            schedule['phases'] = [schedule['phases'][0], {'start_date': body['phases[0][end_date]'],
                                                          'items': [{'price': body['phases[1][items][0][price]'], 'quantity': 1}]}]
            schedule['update'] = body
            return copy.deepcopy(schedule)
        if method == 'GET' and path == '/v1/subscription_schedules/' + SCHEDULE:
            return copy.deepcopy(store[SCHEDULE])
        if method == 'POST' and path == '/v1/subscription_schedules/' + SCHEDULE + '/release':
            store[SCHEDULE]['status'] = 'released'
            data.pop('schedule', None)
            return {'id': SCHEDULE, 'status': 'released'}
        if method == 'POST' and path == '/v1/subscriptions/sub_managed':
            assert body == {'cancel_at_period_end': 'false'}
            data['cancel_at_period_end'] = False
            return copy.deepcopy(data)
        return original(method, path, body, **kwargs)

    stripe.side_effect = provider
    return store


def _on_business(client, subject):
    assert client.post('/billing/change-plan', json={'plan_id': 'business'}).status_code == 200
    confirm_plan(subject, 'business')
    subscriptions.sync_subscription('sub_managed')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'business'


def _renew(subject, store, plan_id):
    """Stripe reaches the renewal date and moves the subscription to the scheduled price."""
    subject['data']['items']['data'][0]['price'] = subject['price'](plan_id)
    subject['data'].pop('latest_invoice', None)
    store[SCHEDULE]['current_phase'] = {'start_date': store[SCHEDULE]['phases'][1]['start_date']}


def test_downgrade_waits_for_renewal_and_charges_nothing_today(client, stripe, managed_subscription):  # noqa: F811
    _on_business(client, managed_subscription)
    store = _fake_schedules(managed_subscription, stripe)
    stripe.reset_mock(return_value=False, side_effect=False)
    response = client.post('/billing/change-plan', json={'plan_id': 'starter'})
    assert response.status_code == 200, response.json
    period_end = managed_subscription['data']['items']['data'][0]['current_period_end']
    assert response.json == {'scheduled': True, 'plan_id': 'starter', 'interval': 'month', 'effective': period_end}
    paths = [call.args[1] for call in stripe.call_args_list]
    assert '/v1/billing_portal/sessions' not in paths  # No hosted payment step: nothing is charged.
    update = store[SCHEDULE]['update']
    assert update['end_behavior'] == 'release' and update['proration_behavior'] == 'none'
    assert update['phases[0][items][0][price]'] == 'price_business'
    assert update['phases[0][end_date]'] == period_end
    assert update['phases[1][items][0][price]'] == 'price_starter' and update['phases[1][iterations]'] == 1
    # Tax and the existing discount carry into the new phase.
    assert update['phases[1][default_tax_rates][0]'] == 'txr_test'
    assert update['phases[1][discounts][0][discount]'] == 'di_half'
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'business'
    summary = billing_management.summary('EXAMPLE')
    assert summary['scheduled_change'] == {'plan_id': 'starter', 'interval': 'month', 'effective': period_end}
    assert not summary['can_change_plan'] and not summary['can_cancel']
    assert client.post('/billing/cancel-subscription', json={}).json == {'error': 'scheduled_change_pending'}
    _renew(managed_subscription, store, 'starter')
    subscriptions.sync_subscription('sub_managed')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'starter'
    assert billing_management.summary('EXAMPLE')['scheduled_change'] is None
    # Our finished schedule is released, so the owner can change plan again straight away.
    assert client.post('/billing/change-plan', json={'plan_id': 'business'}).status_code == 200
    assert store[SCHEDULE]['status'] == 'released'


def test_keep_current_plan_releases_the_schedule(client, stripe, managed_subscription):  # noqa: F811
    _on_business(client, managed_subscription)
    store = _fake_schedules(managed_subscription, stripe)
    assert client.post('/billing/change-plan', json={'plan_id': 'starter'}).json['scheduled']
    response = client.post('/billing/cancel-scheduled-change', json={})
    assert response.status_code == 200, response.json
    assert store[SCHEDULE]['status'] == 'released'
    assert billing_management.summary('EXAMPLE')['scheduled_change'] is None
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'business'
    assert client.post('/billing/cancel-scheduled-change', json={}).json == {'error': 'no_scheduled_change'}


def test_failed_schedule_update_leaves_nothing_scheduled(client, stripe, managed_subscription):  # noqa: F811
    _on_business(client, managed_subscription)
    store = _fake_schedules(managed_subscription, stripe, fail_update=True)
    assert client.post('/billing/change-plan', json={'plan_id': 'starter'}).status_code == 400
    assert store[SCHEDULE]['status'] == 'released'
    assert billing_management.summary('EXAMPLE')['scheduled_change'] is None
    with subscriptions.connection('EXAMPLE') as db:
        assert db.execute("SELECT status FROM billing_plan_changes WHERE plan_id='starter'").fetchone()['status'] == 'failed'


def test_lower_price_never_grants_a_plan_that_was_not_scheduled(client, stripe, managed_subscription):  # noqa: F811
    _on_business(client, managed_subscription)
    store = _fake_schedules(managed_subscription, stripe)
    assert client.post('/billing/change-plan', json={'plan_id': 'starter'}).json['scheduled']
    _renew(managed_subscription, store, 'scale')  # A price nobody scheduled or paid for.
    with pytest.raises(ValueError, match='unknown_billing_plan'):
        subscriptions.sync_subscription('sub_managed')
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'business'


def test_monthly_to_yearly_is_charged_now_with_a_new_billing_period(client, stripe, managed_subscription, monkeypatch):  # noqa: F811
    monkeypatch.setattr('service.plan_catalog.YEARLY_OFFERED', True)  # Yearly is not offered today.
    original = stripe.side_effect

    def provider(method, path, body=None, **kwargs):
        if method == 'POST' and path == '/v1/prices' and body['recurring[interval]'] == 'year':
            return {**managed_subscription['price'](body['metadata[v7_plan_id]']), 'id': 'price_starterYear',
                    'unit_amount': 99000, 'recurring': {'interval': 'year', 'interval_count': 1, 'usage_type': 'licensed'}}
        return original(method, path, body, **kwargs)

    stripe.side_effect = provider
    response = client.post('/billing/change-plan', json={'plan_id': 'starter', 'interval': 'year'})
    assert response.status_code == 200, response.json
    assert response.json['url'].startswith('https://billing.stripe.com/')
    config = next(call.args[2] for call in stripe.call_args_list if call.args[1] == '/v1/billing_portal/configurations')
    assert config['features[subscription_update][billing_cycle_anchor]'] == 'now'
    assert subscriptions.billing_interval('EXAMPLE') == 'month'  # Not until Stripe confirms payment.


def test_yearly_to_monthly_waits_for_renewal(client, stripe, managed_subscription):  # noqa: F811
    with subscriptions.connection('EXAMPLE') as db:
        db.execute('INSERT INTO billing_interval_choices VALUES (?,?,?)', (managed_subscription['ref'], 'EXAMPLE', 'year'))
    year_price = {**managed_subscription['price']('starter'), 'id': 'price_starterYear', 'unit_amount': 99000,
                  'recurring': {'interval': 'year', 'interval_count': 1, 'usage_type': 'licensed'}}
    managed_subscription['data']['items']['data'][0]['price'] = year_price
    store = _fake_schedules(managed_subscription, stripe)
    response = client.post('/billing/change-plan', json={'plan_id': 'starter', 'interval': 'month'})
    assert response.status_code == 200, response.json
    assert response.json['scheduled'] and response.json['interval'] == 'month'
    assert store[SCHEDULE]['update']['phases[0][items][0][price]'] == 'price_starterYear'
    _renew(managed_subscription, store, 'starter')
    subscriptions.sync_subscription('sub_managed')
    assert subscriptions.billing_interval('EXAMPLE') == 'month'
    assert subscriptions.plan_state('EXAMPLE')['active_plan'] == 'starter'


def test_invalid_interval_change_never_reaches_stripe(client, stripe):
    identity(client, 'business_owner')
    for value in ['week', 'YEAR', 1, {}]:
        assert client.post('/billing/change-plan', json={'plan_id': 'starter', 'interval': value}).json == {'error': 'invalid_billing_interval'}
    stripe.assert_not_called()


def test_cancellation_can_be_undone_before_it_takes_effect(client, stripe, managed_subscription):  # noqa: F811
    _fake_schedules(managed_subscription, stripe)
    assert client.post('/billing/reactivate-subscription', json={}).json == {'error': 'subscription_not_cancelling'}
    managed_subscription['data']['cancel_at_period_end'] = True
    subscriptions.sync_subscription('sub_managed')
    assert billing_management.summary('EXAMPLE')['can_reactivate']
    identity(client, 'business_staff')
    assert client.post('/billing/reactivate-subscription', json={}).status_code == 403
    identity(client, 'business_owner')
    response = client.post('/billing/reactivate-subscription', json={})
    assert response.status_code == 200, response.json
    assert subscriptions._contract('EXAMPLE', 'platform')['cancel_at_end'] == 0
    assert not billing_management.summary('EXAMPLE')['can_reactivate']
