"""Durable recharge/outbox consumers in the existing Render app process.

Database leases and stable provider keys survive restarts/multiple workers. No
timer owns financial state. No new paid service or live switch is enabled here.
"""
import atexit
import hashlib
from html import escape
import json
import os
from threading import Event, Lock, Thread
import time
from urllib.parse import urlencode

from service import ai_budget_store as store, ai_budget_payments as payments
from service import registration_mail, usage_wallet, session_store, subscriptions
from service.account_service import AccountService

_lock, _stop = Lock(), Event()
_thread, _monitor_thread, _pid, _offset = None, None, None, 0
SUBJECTS = {'low_balance':'Your V7 AI balance is running low',
    'recharge_succeeded':'£5 added to your V7 AI balance',
    'recharge_cap':'Your V7 automatic recharge limit has been reached',
    'authentication_required':'Your V7 automatic payment needs confirmation',
    'payment_failed':'Your V7 automatic recharge could not complete',
    'payment_review':'Your V7 automatic payment needs review'}


def render(kind,base_url,tenant):
    subject = SUBJECTS[kind]
    body = {
        'low_balance':'Your AI balance has crossed your selected alert threshold. Review your balance and add funds if needed.',
        'recharge_succeeded':'Your authorised £5 automatic recharge completed. £5 has been added to your V7 AI balance.',
        'recharge_cap':'Your calendar-month (UTC) limit prevents another automatic £5 purchase. Manual top-ups and subscriptions are separate.',
        'authentication_required':'Your card needs confirmation. Automatic recharge is paused. Sign in to review the payment; no repeated payment attempts will be made.',
        'payment_failed':'Automatic recharge is paused after a payment failure. Your existing balance is preserved. Sign in to review your settings.',
        'payment_review':'We could not confirm the outcome of a payment. Further automatic purchases are held pending review. Please contact support from your account.'}[kind]
    url=base_url.rstrip('/')+'/console/budget?'+urlencode({'tenant':tenant})
    text=body+'\n\nReview AI Budget: '+url+'\n\nVertex Seven\nSign in securely; we will never ask for card details by email.'
    html=('<!doctype html><html lang="en"><body style="font-family:Arial,sans-serif;background:#f3f5f4;color:#153c30">'
        '<main style="max-width:560px;margin:24px auto;padding:24px;background:white"><h1 style="font-size:23px">'+escape(subject)+
        '</h1><p style="line-height:1.6">'+escape(body)+'</p><p><a href="'+escape(url,quote=True)+
        '" style="display:inline-block;padding:14px;background:#164536;color:white">Review AI Budget</a></p>'
        '<p>Sign in securely; we will never ask for card details by email.</p></main></body></html>')
    return subject,text,html


def notify_one(container,tenant):
    now=time.time()
    with store.connection(tenant,write=True) as db:
        row=db.execute("SELECT * FROM ai_budget_notifications WHERE tenant=? AND state IN('pending','sending') AND available<=? ORDER BY created,id LIMIT 1"+
            (' FOR UPDATE SKIP LOCKED' if session_store._using_postgres() else ''),(tenant,now)).fetchone()
        if not row:
            return False
        row=dict(row)
        if row['attempts']>=8 or row['attempts'] and row['created']<now-23*3600:
            db.execute("UPDATE ai_budget_notifications SET state='needs_review' WHERE tenant=? AND id=?",(tenant,row['id']))
            return True
        settings=store.settings(tenant,db)
        # Recheck an opt-out before sending a queued threshold alert.
        email=bool(row['email_enabled']) and (row['kind']!='low_balance' or settings['alerts_enabled'] and settings['email_alerts'])
        if not email or row['kind'] not in SUBJECTS:
            db.execute("UPDATE ai_budget_notifications SET state='dashboard_only' WHERE tenant=? AND id=?",(tenant,row['id']))
            return True
        lease=now+120
        db.execute("UPDATE ai_budget_notifications SET state='sending',attempts=attempts+1,available=? WHERE tenant=? AND id=?",(lease,tenant,row['id']))
    try:
        recipients=sorted({a['email'] for a in AccountService(container.storage).list_accounts(tenant)
            if a['active'] and 'business_owner' in a['roles']})
        if not recipients:
            raise ValueError('budget_no_active_recipient')
        subject,text,html=render(row['kind'],container.settings.BASE_URL,tenant)
        for email in recipients:
            key=hashlib.sha256((row['id']+':'+email).encode()).hexdigest()
            registration_mail.send_transactional(email,subject,text,html,idempotency_key='v7-budget-'+key)
        state,available='sent',now
    except Exception as exc:
        from flask import current_app
        current_app.logger.warning('Budget notification failed error_type=%s',type(exc).__name__)
        state,available='pending',now+min(3600,30*2**row['attempts'])
    with store.connection(tenant,write=True) as db:
        db.execute("UPDATE ai_budget_notifications SET state=?,available=? WHERE tenant=? AND id=? AND state='sending' AND available=?",(state,available,tenant,row['id'],lease))
    return True


def capture_payment_cost(tenant):
    """Delayed Stripe settlement cost, never deducted from advertised credit."""
    with store.connection(tenant) as db:
        row=db.execute('SELECT p.payment_id,p.paid_pence FROM usage_wallet_payments p LEFT JOIN ai_budget_payment_costs c ON c.tenant=p.tenant AND c.payment_id=p.payment_id WHERE p.tenant=? AND c.payment_id IS NULL ORDER BY p.created_utc LIMIT 1',(tenant,)).fetchone()
    if not row:
        return False
    with store.connection(tenant,write=True) as db:
        current=store.ensure_settings(db,tenant)
        if current['fees_check_after']>time.time():
            return False
        db.execute('UPDATE ai_budget_settings SET fees_check_after=? WHERE tenant=?',(time.time()+3600,tenant))
    from service.usage_payments import _id, _integer, _require_payment_mode
    stripe=subscriptions.client()
    intent=stripe.stripe_request('GET','/v1/payment_intents/'+_id(row['payment_id'],'pi'))
    _require_payment_mode(intent.get('livemode'))
    if intent.get('id')!=row['payment_id'] or intent.get('status')!='succeeded':
        raise ValueError('budget_cost_payment_mismatch')
    charge_id=_id(intent.get('latest_charge'),'ch')
    charge=stripe.stripe_request('GET','/v1/charges/'+charge_id)
    if charge.get('id')!=charge_id or charge.get('payment_intent')!=row['payment_id']:
        raise ValueError('budget_cost_payment_mismatch')
    transaction=_id(charge.get('balance_transaction'),'txn')
    cost=stripe.stripe_request('GET','/v1/balance_transactions/'+transaction)
    if cost.get('id')!=transaction or cost.get('source')!=charge_id or cost.get('currency')!='gbp':
        raise ValueError('budget_cost_currency_or_payment_mismatch')
    gross=_integer(cost.get('amount'),row['paid_pence'])
    fee=_integer(cost.get('fee'))
    net=cost.get('net')
    if type(net) is not int or gross-fee!=net:
        raise ValueError('budget_cost_payment_mismatch')
    details=[]
    for part in (cost.get('fee_details') or [])[:20]:
        if not isinstance(part,dict) or part.get('type') not in {'stripe_fee','tax','application_fee','payment_method_passthrough_fee'}:
            continue
        amount=part.get('amount')
        if type(amount) is int and part.get('currency')=='gbp':
            details.append({'type':part['type'],'amount_pence':amount})
    with store.connection(tenant,write=True) as db:
        db.execute('INSERT INTO ai_budget_payment_costs VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant,payment_id) DO NOTHING',
            (tenant,row['payment_id'],transaction,'gbp',gross,fee,net,json.dumps(details,sort_keys=True),time.time()))
    return True


def run_once(container,tenants=None):
    global _offset
    keys=list(container.storage.tenant_keys() if tenants is None else tenants)
    if not keys:
        return 0
    selected=(keys[_offset:]+keys[:_offset])[:25]
    _offset=(_offset+len(selected))%len(keys)
    processed=0
    for tenant in selected:
        usage_wallet.report(tenant,include_costs=False)
        try:
            # Finish dispatched payments even after opt-out. No eligibility check
            # is allowed to discard a verified payment already taken.
            with store.connection(tenant) as db:
                rows=[dict(r) for r in db.execute("SELECT reference FROM ai_budget_recharges WHERE tenant=? AND status IN('reserved','dispatching','processing','unknown') AND lease_until<=? ORDER BY created LIMIT 1",(tenant,time.time()))]
            if rows:
                processed+=bool(payments.process_recharge(tenant,rows[0]['reference']))
            else:
                reference=payments.reserve_recharge(tenant)
                if reference:
                    processed+=bool(payments.process_recharge(tenant,reference))
        except Exception as exc:
            from flask import current_app
            current_app.logger.warning('Budget recharge worker failed error_type=%s',type(exc).__name__)
        try:
            processed+=notify_one(container,tenant)
            # Fee collection is independent of money and notification settlement.
            if subscriptions.configured():
                processed+=capture_payment_cost(tenant)
        except Exception as exc:
            from flask import current_app
            current_app.logger.warning('Budget bookkeeping failed error_type=%s',type(exc).__name__)
    return processed


def start(app):
    global _thread,_monitor_thread,_pid
    if app.testing or os.getenv('V7_AI_BUDGET_WORKER','false')!='true':
        return
    with _lock:
        if _pid==os.getpid() and _thread and _thread.is_alive():
            return
        _pid=os.getpid()
        _stop.clear()
        def loop():
            while not _stop.is_set():
                try:
                    with app.app_context():
                        run_once(app.container)
                except Exception as exc:
                    app.logger.warning('AI Budget worker failed error_type=%s',type(exc).__name__)
                _stop.wait(30)
        _thread=Thread(target=loop,name='v7-ai-budget',daemon=True)
        _thread.start()
        if os.getenv('V7_PROVIDER_COST_MONITOR','false')=='true' and os.getenv('OPENAI_ADMIN_KEY'):
            def monitor():
                last=time.monotonic()-3600
                while not _stop.is_set():
                    if time.monotonic()-last>=3600:
                        try:
                            with app.app_context():
                                from service.ai_provider_funding import sync_costs,sync_limits
                                sync_costs(days=7)
                                sync_limits()
                        except Exception as exc:
                            app.logger.warning('Provider cost monitor unavailable error_type=%s',type(exc).__name__)
                        last=time.monotonic()
                    _stop.wait(60)
            _monitor_thread=Thread(target=monitor,name='v7-provider-monitor',daemon=True)
            _monitor_thread.start()
        atexit.register(_stop.set)
