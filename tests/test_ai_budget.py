"""Synthetic AI Budget projections/alerts retain the established wallet ledger."""
import sqlite3
import pytest

from service import ai_budget as budget, ai_budget_store as store, usage_wallet as wallet
from tests import test_usage_wallet

ledger = test_usage_wallet.ledger


def add(pence=1000, reference='funds-one'):
    return wallet.apply_payment('ALPHA',reference,'pi_'+reference.replace('-',''),pence,pence)


def spend(pence):
    ref = wallet.reserve_usage('ALPHA',pence*wallet.NANO_PER_PENNY)
    wallet.settle_usage(ref,pence*wallet.NANO_PER_PENNY)


def notices():
    with store.connection('ALPHA') as db:
        return [dict(row) for row in db.execute('SELECT * FROM ai_budget_notifications WHERE tenant=?',('ALPHA',))]


def test_customer_projection_has_new_packs_and_no_provider_details(ledger):
    add(2500)
    spend(1650)
    report = budget.customer_report('ALPHA')
    assert report['available_pence'] == 850
    assert report['added_pence'] == 2500 and report['used_pence'] == 1650
    assert [row['credit_pence'] for row in report['packs']] == [1000,2500,5000]
    encoded = str(report)
    for private in ('input_tokens','output_tokens','fx_rate','markup_percent','provider_cost','reservation_ref','payment_ref'):
        assert private not in encoded
    assert budget.customer_report('BETA')['available_pence'] == 0


def test_settled_threshold_crossings_notify_once_and_replenishment_rearms(ledger):
    add(200)
    assert not notices()  # Equal to £2 is not below £2.
    spend(10)
    assert len(notices()) == 1
    spend(5)
    assert len(notices()) == 1
    add(500,'funds-two')
    spend(500)
    assert len(notices()) == 2


def test_temporary_usage_ceiling_does_not_trigger_a_purchase_or_low_alert(ledger):
    add(500)
    ref = wallet.reserve_usage('ALPHA',400*wallet.NANO_PER_PENNY)
    assert wallet.report('ALPHA')['available_pence'] == 100
    assert not notices()
    wallet.settle_usage(ref,1*wallet.NANO_PER_PENNY)
    assert not notices()


def test_changed_threshold_rearms_once_and_email_choice_is_independent(ledger):
    add(400)
    budget.save_preferences('ALPHA',{'alert_threshold_pence':500,'email_alerts':True},'owner')
    assert len(notices()) == 1 and notices()[0]['email_enabled'] == 1
    budget.save_preferences('ALPHA',{'alert_threshold_pence':500,'email_alerts':True},'owner')
    assert len(notices()) == 1
    assert not store.settings('ALPHA')['recharge_enabled']
    budget.save_preferences('ALPHA',{'alerts_enabled':False},'owner')
    spend(390)
    assert len(notices()) == 1


@pytest.mark.parametrize('data', [None,[],{}, {'email_alerts':'yes'}, {'alert_threshold_pence':True},
    {'alert_threshold_pence':300}, {'recharge_enabled':True}, {'balance':999999}, {'initial_pack':'gbp_5'}])
def test_preferences_validate_json_server_side(ledger,data):
    with pytest.raises(budget.BudgetError):
        budget.save_preferences('ALPHA',data,'owner')


def test_budget_audit_is_append_only_and_does_not_reset_balance(ledger):
    add(1000)
    budget.save_preferences('ALPHA',{'email_alerts':True},'owner')
    with store.connection('ALPHA',write=True) as db:
        with pytest.raises(sqlite3.IntegrityError,match='immutable_budget_audit'):
            db.execute("UPDATE ai_budget_events SET actor='forged'")
    assert wallet.report('ALPHA')['balance_pence'] == 1000
    assert wallet.report('ALPHA')['total'] == 1
