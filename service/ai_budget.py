"""Owner-controlled AI Budget preferences, threshold crossings and customer DTOs."""
from datetime import datetime, timezone
import json
import os
import time

from service import ai_budget_store as store, session_store, subscriptions, usage_wallet

RECHARGE_PENCE = 500
RECHARGE_THRESHOLD_PENCE = 200
CAPS = {2500, 5000, 10000}
ALERTS = {200, 500, 1000}
INITIAL_PACKS = {'', 'gbp_10', 'gbp_25', 'gbp_50'}


class BudgetError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def live_recharge_allowed():
    from service.usage_payments import _production
    if not _production():
        return True
    if os.getenv('V7_AUTO_RECHARGE_LIVE_ENABLED', 'false').lower()!='true':
        return False
    from service import ai_provider_funding
    try:
        policy=ai_provider_funding.settings()
        analysis=ai_provider_funding.break_even(policy,markup=usage_wallet.markup_percent(),vat_percent=subscriptions.vat_percent())
        return analysis.get('validated') is True and analysis.get('profitable') is True
    except (ValueError,usage_wallet.UsagePaused):
        return False


def require_eligible(tenant):
    from service import business_applications
    business_applications.require_eligible(tenant)
    from service.tenant_access import activation
    status = activation(tenant)
    if status.get('status') == 'platform_internal' or not status.get('active'):
        raise BudgetError('budget_active_business_required', 403)
    return status


def save_preferences(tenant, data, actor):
    fields = {'alerts_enabled','email_alerts','alert_threshold_pence','initial_pack'}
    if not isinstance(data, dict) or not data or set(data)-fields:
        raise BudgetError('invalid_budget_settings')
    for key in ('alerts_enabled','email_alerts'):
        if key in data and type(data[key]) is not bool:
            raise BudgetError('invalid_budget_settings')
    if 'alert_threshold_pence' in data and (type(data['alert_threshold_pence']) is not int or data['alert_threshold_pence'] not in ALERTS):
        raise BudgetError('invalid_budget_settings')
    if 'initial_pack' in data and (not isinstance(data['initial_pack'], str) or data['initial_pack'] not in INITIAL_PACKS):
        raise BudgetError('invalid_budget_settings')
    # Old SQLite/offline workspaces may not have made their first AI purchase.
    # Prepare the existing ledger schema before taking the settings write lock.
    usage_wallet.report(tenant,include_costs=False)
    with store.connection(tenant, write=True) as db:
        current = store.ensure_settings(db, tenant)
        changed = any(current[key] != value for key,value in data.items())
        if not changed:
            return
        reset = any(key in data and current[key] != data[key] for key in ('alerts_enabled','email_alerts','alert_threshold_pence'))
        merged={**current,**data}
        db.execute('UPDATE ai_budget_settings SET alerts_enabled=?,email_alerts=?,alert_threshold_pence=?,initial_pack=? WHERE tenant=?',
            (int(merged['alerts_enabled']),int(merged['email_alerts']),merged['alert_threshold_pence'],merged['initial_pack'],tenant))
        db.execute('UPDATE ai_budget_settings SET revision=revision+1,low_state=CASE WHEN ?=1 THEN 0 ELSE low_state END,alert_epoch=alert_epoch+?,updated=? WHERE tenant=?',
                   (int(reset),int(reset),time.time(),tenant))
        store.audit(db,tenant,'preferences_changed',actor,data)
        wallet = db.execute('SELECT * FROM usage_wallets WHERE tenant=?', (tenant,)).fetchone()
        if wallet:
            observe(db, tenant, dict(wallet))


def observe(db, tenant, wallet):
    """Called within the existing ledger transaction after settled changes.

    Temporary request ceilings never trigger purchases. Observe posted balance,
    not a conservative in-flight reservation, and block on disputed/unknown usage.
    """
    store.schema(db)
    # Use the same lock order everywhere: wallet writers already own their row;
    # budget workers never lock a wallet row while owning this settings lock.
    current = store.ensure_settings(db,tenant)
    balance = wallet['balance_nano_gbp']
    threshold = current['alert_threshold_pence'] * usage_wallet.NANO_PER_PENNY
    low = balance < threshold
    previous_known = current['observed_balance_nano'] is not None
    if current['alerts_enabled'] and low and not current['low_state'] and (previous_known or balance>0):
        epoch = current['alert_epoch']+1
        store.notify(db,tenant,'low_balance','low:'+str(epoch),
            {'balance_pence':balance//usage_wallet.NANO_PER_PENNY,'threshold_pence':current['alert_threshold_pence']}, email=bool(current['email_alerts']))
        db.execute('UPDATE ai_budget_settings SET alert_epoch=? WHERE tenant=?',(epoch,tenant))
    db.execute('UPDATE ai_budget_settings SET low_state=?,observed_balance_nano=?,updated=? WHERE tenant=?',
               (int(low and current['alerts_enabled']),balance,time.time(),tenant))


def _money(value):
    return max(0, int(value)) // usage_wallet.NANO_PER_PENNY


def pause_after_reversal(db,tenant,payment_id):
    """A refund must not immediately cause its replacement to be purchased."""
    store.schema(db)
    current=store.ensure_settings(db,tenant)
    active=db.execute("SELECT 1 FROM ai_budget_authorisations WHERE tenant=? AND status IN('active','pending') LIMIT 1",(tenant,)).fetchone()
    if not current['recharge_enabled'] and not active:
        return
    db.execute("UPDATE ai_budget_settings SET recharge_enabled=0,blocked_reason='refund_review',updated=? WHERE tenant=?",(time.time(),tenant))
    db.execute("UPDATE ai_budget_authorisations SET status='revoked',updated=? WHERE tenant=? AND status IN('active','pending')",(time.time(),tenant))
    store.audit(db,tenant,'recharge_paused_after_reversal','stripe_verifier',{'payment_id':payment_id})
    store.notify(db,tenant,'payment_review','reversal:'+payment_id,{},email=True)


def customer_report(tenant, *, page=1):
    if type(page) is not int or not 1<=page<=1000000:
        raise BudgetError('invalid_budget_page')
    # Ensure the established schema exists in disposable SQLite environments.
    raw = usage_wallet.report(tenant, offset=(page-1)*20, limit=20)
    from service import usage_payments
    now = datetime.now(timezone.utc)
    since = now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
    with store.connection(tenant) as db:
        current = store.settings(tenant,db)
        spent = int(db.execute("SELECT COALESCE(-SUM(balance_delta_nano_gbp),0) AS amount FROM usage_wallet_entries WHERE tenant=? AND kind='usage' AND created_utc>=?",(tenant,since)).fetchone()['amount'])
        added = int(db.execute("SELECT COALESCE(SUM(balance_delta_nano_gbp),0) AS amount FROM usage_wallet_entries WHERE tenant=? AND balance_delta_nano_gbp>0 AND kind IN('topup','adjustment')",(tenant,)).fetchone()['amount'])
        all_spent = int(db.execute("SELECT COALESCE(-SUM(balance_delta_nano_gbp),0) AS amount FROM usage_wallet_entries WHERE tenant=? AND kind='usage'",(tenant,)).fetchone()['amount'])
        monthly = int(db.execute("SELECT COALESCE(SUM(amount_pence),0) AS amount FROM ai_budget_recharges WHERE tenant=? AND month=? AND status='succeeded'",(tenant,store.month_key())).fetchone()['amount'])
        pending = store.monthly_reserved(db,tenant)-monthly
        notices = [dict(row) for row in db.execute('SELECT id,kind,payload,created,seen FROM ai_budget_notifications WHERE tenant=? ORDER BY created DESC,id DESC LIMIT 20',(tenant,))]
        attempts = [dict(row) for row in db.execute('SELECT status,amount_pence,created,failure_code FROM ai_budget_recharges WHERE tenant=? ORDER BY created DESC LIMIT 10',(tenant,))]
        filter_sql = "tenant=? AND kind IN('topup','usage','refund','refund_restored','adjustment','reversal','usage_waived')"
        total = db.execute('SELECT COUNT(*) AS total FROM usage_wallet_entries WHERE '+filter_sql,(tenant,)).fetchone()['total']
        history = [dict(row) for row in db.execute('SELECT kind,balance_delta_nano_gbp,created_utc,receipt_url FROM usage_wallet_entries WHERE '+filter_sql+' ORDER BY created_utc DESC,id DESC LIMIT 20 OFFSET ?',(tenant,(page-1)*20))]
    entries = []
    labels = {'topup':'Funds added','usage':'AI usage','refund':'Refund','refund_restored':'Refund reversed',
              'adjustment':'Balance adjustment','reversal':'Payment reversal','usage_waived':'Usage adjustment'}
    for item in history:
        if item['kind'] not in labels:
            continue
        nano = item.get('balance_delta_nano_gbp',0)
        entries.append({'label':labels[item['kind']], 'created':item['created_utc'],
            'amount_pence':abs(nano)//usage_wallet.NANO_PER_PENNY,'direction':'added' if nano>=0 else 'used',
            'less_than_penny':0<abs(nano)<usage_wallet.NANO_PER_PENNY,
            'receipt_url':item.get('receipt_url') or None})
    for notice in notices:
        notice['details'] = json.loads(notice.pop('payload'))
        notice['seen'] = bool(notice['seen'])
    from service.ai_provider_funding import health
    return {
        'currency':'GBP', 'available_pence':_money(raw.get('available_nano_gbp',0)),
        'balance_pence':_money(raw.get('balance_nano_gbp',0)), 'pending_usage_pence':_money(raw.get('reserved_nano_gbp',0)),
        'added_pence':_money(added), 'used_pence':_money(all_spent),
        'monthly_spent_pence':_money(spent), 'month':store.month_key(),
        'paused':raw['paused'], 'review_required':bool(raw.get('reconciliation_hold') or raw.get('debt_nano_gbp',0)
            or raw.get('unknown_reservations') or any(row.get('code')=='financial_review_required' for row in raw.get('alerts',[]))),
        'configured':usage_payments.payments_ready(), 'internal':subscriptions.internal_business(tenant),
        'processing_available':health(tenant,cached=True)['status'] not in {'funding_exhausted','usage_limit'},
        'packs':[next(row for row in usage_payments.packs() if row['id']==key) for key in ('gbp_10','gbp_25','gbp_50')],
        'transactions':entries,'page':page,'has_next':page*20<total,
        'automatic_recharge':{'enabled':bool(current['recharge_enabled']), 'amount_pence':500,
            'threshold_pence':200,'cap_pence':current['recharge_cap_pence'],'cap_choices':sorted(CAPS),
            'spent_this_month_pence':monthly,'pending_this_month_pence':pending,
            'blocked_reason':current['blocked_reason'],'live_available':live_recharge_allowed(),
            'attempts':attempts},
        'alerts':{'enabled':bool(current['alerts_enabled']),'email_enabled':bool(current['email_alerts']),
            'threshold_pence':current['alert_threshold_pence'],'threshold_choices':sorted(ALERTS)},
        'initial_pack':current['initial_pack'],'notifications':notices,
        'checkout_requests':[{key:row[key] for key in ('pack_id','request_id','status')}
            for row in usage_payments.checkout_requests(tenant)],
        'terms':{'rates_url':'/ai-usage-pricing','month_reset':'Calendar month, UTC',
            'summary':'Your balance pays for V7 AI processing at the published rates for your selected model. It is separate from your subscription. No AI allowance is included. Automatic purchase limits do not limit manual purchases or subscriptions.'},
    }
