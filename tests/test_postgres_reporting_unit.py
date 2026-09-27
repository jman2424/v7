"""Inventory authorization and cross-company report composition."""
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from flask import Flask, session
from werkzeug.exceptions import Forbidden

from retrieval.storage import Storage
from service import analytics_db, api_usage, session_store


@pytest.mark.parametrize('backend,expected', [('sqlite', 'CLINIC_MIXED'), ('postgres', 'Clinic_Mixed')])
def test_usage_preserves_postgres_document_key_case(monkeypatch, backend, expected):
    monkeypatch.setenv('V7_STORAGE_BACKEND', backend)
    recorded = []
    monkeypatch.setattr(api_usage, '_write_usage', lambda values: recorded.append(values))
    assert analytics_db._norm_tenant('Clinic_Mixed') == expected
    with api_usage.usage_context('Clinic_Mixed', 'web', 'v7'):
        api_usage._record({'model':'gpt-4o-mini', 'usage':{'prompt_tokens':1, 'completion_tokens':1}},
                          'gpt-4o-mini', 'planning', 'completed')
        api_usage.record_transcription({'usage':{'type':'duration', 'seconds':3}},
                                      'gpt-transcribe', 'completed')
    assert [row[1] for row in recorded] == [expected, expected]


def test_postgres_inventory_revalidates_admin_and_pages_keys(monkeypatch, tmp_path):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'postgres')
    calls = []
    keys = [f'T{i:04d}' for i in range(501)]
    monkeypatch.setattr('service.security.management_user',
                        lambda *, platform_only: calls.append(('authorize', platform_only)))

    class Database:
        def execute(self, sql, params):
            assert sql == 'SELECT tenant FROM v7_private.list_platform_tenant_keys(%s, %s, %s)'
            assert params[0] == session_store._digest('test-management-token')
            assert params[1] == 500
            calls.append(('page', params[2]))
            return SimpleNamespace(fetchall=lambda: [(key,) for key in keys[params[2]:params[2] + params[1]]])

    @contextmanager
    def connection(*, repeatable_read):
        assert repeatable_read is True
        assert calls == [('authorize', True)]
        yield Database()

    monkeypatch.setattr(session_store, 'postgres_connection', connection)
    app = Flask(__name__)
    app.secret_key = 'unit-test-only-secret'
    with app.test_request_context():
        session['management_token'] = 'test-management-token'
        assert Storage('ALPHA', base_dir=tmp_path).tenant_keys() == keys
    assert calls == [('authorize', True), ('page', 0), ('page', 500)]
    assert not list(tmp_path.iterdir())


def test_postgres_inventory_denies_before_opening_database(monkeypatch, tmp_path):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'postgres')
    def reject(*, platform_only):
        assert platform_only is True
        raise Forbidden()
    monkeypatch.setattr('service.security.management_user', reject)
    monkeypatch.setattr(session_store, 'postgres_connection',
                        lambda **kwargs: pytest.fail('Database opened before authorization'))
    with pytest.raises(Forbidden):
        Storage('ALPHA', base_dir=tmp_path).tenant_keys()


def test_platform_usage_combines_individually_scoped_reports(monkeypatch):
    monkeypatch.setenv('V7_STORAGE_BACKEND', 'postgres')
    opened = []
    costs = {'ALPHA': 1000, 'BETA': 2000}
    @contextmanager
    def connection(tenant, *, repeatable_read):
        assert repeatable_read is True
        opened.append(tenant)
        yield SimpleNamespace(tenant=tenant,
            execute=lambda sql, params: SimpleNamespace(fetchone=lambda: ('2026-09-01T00:00:00+00:00',)))
    monkeypatch.setattr(session_store, 'postgres_connection', connection)
    def rows(db, sql, values):
        assert 'v7_private.api_usage' in sql
        assert 'tenant = %s' in sql and values[1] == db.tenant
        base = {'calls': 1, 'failed_calls': 0, 'missing_usage_calls': 0, 'unpriced_calls': 0,
                'input_tokens': Decimal(10), 'cached_tokens': 0, 'cache_write_tokens': 0,
                'output_tokens': Decimal(2), 'audio_seconds': 0,
                'cost_nano_usd': Decimal(costs[db.tenant])}
        if 'GROUP BY tenant' in sql:
            return [{**base, 'tenant': db.tenant, 'mode': 'v7', 'model': 'known-model',
                     'requested_model': 'known-model', 'channel': 'web', 'purpose': 'planning'}]
        if 'GROUP BY mode' in sql:
            return [{**base, 'mode': 'v7'}]
        return [base]
    monkeypatch.setattr('service.analytics_db._pg_rows', rows)
    app = Flask(__name__)
    app.container = SimpleNamespace(storage=SimpleNamespace(tenant_keys=lambda: ['ALPHA', 'BETA']))
    with app.app_context():
        report = api_usage.summary(None, 30)
    assert opened == ['ALPHA', 'BETA']
    assert report['totals']['calls'] == 2
    assert report['totals']['total_tokens'] == 24
    assert report['totals']['estimated_cost_usd'] == pytest.approx(0.000003)
    assert report['mode_totals'][0]['calls'] == 2
    assert [row['tenant'] for row in report['breakdown']] == ['BETA', 'ALPHA']
    assert isinstance(report['breakdown'][0]['input_tokens'], int)
