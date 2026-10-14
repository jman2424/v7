"""Snapshot referral offers and once-only Stripe discounts, scoped by business."""
import hashlib
import re
import secrets
import time

from service import session_store
from service.subscriptions import connection


def owner_hash(identity):
    return hashlib.sha256(str(identity).strip().lower().encode()).hexdigest()


def _schema(db):
    if session_store._using_postgres():
        return
    db.execute('CREATE TABLE IF NOT EXISTS referral_program (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 100))')
    db.execute('INSERT INTO referral_program VALUES (1,1,40) ON CONFLICT DO NOTHING')
    db.execute('CREATE TABLE IF NOT EXISTS referral_codes (tenant TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, owner_hash TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS referral_claims (tenant TEXT PRIMARY KEY, sponsor TEXT NOT NULL, owner_hash TEXT UNIQUE NOT NULL, percent INTEGER NOT NULL, created INTEGER NOT NULL, qualifying_invoice TEXT UNIQUE, status TEXT NOT NULL DEFAULT \'pending\')')
    db.execute('CREATE TABLE IF NOT EXISTS referral_rewards (tenant TEXT NOT NULL, id TEXT NOT NULL, source_tenant TEXT NOT NULL, kind TEXT NOT NULL, percent INTEGER NOT NULL, created INTEGER NOT NULL, status TEXT NOT NULL DEFAULT \'available\', billing_ref TEXT, coupon TEXT, invoice TEXT, PRIMARY KEY(tenant,id), UNIQUE(tenant,source_tenant,kind))')
    db.commit()


def _lock(db):
    if not session_store._using_postgres():
        db.execute('BEGIN IMMEDIATE')


def program(tenant):
    with connection(tenant) as db:
        _schema(db)
        return dict(db.execute('SELECT enabled,percent FROM referral_program WHERE id=1').fetchone())


def set_program(tenant, enabled, token_hash):
    if type(enabled) is not bool:
        raise ValueError('invalid_referral_setting')
    with connection(tenant) as db:
        _schema(db)
        if session_store._using_postgres():
            db.execute('SELECT v7_private.set_referral_program(?,?)',(token_hash,enabled))
        else:
            db.execute('UPDATE referral_program SET enabled=? WHERE id=1',(int(enabled),))
    return program(tenant)


def report(tenant, identity, base_url):
    with connection(tenant) as db:
        _schema(db)
        code = 'V7-' + secrets.token_hex(16).upper()
        db.execute('INSERT INTO referral_codes VALUES (?,?,?) ON CONFLICT(tenant) DO NOTHING',
                   (tenant,code,owner_hash(identity)))
        row = db.execute('SELECT code FROM referral_codes WHERE tenant=?',(tenant,)).fetchone()
        claim = db.execute('SELECT percent,status FROM referral_claims WHERE tenant=?',(tenant,)).fetchone()
        rewards = [dict(row) for row in db.execute('SELECT id,kind,percent,status FROM referral_rewards WHERE tenant=? ORDER BY created,id',(tenant,))]
    from service import subscriptions
    return {'program':program(tenant),'payments_configured':subscriptions.configured(),'code':row['code'],'link':base_url+'/console/?ref='+row['code'],
            'claim':dict(claim) if claim else None,'rewards':rewards}


def claim(tenant, identity, code):
    from service import subscriptions
    if not isinstance(code,str) or not re.fullmatch(r'V7-[A-Fa-f0-9]{32}',code.strip()):
        raise ValueError('invalid_referral_code')
    hashed = owner_hash(identity)
    with connection(tenant) as db:
        _schema(db)
        _lock(db)
        if session_store._using_postgres():
            db.execute('SELECT pg_advisory_xact_lock_shared(hashtextextended(?,0))',('v7-referral-program',))
        settings = db.execute('SELECT enabled,percent FROM referral_program WHERE id=1').fetchone()
        existing = db.execute('SELECT sponsor,percent,status FROM referral_claims WHERE tenant=?',(tenant,)).fetchone()
        if existing:
            raise ValueError('referral_already_accepted')
        if not settings['enabled']:
            raise ValueError('referral_program_disabled')
        if session_store._using_postgres():
            sponsor = db.execute('SELECT * FROM v7_private.lookup_referral_code(?)',(code.strip().upper(),)).fetchone()
        else:
            sponsor = db.execute('SELECT tenant,owner_hash FROM referral_codes WHERE code=?',(code.strip().upper(),)).fetchone()
        if not sponsor or sponsor['tenant']==tenant or sponsor['owner_hash']==hashed:
            raise ValueError('invalid_or_self_referral')
        if (subscriptions.internal_business(tenant) or subscriptions.complimentary_plan(tenant)
                or db.execute("SELECT 1 FROM billing_invoices WHERE tenant=? AND status='paid' LIMIT 1",(tenant,)).fetchone()
                or db.execute("SELECT 1 FROM billing_contracts WHERE tenant=? AND (subscription IS NOT NULL OR checkout_expires>?) LIMIT 1",(tenant,int(time.time()))).fetchone()):
            raise ValueError('referral_requires_new_business_before_checkout')
        # Unique owner hash and tenant constraints prevent repeated welcome awards.
        inserted = db.execute('INSERT INTO referral_claims(tenant,sponsor,owner_hash,percent,created) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING RETURNING tenant',
            (tenant,sponsor['tenant'],hashed,settings['percent'],int(time.time()))).fetchone()
        if not inserted:
            raise ValueError('referral_already_accepted')
        _award(db,tenant,tenant,settings['percent'])
    return {'ok':True,'percent':settings['percent']}


def _award(db,tenant,source,percent):
    for kind in ('platform','implementation'):
        reward = hashlib.sha256((tenant+'\0'+source+'\0'+kind).encode()).hexdigest()
        db.execute('INSERT INTO referral_rewards(tenant,id,source_tenant,kind,percent,created) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                   (tenant,reward,source,kind,percent,int(time.time())))


def qualified_payment(tenant,kind,invoice):
    """Called only after an invoice was retrieved and verified against V7's ledger."""
    if kind!='platform' or invoice.get('status')!='paid' or invoice.get('amount_paid',0)<=0 or invoice.get('billing_reason')!='subscription_create':
        return
    with connection(tenant) as db:
        _schema(db)
        _lock(db)
        row = db.execute('SELECT * FROM referral_claims WHERE tenant=?'+(' FOR UPDATE' if session_store._using_postgres() else ''),(tenant,)).fetchone()
        if not row or row['status']=='review' or (row['qualifying_invoice'] and row['qualifying_invoice']!=invoice['id']):
            return
        db.execute("UPDATE referral_claims SET qualifying_invoice=?,status='qualified' WHERE tenant=?",(invoice['id'],tenant))
        sponsor,percent = row['sponsor'],row['percent']
    # Retry-safe across tenant transactions: a repeated webhook repairs a partial award.
    with connection(sponsor) as db:
        _schema(db)
        _award(db,sponsor,tenant,percent)
    # A reversal can race the separate sponsor transaction. Recheck the
    # durable claim state so that a delayed paid callback cannot clear review.
    with connection(tenant) as db:
        reviewed = db.execute("SELECT 1 FROM referral_claims WHERE tenant=? AND status='review'",(tenant,)).fetchone()
    if reviewed:
        _review_rewards(sponsor, tenant)


def _review_rewards(sponsor, source):
    with connection(sponsor) as db:
        _schema(db)
        db.execute("UPDATE referral_rewards SET status='review' WHERE tenant=? AND source_tenant=? AND status='available'",(sponsor,source))


def review_payment(tenant, invoice_id):
    """Hold unclaimed awards after a verified refund/dispute, without cash clawbacks."""
    with connection(tenant) as db:
        _schema(db)
        _lock(db)
        row=db.execute('SELECT sponsor,qualifying_invoice FROM referral_claims WHERE tenant=?'+(' FOR UPDATE' if session_store._using_postgres() else ''),(tenant,)).fetchone()
        if not row or row['qualifying_invoice'] not in (None, invoice_id):
            return
        db.execute("UPDATE referral_claims SET status='review',qualifying_invoice=? WHERE tenant=?",(invoice_id,tenant))
        sponsor=row['sponsor']
    _review_rewards(sponsor, tenant)


def handle_reversal(event):
    """Retrieve canonical Stripe objects; never trust event tenant or invoice metadata."""
    from service import subscriptions
    event_type=event.get('type','')
    if event_type not in {'charge.refunded','refund.created','refund.updated','charge.dispute.created','charge.dispute.funds_withdrawn'}:
        return
    obj=event['data']['object']
    stripe=subscriptions.client()
    disputed=False
    def identifier(value,prefix):
        if not isinstance(value,str) or not re.fullmatch(prefix+r'_[A-Za-z0-9]+',value):
            raise ValueError('invalid_referral_payment')
        return value
    if event_type.startswith('charge.dispute.'):
        dispute=stripe.stripe_request('GET','/v1/disputes/'+identifier(obj.get('id'),'dp'))
        subscriptions._verify_payment_environment(dispute)
        disputed=dispute.get('status') not in {'won','warning_closed'}
        charge_id=identifier(dispute.get('charge'),'ch')
    elif event_type.startswith('refund.'):
        refund=stripe.stripe_request('GET','/v1/refunds/'+identifier(obj.get('id'),'re'))
        subscriptions._verify_payment_environment(refund)
        charge_id=identifier(refund.get('charge'),'ch')
    else:
        charge_id=identifier(obj.get('id'),'ch')
    charge=stripe.stripe_request('GET','/v1/charges/'+charge_id)
    subscriptions._verify_payment_environment(charge)
    if not disputed and not charge.get('disputed') and not charge.get('amount_refunded',0)>0:
        return
    payment_id=identifier(charge.get('payment_intent'),'pi')
    payments=stripe.stripe_request('GET','/v1/invoice_payments',{'payment[type]':'payment_intent','payment[payment_intent]':payment_id,'limit':100})
    if payments.get('has_more') or not isinstance(payments.get('data'),list):
        raise ValueError('incomplete_referral_payment_proof')
    for payment in payments['data']:
        if (payment.get('payment') or {}).get('payment_intent') != payment_id:
            raise ValueError('invalid_referral_payment')
        invoice_id=identifier(payment.get('invoice'),'in')
        invoice=stripe.stripe_request('GET','/v1/invoices/'+invoice_id)
        subscriptions._verify_payment_environment(invoice)
        if invoice.get('billing_reason')!='subscription_create':
            continue
        parent=(invoice.get('parent') or {}).get('subscription_details') or {}
        subscription_id=parent.get('subscription') or invoice.get('subscription')
        if not subscription_id:
            continue
        identity=subscriptions.sync_subscription(subscription_id)
        if identity['kind']=='platform':
            review_payment(identity['tenant'],invoice_id)


def reserve(tenant,kind,billing_ref):
    if kind not in ('platform','implementation'):
        return None
    with connection(tenant) as db:
        _schema(db)
        _lock(db)
        if session_store._using_postgres():
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('referral:'+tenant+':'+kind,))
        row = db.execute("SELECT * FROM referral_rewards WHERE tenant=? AND kind=? AND status IN ('reserved','applied') ORDER BY created,id LIMIT 1"+(' FOR UPDATE' if session_store._using_postgres() else ''),(tenant,kind)).fetchone()
        if row:
            return dict(row) if row['billing_ref']==billing_ref else None
        row = db.execute("SELECT * FROM referral_rewards WHERE tenant=? AND kind=? AND status='available' ORDER BY created,id LIMIT 1"+(' FOR UPDATE' if session_store._using_postgres() else ''),(tenant,kind)).fetchone()
        if not row:
            return None
        db.execute("UPDATE referral_rewards SET status='reserved',billing_ref=? WHERE tenant=? AND id=?",(billing_ref,tenant,row['id']))
        return {**dict(row),'billing_ref':billing_ref,'status':'reserved'}


def coupon(stripe,tenant,reward):
    result = stripe.stripe_request('POST','/v1/coupons',
        {'percent_off':reward['percent'],'duration':'once','name':'V7 referral reward'},
        idempotency_key='v7-referral-'+reward['id'])
    identifier = result.get('id')
    if (not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',identifier)
            or result.get('percent_off')!=reward['percent'] or result.get('duration')!='once' or result.get('valid') is not True):
        raise ValueError('invalid_referral_coupon')
    with connection(tenant) as db:
        _schema(db)
        db.execute('UPDATE referral_rewards SET coupon=? WHERE tenant=? AND id=?',(identifier,tenant,reward['id']))
    return identifier


def release(tenant,billing_ref):
    with connection(tenant) as db:
        _schema(db)
        db.execute("UPDATE referral_rewards SET status='available',billing_ref=NULL WHERE tenant=? AND billing_ref=? AND status='reserved'",(tenant,billing_ref))


def consumed_payment(tenant,kind,billing_ref,invoice):
    if invoice.get('status')!='paid' or invoice.get('amount_paid',0)<=0:
        return
    coupons = _coupon_ids(invoice.get('discounts') or [])
    if not coupons:
        return
    with connection(tenant) as db:
        _schema(db)
        for identifier in coupons:
            db.execute("UPDATE referral_rewards SET status='used',invoice=? WHERE tenant=? AND kind=? AND billing_ref=? AND coupon=? AND status IN ('reserved','applied')",(invoice['id'],tenant,kind,billing_ref,identifier))


def _coupon_ids(discounts):
    coupons = set()
    for discount in discounts:
        if isinstance(discount,dict):
            value = discount.get('coupon') or (discount.get('source') or {}).get('coupon')
            if isinstance(value,dict): value = value.get('id')
            if isinstance(value,str): coupons.add(value)
    return coupons


def apply_next_month(tenant):
    from service import subscriptions
    if subscriptions.saved_campaign(tenant):
        raise ValueError('referral_does_not_stack_with_existing_discount')
    contract = subscriptions._contract(tenant,'platform')
    if not contract.get('subscription') or contract['status']!='active':
        raise ValueError('active_paid_subscription_required')
    subscriptions.sync_subscription(contract['subscription'])
    contract = subscriptions._contract(tenant,'platform')
    if contract['status'] != 'active':
        raise ValueError('active_paid_subscription_required')
    reward = reserve(tenant,'platform',contract['ref'])
    if not reward:
        raise ValueError('no_available_referral_reward')
    stripe = subscriptions.client()
    identifier = coupon(stripe,tenant,reward)
    current = stripe.stripe_request('GET','/v1/subscriptions/'+contract['subscription'],{'expand[0]':'discounts'})
    subscriptions._verify_payment_environment(current)
    if current.get('id') != contract['subscription'] or current.get('status') != 'active':
        raise ValueError('active_paid_subscription_required')
    if current.get('discounts') and _coupon_ids(current['discounts']) != {identifier}:
        release(tenant,contract['ref'])
        raise ValueError('referral_does_not_stack_with_existing_discount')
    result = stripe.stripe_request('POST','/v1/subscriptions/'+contract['subscription'],
        {'discounts[0][coupon]':identifier,'proration_behavior':'none','expand[0]':'discounts'},
        idempotency_key='v7-referral-renewal-'+reward['id'])
    if result.get('id')!=contract['subscription'] or _coupon_ids(result.get('discounts') or []) != {identifier}:
        raise ValueError('referral_discount_not_confirmed')
    with connection(tenant) as db:
        _schema(db)
        db.execute("UPDATE referral_rewards SET status='applied' WHERE tenant=? AND id=? AND status='reserved'",(tenant,reward['id']))
    return {'ok':True,'percent':reward['percent']}
