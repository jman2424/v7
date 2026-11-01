"""Run on the existing verified-TLS disposable PostgreSQL CI fixture."""
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
import time
import pytest

from service import ai_budget as budget, ai_budget_store as store, ai_budget_payments as payments, usage_wallet, session_store


def seed(tenant,cap=2500):
    identifier=secrets.token_hex(24)
    with store.connection(tenant,write=True) as db:
        store.ensure_settings(db,tenant)
        db.execute("INSERT INTO ai_budget_authorisations(id,tenant,revision,request_id,actor,actor_revision,consent_terms,cap_pence,customer,payment_method,livemode,status,created,updated) VALUES (?,?,2,?,'{}','revision','test consent',?,'cus_test','pm_test',0,'active',?,?)",(identifier,tenant,secrets.token_hex(12),cap,time.time(),time.time()))
        db.execute('UPDATE ai_budget_settings SET authorisation=?,recharge_enabled=1,recharge_cap_pence=? WHERE tenant=?',(identifier,cap,tenant))
    return identifier


def test_native_budget_rls_immutable_audit_and_unchanged_wallet(pg_runtime):
    tenant,other=pg_runtime['tenant'],pg_runtime['other']
    usage_wallet.apply_payment(tenant,'native_budget','pi_nativebudget'+tenant,2500,2500)
    before=usage_wallet.report(tenant)
    budget.save_preferences(tenant,{'email_alerts':True},'owner')
    with session_store.postgres_connection(other) as db:
        assert db.execute('SELECT count(*) FROM ai_budget_settings WHERE tenant=%s',(tenant,)).fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM ai_budget_events WHERE tenant=%s',(tenant,)).fetchone()[0]==0
        for table in (*store.TENANT_TABLES,*store.PLATFORM_TABLES):
            assert db.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',('v7_private.'+table,)).fetchone()==(True,True)
            assert not db.execute('SELECT has_table_privilege(current_user,%s,\'TRUNCATE\')',('v7_private.'+table,)).fetchone()[0]
    with pytest.raises(RuntimeError):
        with session_store.postgres_connection(other) as db:
            db.execute('INSERT INTO ai_budget_settings(tenant,updated) VALUES(%s,0)',(tenant,))
    with pytest.raises(RuntimeError):
        with session_store.postgres_connection(tenant) as db:
            db.execute("UPDATE ai_budget_events SET actor='changed' WHERE tenant=%s",(tenant,))
    after=usage_wallet.report(tenant)
    assert before['balance_nano_gbp']==after['balance_nano_gbp']
    assert before['total']==after['total']


def test_native_concurrent_recharge_reservations_share_one_cap_slot(pg_runtime,monkeypatch):
    tenant,other=pg_runtime['tenant'],pg_runtime['other']
    seed(tenant)
    monkeypatch.setattr(payments,'_actor_valid',lambda row:True)
    monkeypatch.setattr(budget,'require_eligible',lambda tenant:None)
    with ThreadPoolExecutor(max_workers=6) as pool:
        refs=list(pool.map(lambda _:payments.reserve_recharge(tenant),range(12)))
    assert len(set(refs))==1 and refs[0]
    with store.connection(tenant) as db:
        assert store.monthly_reserved(db,tenant)==500
    with store.connection(other) as db:
        assert store.monthly_reserved(db,other)==0
    with session_store.postgres_connection(other) as db:
        assert not db.execute('SELECT reference FROM ai_budget_recharges WHERE reference=%s',(refs[0],)).fetchall()


def test_native_provider_configuration_requires_live_operator_session(pg_runtime):
    with pytest.raises(RuntimeError):
        with store.connection(pg_runtime['tenant'],write=True) as db:
            db.execute('INSERT INTO ai_provider_funding_settings VALUES(1,?,0)',(json.dumps({'financial_review_completed':True}),))
