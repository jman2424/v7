"""Tiered billing and resource checks through native restricted PostgreSQL."""
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from unittest.mock import Mock

import pytest

from retrieval.storage import Storage
from service import session_store, subscriptions
from service.account_service import AccountService
from service.business_core import empty_core


TABLES = ('billing_plan_state', 'billing_plan_choices', 'billing_plan_usage',
          'billing_plan_events', 'billing_plan_reservations')


@pytest.fixture
def stripe_plan_provider(pg_runtime, monkeypatch):
    monkeypatch.setenv('BILLING_PROVIDER', 'stripe')
    monkeypatch.setenv('STRIPE_API_KEY', 'native-test-placeholder')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'native-test-placeholder')
    monkeypatch.setenv('STRIPE_TAX_RATE_ID', 'txr_native')
    provider = Mock()
    provider.provider = 'stripe'
    provider.api_key = 'native-test-placeholder'
    provider.webhook_secret = 'native-test-placeholder'

    def request(method, path, data=None, **kwargs):
        if path == '/v1/tax_rates/txr_native':
            return {'active': True, 'inclusive': False, 'percentage': 20}
        if method == 'POST' and path == '/v1/checkout/sessions':
            return {'id': 'cs_' + secrets.token_hex(8), 'url': 'https://checkout.stripe.com/c/pay/native',
                    'expires_at': int(time.time()) + 3600}
        raise AssertionError('Unexpected provider operation')

    provider.stripe_request.side_effect = request
    monkeypatch.setattr(subscriptions, 'client', lambda: provider)
    return provider


def test_native_plan_tables_force_rls_and_hide_other_tenant(pg_runtime):
    tenant, other = pg_runtime['tenant'], pg_runtime['other']
    subscriptions.select_plan(tenant, 'starter')
    subscriptions.select_plan(other, 'scale')
    for key in (tenant, other):
        contract = subscriptions._contract(key, 'platform')
        with subscriptions.connection(key) as db:
            db.execute('INSERT INTO billing_plan_choices VALUES (?,?,?,?)',
                       (contract['ref'], key, 'platform', 'starter'))
            db.execute('INSERT INTO billing_plan_usage (tenant,month) VALUES (?,?)', (key, '2026-10'))
            db.execute('INSERT INTO billing_plan_events VALUES (?,?,?,?)',
                       (key, '2026-10', 'website_conversations', 'a' * 64))
            db.execute('INSERT INTO billing_plan_reservations VALUES (?,?,?,?)',
                       (key, '2026-10', 'test-reservation', 100))
    with session_store.postgres_connection(tenant) as db:
        restrictions = db.execute(
            'SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class '
            "WHERE relnamespace='v7_private'::regnamespace AND relname=ANY(%s)", (list(TABLES),),
        ).fetchall()
        assert {row[0] for row in restrictions} == set(TABLES)
        assert all(row[1] and row[2] for row in restrictions)
        for table in TABLES:
            assert db.execute(f'SELECT count(*) FROM v7_private.{table} WHERE tenant=%s', (other,)).fetchone()[0] == 0
            assert db.execute(f'SELECT count(*) FROM v7_private.{table} WHERE tenant=%s', (tenant,)).fetchone()[0] == 1
            assert not db.execute('SELECT has_table_privilege(current_user,%s,\'TRUNCATE\')',
                                  ('v7_private.' + table,)).fetchone()[0]
    with pytest.raises(RuntimeError, match='database operation failed'):
        with session_store.postgres_connection(tenant) as db:
            db.execute("INSERT INTO v7_private.billing_plan_state (tenant,selected_plan) VALUES(%s,'starter') "
                       'ON CONFLICT(tenant) DO UPDATE SET selected_plan=excluded.selected_plan', (other,))
    assert subscriptions.plan_state(other)['selected_plan'] == 'scale'


@pytest.mark.parametrize('plan_id,monthly,setup', [('starter', 9900, 14900),
                                                 ('business', 19900, 29900),
                                                 ('scale', 34900, 59900)])
@pytest.mark.parametrize('vat_registered', [False, True])
def test_native_checkout_binds_server_plan_prices_and_vat(pg_runtime, stripe_plan_provider, plan_id, monthly, setup, monkeypatch, vat_registered):
    monkeypatch.setenv('V7_VAT_REGISTERED', 'true' if vat_registered else 'false')
    tenant = pg_runtime['tenant']
    for kind, amount in [('platform', monthly), ('implementation', setup)]:
        result = subscriptions.checkout(tenant, 'native@example.test', kind, 'https://example.test', plan_id=plan_id)
        assert result['url'].startswith('https://checkout.stripe.com/')
        body = stripe_plan_provider.stripe_request.call_args.args[2]
        assert body['line_items[0][price_data][unit_amount]'] == amount
        assert body['line_items[0][price_data][currency]'] == 'gbp'
        assert body['line_items[0][price_data][tax_behavior]'] == 'exclusive'
        if vat_registered:
            assert body['line_items[0][tax_rates][0]'] == 'txr_native'
        else:
            assert 'line_items[0][tax_rates][0]' not in body
        assert body['metadata[plan_id]'] == plan_id
        with subscriptions.connection(tenant) as db:
            choice = db.execute('SELECT * FROM billing_plan_choices WHERE ref=?', (body['metadata[billing_ref]'],)).fetchone()
            assert choice['tenant'] == tenant and choice['kind'] == kind and choice['plan_id'] == plan_id
    assert subscriptions.plan_state(tenant)['active_plan'] is None
    assert subscriptions.plan_state(pg_runtime['other']) is None


def test_native_callback_cannot_claim_unbound_tier(pg_runtime, stripe_plan_provider):
    tenant = pg_runtime['tenant']
    subscriptions.checkout(tenant, 'native@example.test', 'platform', 'https://example.test', plan_id='starter')
    body = stripe_plan_provider.stripe_request.call_args.args[2]
    metadata = {'tenant': tenant, 'kind': 'platform', 'billing_ref': body['metadata[billing_ref]'], 'plan_id': 'scale'}
    stripe_plan_provider.stripe_request.side_effect = None
    stripe_plan_provider.stripe_request.return_value = {'id': 'sub_native', 'metadata': metadata,
        'customer': 'cus_native', 'status': 'active', 'items': {'data': [{'current_period_end': int(time.time()) + 3600}]}}
    with pytest.raises(ValueError, match='^unknown_billing_plan$'):
        subscriptions.sync_subscription('sub_native')
    assert subscriptions.plan_state(tenant)['active_plan'] is None
    metadata['plan_id'] = 'starter'
    subscriptions.sync_subscription('sub_native')
    assert subscriptions.plan_state(tenant)['active_plan'] == 'starter'
    assert subscriptions._contract(tenant, 'platform')['status'] == 'active'


def test_native_resource_writes_share_cap_transaction(pg_runtime):
    tenant = pg_runtime['tenant']
    storage = Storage(tenant)
    subscriptions.select_plan(tenant, 'starter')
    service = AccountService(storage)
    service.create_account(tenant, {'email': 'existing@example.test', 'password': 'Native-resource-test-password',
                                   'roles': ['business_staff']})
    start = Barrier(2)

    def create(index):
        start.wait(timeout=5)
        try:
            service.create_account(tenant, {'email': f'staff{index}@example.test',
                'password': 'Native-resource-test-password', 'roles': ['business_staff']})
            return 'saved'
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(create, [1, 2])) == ['saved', 'staff_account_limit_reached']
    assert len(service.list_accounts(tenant)) == 2
    core = empty_core()
    core['locations'] = [{'id': 'remote', 'name': 'Online service', 'type': 'remote_only',
                          'active': True, 'service_area': 'United Kingdom'}]
    storage.write_json(tenant, 'business_core.json', core)
    with pytest.raises(ValueError, match='^location_limit_reached$'):
        storage.write_json(tenant, 'branches.json', [{'id': 'branch', 'name': 'Branch',
                           'postcode': 'SW1A 1AA', 'lat': None, 'lon': None}])
    assert storage.read_json(tenant, 'branches.json') == []


def test_native_simultaneous_checkout_uses_one_immutable_generation(pg_runtime, stripe_plan_provider, monkeypatch):
    tenant = pg_runtime['tenant']
    subscriptions.select_plan(tenant, 'business')
    start = Barrier(2)
    provider_lock = Lock()
    generations = {}

    def tax():
        start.wait(timeout=10)
        return 'txr_native'

    def create(method, path, data=None, **kwargs):
        assert method == 'POST' and path == '/v1/checkout/sessions'
        key = kwargs['idempotency_key']
        with provider_lock:
            if key in generations:
                assert generations[key]['data'] == data
            else:
                generations[key] = {'data': data, 'result': {'id': 'cs_nativeone',
                    'url': 'https://checkout.stripe.com/c/pay/nativeone',
                    'expires_at': int(time.time()) + 3600}}
            return generations[key]['result']

    monkeypatch.setattr(subscriptions, '_tax', tax)
    stripe_plan_provider.stripe_request.side_effect = create
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: subscriptions.checkout(tenant, 'native@example.test',
                           'platform', 'https://example.test', plan_id='business'), range(2)))
    assert len(generations) == 1
    assert results == [{'url': 'https://checkout.stripe.com/c/pay/nativeone'}] * 2
    contract = subscriptions._contract(tenant, 'platform')
    assert contract['checkout'] == 'cs_nativeone'
    with subscriptions.connection(tenant) as db:
        choices = db.execute('SELECT plan_id FROM billing_plan_choices WHERE tenant=?', (tenant,)).fetchall()
    assert [row['plan_id'] for row in choices] == ['business']
