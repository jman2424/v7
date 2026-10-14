"""Run only against an explicitly configured disposable native database."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from service import referrals, subscriptions


def test_referral_records_cannot_cross_native_tenant_boundary(pg_runtime):
    a,b=pg_runtime['tenant'],pg_runtime['other']
    referrals.report(a,'owner-a@example.test','https://example.test')
    referrals.report(b,'owner-b@example.test','https://example.test')
    with subscriptions.connection(a) as db:
        assert db.execute('SELECT COUNT(*) AS count FROM referral_codes').fetchone()['count']==1
        assert db.execute('SELECT code FROM referral_codes WHERE tenant=?',(b,)).fetchone() is None


def test_native_program_toggle_requires_a_live_platform_session(pg_runtime):
    import psycopg
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        referrals.set_program(pg_runtime['tenant'],False,'0'*64)


def test_native_concurrent_referral_spending_is_serialized(pg_runtime):
    a,b=pg_runtime['tenant'],pg_runtime['other']
    code=referrals.report(a,'owner-a@example.test','https://example.test')['code']
    referrals.claim(b,'owner-b@example.test',code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(lambda ref:referrals.reserve(b,'platform',ref),['first','second']))
    assert sum(row is not None for row in rows)==1
