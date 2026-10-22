"""Prepaid financial accounting tests use synthetic identities and no provider calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import pytest

from service import analytics_db, usage_currency, usage_wallet as wallet


@pytest.fixture
def ledger(tmp_path,monkeypatch):
    monkeypatch.setenv("SECURITY_DB_PATH",str(tmp_path/"security.db"))
    monkeypatch.setattr(analytics_db,"DB_PATH",str(tmp_path/"analytics.db"))
    monkeypatch.setenv("V7_USAGE_MARKUP_PERCENT","0")
    rate = {"rate":1,"date":date.today().isoformat(),"stale":False,"source":"synthetic"}
    monkeypatch.setattr(usage_currency,"gbp_rate",lambda:dict(rate))
    monkeypatch.setattr(usage_currency,"cached_gbp_rate",lambda:dict(rate))
    return rate


def credit(tenant="ALPHA",reference="order-1",payment_id="pi_synthetic",pence=100,**kwargs):
    return wallet.apply_payment(tenant,reference,payment_id,pence,pence*120//100,
        invoice_id="in_synthetic",receipt_url="https://invoice.stripe.com/synthetic",**kwargs)


def test_credit_payment_is_idempotent_and_vat_is_not_credit(ledger):
    credit()
    credit()
    result = wallet.report("ALPHA")
    assert result["balance_pence"]==result["available_pence"]==100
    assert result["total"]==1
    assert result["transactions"][0]["kind"]=="topup"
    assert result["transactions"][0]["metadata"]=={"paid_pence":120,"credit_pence":100}
    assert wallet.report("BETA")["balance_pence"]==0


def test_operator_waiver_releases_only_reservation_and_keeps_provider_cost_unknown(ledger):
    credit()
    held = wallet.reserve_usage("ALPHA",100_000_000,{"model":"gpt-4o-mini","channel":"web","prompt":"private"})
    wallet.settle_usage(held,None)
    assert wallet.report("ALPHA")["paused"]
    reviews = wallet.unconfirmed_usage("ALPHA")
    assert reviews[0]["reference"]==held.ref and "private" not in str(reviews)
    assert wallet.unconfirmed_usage("BETA")==[]
    reason = "Setup request timed out; platform accepts provider cost"
    assert not wallet.waive_unconfirmed_usage("ALPHA",held.ref,reason,"operator")["duplicate"]
    assert wallet.waive_unconfirmed_usage("ALPHA",held.ref,reason,"operator")["duplicate"]
    result = wallet.report("ALPHA")
    assert result["balance_pence"]==result["available_pence"]==100
    assert result["reserved_pence"]==result["spent_pence"]==0
    assert not result["paused"] and not result["reconciliation_hold"]
    entry = next(row for row in result["transactions"] if row["kind"]=='usage_waived')
    assert entry["balance_delta_pence"]==0 and entry["reserved_delta_pence"]==-10
    assert entry["reason"]==reason and entry["usage"]["provider_cost_status"]=='unknown'
    with wallet._connection("ALPHA") as db:
        row = db.execute("SELECT * FROM usage_wallet_reservations WHERE ref=?",(held.ref,)).fetchone()
        assert row["cost_nano_usd"] is None and row["charged_nano_gbp"]==0
        assert db.execute("SELECT actor FROM usage_wallet_entries WHERE kind='usage_waived'").fetchone()["actor"]=='operator'
    # Late settlement and duplicate delivery cannot charge a waived client request.
    wallet.settle_usage(held,10_000_000)
    assert wallet.report("ALPHA")["balance_pence"]==100
    with pytest.raises(ValueError,match='usage_review_mismatch'):
        wallet.waive_unconfirmed_usage("ALPHA",held.ref,"Different reason","operator")


@pytest.mark.parametrize("remaining",["unknown","overrun","dispute","debt"])
def test_waiver_preserves_other_financial_holds(ledger,remaining):
    credit(pence=200)
    held = wallet.reserve_usage("ALPHA",100_000_000)
    other = wallet.reserve_usage("ALPHA",100_000_000)
    wallet.settle_usage(held,None)
    wallet.settle_usage(other,None if remaining=='unknown' else 200_000_000 if remaining=='overrun' else 0)
    if remaining=='dispute':
        wallet.reconcile_payment("ALPHA","pi_synthetic",0,True,"dispute-event")
    elif remaining=='debt':
        with wallet._connection("ALPHA",write=True) as db:
            db.execute("UPDATE usage_wallets SET debt_nano_gbp=1 WHERE tenant='ALPHA'")
    wallet.waive_unconfirmed_usage("ALPHA",held.ref,"Setup timeout","operator")
    assert wallet.report("ALPHA")["paused"]
    with pytest.raises(wallet.UsagePaused):
        wallet.reserve_usage("ALPHA",1)


def test_waiver_rejects_foreign_active_known_and_invalid_requests(ledger):
    credit()
    held = wallet.reserve_usage("ALPHA",100_000_000)
    for tenant in ("ALPHA","BETA"):
        with pytest.raises(ValueError,match='usage_review_not_unconfirmed'):
            wallet.waive_unconfirmed_usage(tenant,held.ref,"Review","operator")
    wallet.settle_usage(held,200_000_000)
    with pytest.raises(ValueError,match='usage_review_not_unconfirmed'):
        wallet.waive_unconfirmed_usage("ALPHA",held.ref,"Known overrun","operator")
    with pytest.raises(ValueError):
        wallet.waive_unconfirmed_usage("ALPHA",held.ref,"   ","operator")
    assert wallet.report("ALPHA")["reserved_pence"]==10


def test_parallel_credit_and_payment_identity_cannot_duplicate(ledger):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _:credit(),range(16)))
    assert wallet.report("ALPHA")["balance_pence"]==100
    with pytest.raises(ValueError,match="payment_credit_mismatch"):
        credit(pence=200)
    with pytest.raises((sqlite3.IntegrityError,RuntimeError)):
        credit("BETA","order-other")
    assert wallet.report("BETA")["balance_pence"]==0


def test_atomic_reservations_stop_parallel_overspend(ledger):
    credit()

    def reserve(_):
        try:
            return wallet.reserve_usage("ALPHA",500_000_000)
        except wallet.UsagePaused:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        held = [row for row in pool.map(reserve,range(20)) if row]
    assert len(held)==2
    assert wallet.report("ALPHA")["reserved_pence"]==100
    for reservation in held:
        wallet.settle_usage(reservation,100_000_000,{"model":"gpt-4o-mini","input_tokens":10})
        wallet.settle_usage(reservation,100_000_000)
    result = wallet.report("ALPHA")
    assert result["balance_pence"]==80 and result["reserved_pence"]==0 and result["spent_pence"]==20


def test_fx_markup_and_metadata_are_frozen_and_secret_fields_are_dropped(ledger,monkeypatch):
    credit(pence=1000)
    ledger["rate"] = .8
    monkeypatch.setenv("V7_USAGE_MARKUP_PERCENT","25")
    held = wallet.reserve_usage("ALPHA",500_000_000,{"model":"gpt-4o-mini","channel":"whatsapp",
        "price_version":"test-v1","prompt":"private chat","api_key":"synthetic-secret",
        "rate_snapshot":{"input":150,"cached":75,"output":600}})
    ledger["rate"] = .5
    monkeypatch.setenv("V7_USAGE_MARKUP_PERCENT","100")
    forged = wallet.Reservation(held.tenant,held.ref,Decimal(9),Decimal(200))
    wallet.settle_usage(forged,100_000_000,{"output_tokens":20,"headers":"private headers"})
    result = wallet.report("ALPHA")
    assert result["spent_pence"]==10
    usage = next(row["usage"] for row in result["transactions"] if row["kind"]=="usage")
    assert usage["fx_rate"]=="0.8" and usage["markup_percent"]=="25"
    assert usage["provider_cost_usd"]==.1 and usage["rate_snapshot"]["cached"]==75
    assert "private chat" not in str(result) and "synthetic-secret" not in str(result) and "private headers" not in str(result)


@pytest.mark.parametrize("cost",[None,-1,True,float("nan")])
def test_unknown_cost_keeps_reservation_and_cannot_be_reset_by_topup(ledger,cost):
    credit()
    held = wallet.reserve_usage("ALPHA",500_000_000)
    wallet.settle_usage(held,cost)
    wallet.settle_usage(held,cost)
    credit(reference="order-2",payment_id="pi_other")
    result = wallet.report("ALPHA")
    assert result["reserved_pence"]==50 and result["unknown_reservations"]==1
    assert result["reconciliation_hold"] and result["paused"]
    with pytest.raises(wallet.UsagePaused,match="financial_review_required"):
        wallet.reserve_usage("ALPHA",1)


def test_overrun_is_held_for_reconciliation_without_negative_balance(ledger):
    credit()
    held = wallet.reserve_usage("ALPHA",100_000_000)
    wallet.settle_usage(held,200_000_000)
    result = wallet.report("ALPHA")
    assert result["balance_pence"]==100 and result["reserved_pence"]==10
    assert result["spent_pence"]==0 and result["reconciliation_hold"]
    wallet.settle_usage(held,None)
    wallet.settle_usage(held,200_000_000)
    assert wallet.report("ALPHA")["reserved_pence"]==10
    wallet.settle_usage(held,50_000_000)
    assert wallet.report("ALPHA")["reconciliation_hold"] is False
    assert wallet.report("ALPHA")["spent_pence"]==5


def test_stale_crashed_reservation_keeps_credit_and_late_verified_usage_settles_once(ledger,monkeypatch):
    credit()
    with monkeypatch.context() as expired:
        created = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        expired.setattr(wallet,"_now",lambda:created)
        held = wallet.reserve_usage("ALPHA",100_000_000,{
            "price_version":"test-v1","rate_snapshot":{"input":150,"cached":75,"output":600}})
    report = wallet.report("ALPHA")
    assert report["paused"] and report["unknown_reservations"]==1
    assert report["balance_pence"]==100 and report["reserved_pence"]==10
    with wallet._connection("ALPHA") as db:
        assert db.execute("SELECT status FROM usage_wallet_reservations WHERE ref=?",(held.ref,)).fetchone()[0]=="pending"
    with pytest.raises(wallet.UsagePaused,match="financial_review_required"):
        wallet.reserve_usage("ALPHA",1)
    report = wallet.report("ALPHA")
    unknown = next(row for row in report["transactions"] if row["kind"]=="usage_unknown")
    assert unknown["usage"]["rate_snapshot"]["input"]==150
    assert unknown["usage"]["fx_rate"]=="1"
    assert report["reconciliation_hold"] and report["reserved_pence"]==10
    wallet.settle_usage(held,50_000_000)
    wallet.settle_usage(held,50_000_000)
    recovered = wallet.report("ALPHA")
    assert recovered["balance_pence"]==95 and recovered["reserved_pence"]==0
    assert recovered["spent_pence"]==5 and recovered["unknown_reservations"]==0
    assert recovered["paused"] is False and recovered["reconciliation_hold"] is False


@pytest.mark.parametrize("rate",[None,{"rate":1,"stale":True},{"rate":float("nan")},{"rate":-1}])
def test_missing_or_stale_fx_blocks_before_reservation(ledger,monkeypatch,rate):
    credit()
    monkeypatch.setattr(usage_currency,"gbp_rate",lambda:rate)
    with pytest.raises(wallet.UsagePaused,match="pricing_unavailable"):
        wallet.reserve_usage("ALPHA",100)
    assert wallet.report("ALPHA")["reserved_pence"]==0


@pytest.mark.parametrize("markup",["nan","-1","201","unpriced"])
def test_invalid_markup_fails_closed(ledger,monkeypatch,markup):
    credit()
    monkeypatch.setenv("V7_USAGE_MARKUP_PERCENT",markup)
    with pytest.raises(wallet.UsagePaused,match="pricing_unavailable"):
        wallet.reserve_usage("ALPHA",100)


def test_partial_and_full_refund_are_cumulative_and_not_replayed(ledger):
    credit()
    wallet.reconcile_payment("ALPHA","pi_synthetic",60,event_id="evt_partial")
    wallet.reconcile_payment("ALPHA","pi_synthetic",60,event_id="evt_duplicate")
    assert wallet.report("ALPHA")["balance_pence"]==50
    wallet.reconcile_payment("ALPHA","pi_synthetic",120)
    wallet.reconcile_payment("ALPHA","pi_synthetic",60)  # stale snapshot cannot undo a refund
    result = wallet.report("ALPHA")
    assert result["balance_pence"]==0 and result["debt_pence"]==0 and result["total"]==3


def test_initial_refunded_credit_is_never_available_to_spend(ledger):
    credit(refunded_pence=120)
    result = wallet.report("ALPHA")
    assert result["balance_pence"]==0 and result["available_pence"]==0
    with pytest.raises(wallet.UsagePaused):
        wallet.reserve_usage("ALPHA",1)


def test_refund_while_reserved_conserves_balance_and_records_spent_debt(ledger):
    credit()
    held = wallet.reserve_usage("ALPHA",1_000_000_000)
    wallet.reconcile_payment("ALPHA","pi_synthetic",120)
    result = wallet.report("ALPHA")
    assert result["balance_pence"]==result["reserved_pence"]==100 and result["debt_pence"]==100
    wallet.settle_usage(held,200_000_000)
    result = wallet.report("ALPHA")
    assert result["balance_pence"]==0 and result["reserved_pence"]==0 and result["debt_pence"]==20
    credit(reference="order-2",payment_id="pi_second")
    result = wallet.report("ALPHA")
    assert result["debt_pence"]==0 and result["balance_pence"]==80


def test_dispute_reversal_and_confirmed_restoration_do_not_duplicate_credit(ledger):
    credit(disputed=True,dispute_states={"dp_synthetic":"open"})
    assert wallet.report("ALPHA")["balance_pence"]==0
    assert wallet.report("ALPHA")["paused"]
    wallet.reconcile_payment("ALPHA","pi_synthetic",0,disputed=False,dispute_states={"dp_synthetic":"won"})
    wallet.reconcile_payment("ALPHA","pi_synthetic",0,disputed=False,dispute_states={"dp_synthetic":"won"})
    assert wallet.report("ALPHA")["balance_pence"]==100


def test_stale_dispute_snapshots_never_restore_or_regress_terminal_proof(ledger):
    credit()
    wallet.reconcile_payment("ALPHA","pi_synthetic",0,disputed=True,dispute_states={"dp_synthetic":"open"})
    # A canonical checkout snapshot retrieved before the dispute was opened
    # can arrive later. Replay it through both grant and reconciliation paths.
    credit(disputed=False,dispute_states={})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _:wallet.reconcile_payment("ALPHA","pi_synthetic",0,
            disputed=False,dispute_states={}),range(16)))
    assert wallet.report("ALPHA")["balance_pence"]==0
    assert wallet.report("ALPHA")["paused"] is True
    with pytest.raises(wallet.UsagePaused,match="financial_review_required"):
        wallet.reserve_usage("ALPHA",1)
    wallet.reconcile_payment("ALPHA","pi_synthetic",0,dispute_states={"dp_synthetic":"won"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _:wallet.reconcile_payment("ALPHA","pi_synthetic",0,
            disputed=True,dispute_states={"dp_synthetic":"open"}),range(16)))
    assert wallet.report("ALPHA")["balance_pence"]==100
    assert wallet.report("ALPHA")["paused"] is False
    with wallet._connection("ALPHA") as db:
        states = db.execute("SELECT dispute_states_json FROM usage_wallet_payments WHERE tenant=?",("ALPHA",)).fetchone()[0]
    assert states == '{"dp_synthetic": "won"}'


def test_lost_disputes_keep_reversal_but_allow_new_credit_and_unidentified_proof_holds(ledger):
    credit(disputed=True,dispute_states={"dp_synthetic":"lost"})
    wallet.reconcile_payment("ALPHA","pi_synthetic",0,dispute_states={"dp_synthetic":"won"})
    assert wallet.report("ALPHA")["paused"]
    credit(reference="order-after-loss",payment_id="pi_after_loss")
    assert wallet.report("ALPHA")["balance_pence"]==100
    assert wallet.report("ALPHA")["paused"] is False
    wallet.reserve_usage("ALPHA",1)
    with wallet._connection("ALPHA") as db:
        old = db.execute("SELECT reversed_nano_gbp,dispute_open FROM usage_wallet_payments WHERE payment_id=?",("pi_synthetic",)).fetchone()
    assert old["reversed_nano_gbp"]==100*wallet.NANO_PER_PENNY and old["dispute_open"]==0
    credit("BETA","order-beta","pi_beta",disputed=True)
    wallet.reconcile_payment("BETA","pi_beta",0,disputed=False,dispute_states={})
    assert wallet.report("BETA")["paused"]


def test_adjustments_are_bounded_audited_idempotent_and_do_not_release_holds(ledger):
    with pytest.raises(wallet.UsagePaused,match="insufficient_credit"):
        wallet.reserve_usage("ALPHA",1)
    wallet.adjust("ALPHA",100,"Support correction","operator-synthetic","request-1")
    wallet.adjust("ALPHA",100,"Support correction","operator-synthetic","request-1")
    assert wallet.report("ALPHA")["balance_pence"]==100
    assert wallet.report("ALPHA")["paused"] is False
    with pytest.raises(ValueError,match="adjustment_request_mismatch"):
        wallet.adjust("ALPHA",200,"Support correction","operator-synthetic","request-1")
    held = wallet.reserve_usage("ALPHA",500_000_000)
    with pytest.raises(ValueError,match="adjustment_exceeds_available_credit"):
        wallet.adjust("ALPHA",-100,"Remove mistaken credit","operator-synthetic","request-2")
    wallet.settle_usage(held,None)
    wallet.adjust("ALPHA",100,"Support correction","operator-synthetic","request-3")
    assert wallet.report("ALPHA")["reconciliation_hold"]


def test_history_is_paginated_private_and_ledger_cannot_be_erased(ledger):
    credit()
    held = wallet.reserve_usage("ALPHA",100_000_000)
    wallet.settle_usage(held,1)
    result = wallet.report("ALPHA",offset=1,limit=1)
    assert result["total"]==3 and len(result["transactions"])==1 and result["has_next"]
    hidden = wallet.report("ALPHA",include_costs=False)
    assert not any("pence" in key or "nano" in key for key in hidden)
    assert "transactions" not in hidden
    with pytest.raises(sqlite3.IntegrityError,match="immutable_wallet_ledger"), wallet._connection("ALPHA",write=True) as db:
        db.execute("DELETE FROM usage_wallet_entries WHERE tenant=?",("ALPHA",))
    assert wallet.report("ALPHA")["total"]==3


def test_operator_email_stays_in_internal_audit_and_is_redacted_from_company_report(ledger):
    email = "private-operator@example.test"
    wallet.adjust("ALPHA",100,"Support correction",email,"request-private")
    result = wallet.report("ALPHA")
    assert email not in str(result)
    assert "actor" not in result["transactions"][0]
    with wallet._connection("ALPHA") as db:
        actor = db.execute("SELECT actor FROM usage_wallet_entries WHERE tenant=?",("ALPHA",)).fetchone()[0]
    assert actor == email


def test_native_wallet_rls_and_concurrent_reservations(pg_runtime,monkeypatch):
    monkeypatch.setenv("V7_USAGE_MARKUP_PERCENT","0")
    rate = {"rate":1,"date":date.today().isoformat(),"stale":False}
    monkeypatch.setattr(usage_currency,"gbp_rate",lambda:rate)
    monkeypatch.setattr(usage_currency,"cached_gbp_rate",lambda:rate)
    tenant,other = pg_runtime["tenant"],pg_runtime["other"]
    credit(tenant)
    credit(other,"order-beta","pi_beta")

    def reserve(_):
        try:
            return wallet.reserve_usage(tenant,500_000_000)
        except wallet.UsagePaused:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        held = [row for row in pool.map(reserve,range(8)) if row]
    assert len(held)==2
    with wallet._connection(tenant) as db:
        for table in ("usage_wallets","usage_wallet_payments","usage_wallet_reservations","usage_wallet_entries"):
            assert not db.execute("SELECT 1 FROM "+table+" WHERE tenant=?",(other,)).fetchone()
    assert wallet.report(other)["reserved_pence"]==0
    with pytest.raises(RuntimeError), wallet._connection(tenant,write=True) as db:
        db.execute("DELETE FROM usage_wallet_entries WHERE tenant=?",(tenant,))


@pytest.mark.parametrize("privilege",["UPDATE","DELETE"])
def test_native_startup_rejects_mutable_wallet_ledger(pg_runtime,privilege):
    from service.storage_readiness import validate_postgres_storage
    validate_postgres_storage(pg_runtime["tenant"])
    admin = pg_runtime["admin"]
    try:
        admin.execute("GRANT "+privilege+" ON v7_private.usage_wallet_entries TO v7_backend")
        with pytest.raises(RuntimeError,match="immutable"):
            validate_postgres_storage(pg_runtime["tenant"])
    finally:
        admin.execute("REVOKE "+privilege+" ON v7_private.usage_wallet_entries FROM v7_backend")
