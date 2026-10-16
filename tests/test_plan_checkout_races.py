"""A checkout generation keeps one plan even while replacing canceled billing."""
import time

from service import subscriptions
from tests import test_postgres_plan_runtime, test_subscriptions

stripe = test_subscriptions.stripe
stripe_plan_provider = test_postgres_plan_runtime.stripe_plan_provider


def test_restarting_canceled_subscription_reserves_plan_before_provider_work(client, stripe, monkeypatch):
    _assert_restart_reserves_plan('EXAMPLE', stripe, monkeypatch)


def test_native_restarting_canceled_subscription_reserves_plan(pg_runtime, stripe_plan_provider, monkeypatch):
    _assert_restart_reserves_plan(pg_runtime['tenant'], stripe_plan_provider.stripe_request, monkeypatch)


def _assert_restart_reserves_plan(tenant, stripe, monkeypatch):
    subscriptions.select_plan(tenant, 'starter')
    contract = subscriptions._contract(tenant, 'platform')
    with subscriptions.connection(tenant) as db:
        db.execute("UPDATE billing_contracts SET subscription='sub_retired',status='canceled' WHERE ref=?", (contract['ref'],))
    competing_selection = []

    def tax():
        # This other request arrives while checkout is awaiting its tax API call.
        try:
            subscriptions.select_plan(tenant, 'scale')
        except ValueError as exc:
            competing_selection.append(str(exc))
        else:
            competing_selection.append('changed')
        return 'txr_test'

    monkeypatch.setattr(subscriptions, '_tax', tax)

    def response(method, path, data=None, **kwargs):
        if path == '/v1/subscriptions/sub_retired':
            return {'status': 'canceled', 'metadata': {'tenant': tenant, 'kind': 'platform',
                    'billing_ref': contract['ref']}, 'items': {'data': []}}
        if method == 'POST' and path == '/v1/checkout/sessions':
            return {'id': 'cs_replacement', 'url': 'https://checkout.stripe.com/c/pay/replacement',
                    'expires_at': int(time.time()) + 3600}
        raise AssertionError('Unexpected test provider operation')

    stripe.side_effect = response
    subscriptions.checkout(tenant, 'test@example.test', 'platform', 'https://example.test', plan_id='starter')
    assert competing_selection == ['cancel_pending_checkout_before_changing_plan']
    assert subscriptions.plan_state(tenant)['selected_plan'] == 'starter'
