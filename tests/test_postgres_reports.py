"""Native PostgreSQL reporting and bounded platform inventory security."""
from datetime import datetime, timedelta, timezone
import json
import secrets
import time
from types import SimpleNamespace

import pytest
from flask import Flask, session
from werkzeug.security import generate_password_hash
from werkzeug.exceptions import Forbidden

from retrieval.storage import Storage
from service import analytics_db, api_usage, session_store
from service.product_metrics import record_inventory, record_sale, void_sale
from service.security import _revision
from service.statistics import get_statistics
from service.tenant_service import TenantService


def platform_context(runtime):
    """Use a real revocable management session and credential revision."""
    from psycopg.types.json import Jsonb
    email = 'operator-' + secrets.token_hex(4) + '@example.test'
    runtime['admin'].execute('INSERT INTO v7_private.operator_accounts(email,payload) VALUES(%s,%s)',
                            (email, Jsonb({'email': email, 'role': 'platform_admin',
                                          'password_hash': generate_password_hash('Test-only-password-42!')})))
    app = Flask(__name__)
    app.secret_key = 'native-test-only-secret'
    app.container = SimpleNamespace(storage=Storage(runtime['tenant']))
    context = app.test_request_context()
    context.push()
    identity = {'id': email, 'email': email, 'roles': ['platform_admin'], 'tenant': runtime['tenant']}
    session['user'] = identity
    session['management_token'] = session_store.create(identity, _revision(identity))
    return context


def test_native_statistics_products_offers_and_legacy_metadata(pg_runtime):
    runtime = pg_runtime
    tenant, other, admin = runtime['tenant'], runtime['other'], runtime['admin']
    now = datetime.now(timezone.utc)
    def event(offset, kind, message_id, *, company=tenant, channel='web', intent='faq', meta=None):
        admin.execute('INSERT INTO v7_private.events '
                      '(ts_utc,tenant,channel,session_id,event_type,message_id,intent,meta_json) '
                      'VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                      ((now-timedelta(seconds=offset)).isoformat(), company, channel, 'customer',
                       kind, message_id, intent, json.dumps(meta or {}) if not isinstance(meta, str) else meta))
    event(100, 'msg_in', 'q1')
    event(96, 'msg_out', 'q1:reply', intent='search_product', meta={'products': ['SKU', 'removed', 4]})
    event(90, 'msg_in', 'q2', channel='whatsapp')
    event(85, 'msg_out', 'q2:out', channel='whatsapp', meta={'fallback': True})
    event(70, 'msg_out', 'deal', intent='offers', meta={'offers': ['deal1', 5]})
    event(50, 'msg_out', 'legacy', meta='invalid legacy json')
    event(40, 'msg_out', 'other', company=other)
    catalog = {'categories': [{'items': [{'sku': 'SKU', 'name': 'Test product', 'stock_quantity': 3}]}]}
    record_inventory(tenant, {}, catalog)
    payload = {'id': 'native-sale-reference-0001', 'sku': 'SKU', 'quantity': 2, 'amount_gbp': '19.99',
               'occurred_utc': (now-timedelta(hours=1)).isoformat(), 'channel': 'web'}
    assert record_sale(tenant, payload, catalog)['duplicate'] is False
    assert record_sale(tenant, payload, catalog)['duplicate'] is True
    report = get_statistics(tenant=tenant, days=1, now=datetime.now(timezone.utc), catalog=catalog,
                            offers=[{'id': 'deal1', 'title': 'Test deal', 'active': True}])
    assert report['current']['inbound'] == 2 and report['current']['outbound'] == 4
    assert report['current']['fallbacks'] == 1
    assert report['replies']['total']['replied'] == 2
    assert report['replies']['total']['answered'] == 1
    assert report['replies']['total']['response_seconds'] == pytest.approx(9)
    products = {row['sku']: row for row in report['commerce']['products']}
    assert products['SKU']['interest'] == 1
    assert products['SKU']['units'] == 2 and products['SKU']['amount_pence'] == 1999
    assert products['removed']['archived'] is True
    assert '4' not in products
    assert len(report['commerce']['inventory']) == 1
    assert report['offers']['offer_replies'] == 1
    assert report['offers']['items'][0]['replies'] == 1
    assert isinstance(report['commerce']['sales_daily'][0]['amount_pence'], int)
    json.dumps(report)  # Native numeric aggregates remain serializable numbers.


def test_native_inventory_requires_live_admin_session_without_broad_rls(pg_runtime):
    runtime = pg_runtime
    context = platform_context(runtime)
    try:
        keys = Storage(runtime['tenant']).tenant_keys()
        assert runtime['tenant'] in keys and runtime['other'] in keys
        token_hash = session_store._digest(session['management_token'])
    finally:
        context.pop()
    with session_store.postgres_connection() as db:
        assert db.execute('SELECT tenant FROM v7_private.tenants').fetchall() == []
        assert db.execute('SELECT tenant FROM v7_private.list_platform_tenant_keys(%s,1,0)',
                          (token_hash,)).fetchone() is not None
    for roles, expires in [(['business_owner'], time.time()+600), (['platform_admin'], time.time()-1)]:
        rejected = secrets.token_hex(32)
        runtime['admin'].execute('INSERT INTO v7_private.management_sessions VALUES(%s,%s,%s,%s)',
                                 (rejected, json.dumps({'roles': roles}), 'test-revision', expires))
        with pytest.raises(RuntimeError, match='Security database operation failed'):
            with session_store.postgres_connection() as db:
                db.execute('SELECT tenant FROM v7_private.list_platform_tenant_keys(%s,500,0)', (rejected,))
    with pytest.raises(RuntimeError, match='Security database operation failed'):
        with session_store.postgres_connection() as db:
            db.execute('SELECT tenant FROM v7_private.list_platform_tenant_keys(%s,501,0)', (token_hash,))


def test_native_platform_usage_sums_scoped_tenants(pg_runtime):
    runtime = pg_runtime
    context = platform_context(runtime)
    try:
        before = api_usage.summary(None, 30)['totals']['calls']
        for tenant, mode in [(runtime['tenant'], 'v7'), (runtime['tenant'], 'v7'), (runtime['other'], 'v6')]:
            with api_usage.usage_context(tenant, 'web', mode):
                api_usage._record({'model': 'gpt-4o-mini', 'usage': {'prompt_tokens': 10, 'completion_tokens': 2}},
                                  'gpt-4o-mini', 'planning', 'completed')
        report = api_usage.summary(None, 30)
        assert report['totals']['calls'] == before + 3
        own = api_usage.summary(runtime['tenant'], 30)
        assert own['totals']['calls'] == 2 and own['totals']['total_tokens'] == 24
        assert own['totals']['estimated_cost_usd'] == pytest.approx(0.0000054)
        json.dumps(report)
    finally:
        context.pop()


def test_native_owner_inventory_reads_only_assigned_workspaces(pg_runtime):
    from service.account_service import AccountService
    runtime = pg_runtime
    storage = Storage(runtime['tenant'])
    account = AccountService(storage).create_account(runtime['tenant'], {
        'email': 'owner-' + secrets.token_hex(4) + '@example.test',
        'password': 'Native-test-password-42!', 'roles': ['business_owner'],
    })
    app = Flask(__name__)
    app.secret_key = 'native-owner-test-only-secret'
    app.container = SimpleNamespace(storage=storage)
    with app.test_request_context():
        identity = {key: account[key] for key in ('id', 'email', 'roles')}
        identity['tenant'] = runtime['tenant']
        session['user'] = identity
        session['management_token'] = session_store.create(identity, _revision(identity))
        assert [row['key'] for row in TenantService(storage).list_tenants()] == [runtime['tenant']]
        with pytest.raises(Forbidden):
            storage.tenant_keys()


def test_native_mixed_case_tenant_events_commerce_and_usage(pg_runtime, monkeypatch):
    tenant = 'Clinic_' + secrets.token_hex(5)
    storage = Storage(pg_runtime['tenant'])
    TenantService(storage).create_tenant(tenant, 'Mixed case test company')
    now = datetime.now(timezone.utc)
    analytics_db.log_message(tenant=tenant, channel='web', session_id='customer',
        direction='inbound', text='Test enquiry', message_id='mixed-q')
    analytics_db._insert_event(tenant=tenant, channel='web', session_id='customer',
        event_type='msg_out', intent='offers', message_id='mixed-q:reply',
        meta_json=json.dumps({'offers':['deal1'], 'products':['SKU']}))
    analytics_db.upsert_lead(tenant=tenant, lead_id='mixed-lead', name='Test customer')
    assert analytics_db.update_lead_status(tenant=tenant, lead_id='mixed-lead', status='Qualified')
    with api_usage.usage_context(tenant, 'web', 'v7'):
        api_usage._record({'model':'gpt-4o-mini', 'usage':{'prompt_tokens':10, 'completion_tokens':2}},
                          'gpt-4o-mini', 'planning', 'completed')
        api_usage.record_transcription({'usage':{'type':'duration', 'seconds':3}},
                                      'gpt-transcribe', 'completed')
    catalog = {'categories':[{'items':[{'sku':'SKU', 'name':'Test product', 'stock_quantity':3}]}]}
    record_inventory(tenant, {}, catalog)
    sale = {'id':'mixed-sale-reference-0001', 'sku':'SKU', 'quantity':1, 'amount_gbp':'9.99',
            'occurred_utc':(now-timedelta(minutes=1)).isoformat(), 'channel':'web'}
    assert not record_sale(tenant, sale, catalog)['duplicate']
    report = get_statistics(tenant=tenant, days=1, catalog=catalog,
                           offers=[{'id':'deal1', 'title':'Test deal', 'active':True}])
    assert report['current']['inbound'] == 1 and report['current']['outbound'] == 1
    assert report['pipeline']['Qualified'] == 1
    assert report['replies']['total']['replied'] == 1
    assert report['commerce']['products'][0]['interest'] == 1
    assert report['commerce']['products'][0]['units'] == 1
    assert len(report['commerce']['inventory']) == 1
    assert report['offers']['items'][0]['replies'] == 1
    assert api_usage.summary(tenant, 30)['totals']['calls'] == 2
    assert api_usage.summary(tenant, 30)['totals']['audio_seconds'] == 3
    from service import subscriptions
    from service.analytics_service import AnalyticsService
    monkeypatch.setattr('service.usage_currency.gbp_rate',
                        lambda: {'rate':0.75, 'rate_date':'2026-09-27'})
    assert subscriptions.usage_months(tenant)[0][0]['calls'] == 2
    assert 'Test customer' in AnalyticsService(SimpleNamespace()).leads_csv(tenant=tenant)
    assert analytics_db.get_kpis(tenant=tenant.upper())['inbound'] == 0
    assert api_usage.summary(tenant.upper(), 30)['totals']['calls'] == 0
    assert void_sale(tenant, sale['id']) is True
    assert get_statistics(tenant=tenant, days=1, catalog=catalog)['commerce']['products'][0]['units'] == 0
