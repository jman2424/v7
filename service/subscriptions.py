"""Stripe-backed subscription and invoice ledger, isolated by company."""
import json
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from connectors.billing import BillingClient
from service import session_store, analytics_db, api_usage

VAT_PERCENT = 20
PRICES = {'platform': 40000, 'implementation': 20000, 'whatsapp': 20000}


# Store only a verifier; the private redemption code is never sent to the browser.
_PLATFORM_DISCOUNT_DIGEST = '5b88cf8922d8d9074123ded1c69cde02e49dc05106694f1bec8eb8b067c0603e'
_PLATFORM_CAMPAIGN = 'platform-recurring-half-v1'


def _discount_campaign(kind, code):
    if not isinstance(code, str) or len(code) > 100:
        raise ValueError('invalid_discount_code')
    if not code.strip():
        return ''
    digest = hashlib.sha256(code.strip().upper().encode()).hexdigest()
    if kind not in {'platform','implementation'} or not hmac.compare_digest(digest, _PLATFORM_DISCOUNT_DIGEST):
        raise ValueError('invalid_discount_code')
    return _PLATFORM_CAMPAIGN


@contextmanager
def connection():
    with session_store.connection() as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS billing_discounts (tenant TEXT PRIMARY KEY, campaign TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS billing_contracts (tenant TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT UNIQUE NOT NULL, subscription TEXT, customer TEXT, status TEXT NOT NULL DEFAULT \'not_started\', next_due INTEGER, paused INTEGER NOT NULL DEFAULT 0, cancel_at_end INTEGER NOT NULL DEFAULT 0, checkout TEXT, checkout_url TEXT, checkout_expires INTEGER, implementation_paid INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(tenant,kind))')
        db.execute('CREATE TABLE IF NOT EXISTS billing_invoices (id TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL, month TEXT NOT NULL, issued INTEGER NOT NULL, due INTEGER, total INTEGER NOT NULL, paid INTEGER NOT NULL, remaining INTEGER NOT NULL, status TEXT NOT NULL, lines TEXT NOT NULL, url TEXT)')
        db.execute('CREATE INDEX IF NOT EXISTS billing_invoice_tenant ON billing_invoices(tenant,issued)')
        db.execute('CREATE TABLE IF NOT EXISTS billing_api_charges (tenant TEXT NOT NULL, month TEXT NOT NULL, amount INTEGER NOT NULL, ref TEXT UNIQUE NOT NULL, checkout TEXT, checkout_url TEXT, checkout_expires INTEGER, PRIMARY KEY(tenant,month))')
        db.execute('CREATE TABLE IF NOT EXISTS billing_references (ref TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL)')
        yield db


def client():
    return BillingClient.from_env()


def configured():
    import os
    stripe = client()
    return bool(stripe.provider == 'stripe' and stripe.api_key and stripe.webhook_secret and os.getenv('STRIPE_TAX_RATE_ID'))


def _safe_url(value, host):
    from urllib.parse import urlsplit
    parsed = urlsplit(value or '')
    return value if parsed.scheme == 'https' and parsed.hostname == host and not parsed.username else None


def _contract(tenant, kind):
    with connection() as db:
        db.execute('INSERT OR IGNORE INTO billing_contracts (tenant,kind,ref) VALUES (?,?,?)', (tenant,kind,secrets.token_urlsafe(24)))
        db.execute('INSERT OR IGNORE INTO billing_references SELECT ref,tenant,kind FROM billing_contracts WHERE tenant=? AND kind=?',(tenant,kind))
        return dict(db.execute('SELECT * FROM billing_contracts WHERE tenant=? AND kind=?', (tenant,kind)).fetchone())


def _tax():
    import os
    rate = os.getenv('STRIPE_TAX_RATE_ID', '')
    if not configured() or not re.fullmatch(r'txr_[A-Za-z0-9]+', rate):
        raise ValueError('stripe_setup_required')
    actual = client().stripe_request('GET','/v1/tax_rates/'+rate)
    if actual.get('active') is not True or actual.get('inclusive') is not False or Decimal(str(actual.get('percentage', -1))) != VAT_PERCENT:
        raise ValueError('stripe_tax_rate_must_be_20_percent_exclusive')
    return rate


def saved_campaign(tenant):
    with connection() as db:
        row = db.execute('SELECT campaign FROM billing_discounts WHERE tenant=?',(tenant,)).fetchone()
    return _PLATFORM_CAMPAIGN if row and row['campaign'] == _PLATFORM_CAMPAIGN else ''


def _discount_coupon(stripe, key):
    coupon = stripe.stripe_request('POST','/v1/coupons',
        {'percent_off':50,'duration':'forever','name':'Business subscription discount'},
        idempotency_key='v7-discount-'+key)
    if not isinstance(coupon.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]+',coupon['id']) or coupon.get('percent_off') != 50 or coupon.get('duration') != 'forever' or coupon.get('valid') is not True:
        raise ValueError('stripe_discount_invalid')
    return coupon['id']


def redeem_discount(tenant, code):
    campaign = _discount_campaign('platform', code)
    if not campaign:
        raise ValueError('invalid_discount_code')
    contract = _contract(tenant,'platform')
    if contract.get('subscription'):
        sync_subscription(contract['subscription'])
        contract = _contract(tenant,'platform')
        if contract['status'] not in {'canceled','incomplete_expired'}:
            stripe = client()
            coupon = _discount_coupon(stripe, contract['ref']+'-renewal')
            # Discount future invoices without creating a proration charge/refund.
            result = stripe.stripe_request('POST','/v1/subscriptions/'+contract['subscription'],
                {'discounts[0][coupon]':coupon,'proration_behavior':'none',
                 'metadata[discount_campaign]':campaign},
                idempotency_key='v7-discount-renewal-'+contract['ref'])
            if result.get('id') != contract['subscription'] or (result.get('metadata') or {}).get('discount_campaign') != campaign:
                raise ValueError('stripe_discount_invalid')
    with connection() as db:
        db.execute('INSERT INTO billing_discounts VALUES (?,?) ON CONFLICT(tenant) DO UPDATE SET campaign=excluded.campaign',(tenant,campaign))
    return {'ok':True,'discount_percent':50}


def checkout(tenant, email, kind, base_url, month='', discount_code=''):
    if not isinstance(kind,str) or kind not in {'platform','implementation','whatsapp','api'} or not isinstance(month,str):
        raise ValueError('invalid_billing_item')
    entered_campaign = _discount_campaign(kind, discount_code)
    if entered_campaign:
        redeem_discount(tenant, discount_code)
    campaign = saved_campaign(tenant) if kind in {'platform','implementation'} else ''
    one_time = kind in {'implementation','api'}
    if kind=='implementation' and (_contract(tenant,'platform')['implementation_paid'] or _contract(tenant,kind)['status']=='paid'):
        raise ValueError('implementation_already_paid')
    if kind=='whatsapp' and _contract(tenant,'platform')['status']!='active':
        raise ValueError('active_platform_subscription_required')
    tax = _tax()
    stripe = client()
    if kind == 'api':
        with connection() as db:
            row = db.execute('SELECT * FROM billing_api_charges WHERE tenant=? AND month=?', (tenant,month)).fetchone()
        if not row:
            raise ValueError('api_charge_not_approved')
        contract = dict(row)
    else:
        contract = _contract(tenant,kind)
        if contract['subscription']:
            sync_subscription(contract['subscription'])
            contract = _contract(tenant,kind)
            if contract['status'] not in {'canceled','incomplete_expired'}:
                raise ValueError('subscription_already_exists')
            with connection() as db:
                db.execute('UPDATE billing_contracts SET ref=?,subscription=NULL,checkout=NULL,checkout_url=NULL,checkout_expires=NULL WHERE ref=?', (secrets.token_urlsafe(24),contract['ref']))
            contract = _contract(tenant,kind)
    if contract.get('checkout'):
        previous = stripe.stripe_request('GET','/v1/checkout/sessions/'+contract['checkout'])
        if previous.get('status') == 'open':
            if (kind=='platform' and (previous.get('metadata') or {}).get('billing_version')!='separate_implementation') or (kind in {'platform','implementation'} and (previous.get('metadata') or {}).get('discount_campaign','') != campaign):
                # Retire old combined checkouts before replacing them with the monthly plan.
                stripe.stripe_request('POST','/v1/checkout/sessions/'+contract['checkout']+'/expire')
            else:
                return {'url':_safe_url(previous.get('url'),'checkout.stripe.com')}
        if previous.get('status') == 'complete':
            raise ValueError('payment_processing_refresh_soon')
        # Serialize the new generation; simultaneous requests use one Stripe idempotency key.
        with connection() as db:
            table = 'billing_api_charges' if kind == 'api' else 'billing_contracts'
            db.execute(f'UPDATE {table} SET ref=?,checkout=NULL,checkout_url=NULL,checkout_expires=NULL WHERE ref=?', (secrets.token_urlsafe(24),contract['ref']))
            row = db.execute(f'SELECT * FROM {table} WHERE tenant=? AND '+('month=?' if kind=='api' else 'kind=?'),(tenant,month if kind=='api' else kind)).fetchone()
            contract = dict(row)
    with connection() as db:
        table = 'billing_api_charges' if kind=='api' else 'billing_contracts'
        db.execute(f'UPDATE {table} SET checkout_expires=? WHERE ref=? AND checkout_expires IS NULL',(int(time.time())+3600,contract['ref']))
        contract['checkout_expires'] = db.execute(f'SELECT checkout_expires FROM {table} WHERE ref=?',(contract['ref'],)).fetchone()[0]
        db.execute('INSERT OR IGNORE INTO billing_references VALUES (?,?,?)',(contract['ref'],tenant,kind))
    ref = contract['ref']
    return_url = base_url+'/console/subscription?'+urlencode({'tenant':tenant})
    data = {'mode':'payment' if one_time else 'subscription','success_url':return_url+'&payment=processing','cancel_url':return_url,
            'managed_payments[enabled]':'false',
            'client_reference_id':tenant,'metadata[tenant]':tenant,'metadata[kind]':kind,'metadata[billing_ref]':ref,
            'metadata[billing_version]':'separate_implementation',
            }
    customer = contract.get('customer') or (_contract(tenant,'platform').get('customer') if kind!='platform' else None)
    if not customer and kind=='platform':
        customer = _contract(tenant,'implementation').get('customer')
    if customer:
        data['customer'] = customer
    elif one_time:
        data['customer_creation'] = 'always'
    # Stripe collects billing contact details; they do not depend on which admin opened checkout.
    meta_prefix = 'invoice_creation[invoice_data][metadata]' if one_time else 'subscription_data[metadata]'
    for key, value in {'tenant':tenant,'kind':kind,'billing_ref':ref,'month':month}.items():
        data[f'{meta_prefix}[{key}]'] = value
    if one_time:
        data['invoice_creation[enabled]'] = 'true'
    else:
        data['subscription_data[default_tax_rates][0]'] = tax
    items = [(kind, contract['amount'] if kind=='api' else PRICES[kind], not one_time)]
    for index, (item,amount,recurring) in enumerate(items):
        prefix = f'line_items[{index}]'
        name = {'platform':'V7 monthly subscription','implementation':'V7 implementation (one time)','whatsapp':'V7 WhatsApp monthly add-on','api':'V7 API usage '+month}[item]
        data.update({prefix+'[quantity]':1,prefix+'[price_data][currency]':'gbp',prefix+'[price_data][unit_amount]':amount,
                     prefix+'[price_data][tax_behavior]':'exclusive',prefix+'[price_data][product_data][name]':name,prefix+'[tax_rates][0]':tax})
        if recurring:
            data[prefix+'[price_data][recurring][interval]'] = 'month'
    if campaign:
        data['discounts[0][coupon]'] = _discount_coupon(stripe, ref)
        data['metadata[discount_campaign]'] = campaign
    result = stripe.stripe_request('POST','/v1/checkout/sessions',data,idempotency_key='v7-checkout-'+ref)
    url = _safe_url(result.get('url'),'checkout.stripe.com')
    if not url or not re.fullmatch(r'cs_[A-Za-z0-9_]+', result.get('id','')):
        raise ValueError('stripe_response_invalid')
    with connection() as db:
        table = 'billing_api_charges' if kind=='api' else 'billing_contracts'
        db.execute(f'UPDATE {table} SET checkout=?,checkout_url=?,checkout_expires=? WHERE ref=?', (result['id'],url,result.get('expires_at'),ref))
    return {'url':url}


def sync_subscription(subscription_id):
    if not re.fullmatch(r'sub_[A-Za-z0-9]+',subscription_id):
        raise ValueError('invalid_subscription')
    data = client().stripe_request('GET','/v1/subscriptions/'+subscription_id)
    metadata = data.get('metadata') or {}
    with connection() as db:
        row = db.execute('SELECT tenant,kind FROM billing_references WHERE ref=?', (metadata.get('billing_ref',''),)).fetchone()
        if not row or row['tenant'] != metadata.get('tenant') or row['kind'] != metadata.get('kind'):
            raise ValueError('unknown_billing_reference')
        periods = [item.get('current_period_end') for item in data.get('items',{}).get('data',[]) if item.get('current_period_end')]
        db.execute('UPDATE billing_contracts SET subscription=?,customer=?,status=?,next_due=?,cancel_at_end=? WHERE ref=?',
                   (subscription_id,data.get('customer'),data.get('status','unknown'),min(periods) if periods else None,int(bool(data.get('cancel_at_period_end'))),metadata['billing_ref']))
    return dict(row)


def sync_invoice(invoice_id):
    if not re.fullmatch(r'in_[A-Za-z0-9]+',invoice_id):
        raise ValueError('invalid_invoice')
    invoice = client().stripe_request('GET','/v1/invoices/'+invoice_id)
    if invoice.get('currency') != 'gbp':
        raise ValueError('unsupported_invoice_currency')
    parent = (invoice.get('parent') or {}).get('subscription_details') or {}
    subscription_id = parent.get('subscription') or invoice.get('subscription')
    if subscription_id:
        identity = sync_subscription(subscription_id)
        month = datetime.fromtimestamp(invoice.get('period_start') or invoice['created'],timezone.utc).strftime('%Y-%m')
    else:
        metadata = invoice.get('metadata') or {}
        with connection() as db:
            row = db.execute("SELECT tenant,kind FROM billing_references WHERE ref=? AND kind IN ('api','implementation')", (metadata.get('billing_ref',''),)).fetchone()
        if not row or row['tenant']!=metadata.get('tenant') or row['kind']!=metadata.get('kind'):
            raise ValueError('unknown_billing_reference')
        identity = dict(row)
        month = metadata.get('month') if row['kind']=='api' else datetime.fromtimestamp(invoice['created'],timezone.utc).strftime('%Y-%m')
    lines = [{'description':str(line.get('description') or '')[:300], 'amount':line.get('amount',0)} for line in invoice.get('lines',{}).get('data',[])]
    with connection() as db:
        db.execute("INSERT INTO billing_invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET total=excluded.total,paid=excluded.paid,remaining=excluded.remaining,status=excluded.status,lines=excluded.lines,url=excluded.url WHERE billing_invoices.status!='paid' OR excluded.status='paid'",
                   (invoice_id,identity['tenant'],identity['kind'],month,invoice['created'],invoice.get('due_date'),invoice['total'],invoice['amount_paid'],invoice['amount_remaining'],invoice['status'],json.dumps(lines),_safe_url(invoice.get('hosted_invoice_url'),'invoice.stripe.com')))
        legacy_implementation = identity['kind']=='platform' and invoice.get('billing_reason')=='subscription_create' and any('V7 implementation' in line['description'] for line in lines)
        if invoice.get('status')=='paid' and (identity['kind']=='implementation' or legacy_implementation):
            db.execute('UPDATE billing_contracts SET implementation_paid=1 WHERE tenant=? AND kind=\'platform\'',(identity['tenant'],))
            if identity['kind']=='implementation':
                db.execute("UPDATE billing_contracts SET status='paid',customer=? WHERE tenant=? AND kind='implementation'",(invoice.get('customer'),identity['tenant']))


def change_whatsapp(tenant, enabled):
    contract = _contract(tenant,'whatsapp')
    if not contract['subscription']:
        raise ValueError('whatsapp_subscription_required')
    # Stop future renewals on deactivation; no surprise prorations or refunds.
    client().stripe_request('POST','/v1/subscriptions/'+contract['subscription'],{'cancel_at_period_end':'false' if enabled else 'true'},
                            idempotency_key='v7-wa-'+contract['ref']+'-'+str(enabled)+'-'+str(int(time.time())//30))
    sync_subscription(contract['subscription'])
    with connection() as db:
        db.execute("UPDATE billing_contracts SET paused=? WHERE tenant=? AND kind='whatsapp'",(int(not enabled),tenant))


def portal(tenant, base_url):
    customer = _contract(tenant,'platform').get('customer')
    if not customer:
        raise ValueError('subscription_required')
    result = client().stripe_request('POST','/v1/billing_portal/sessions',{'customer':customer,'return_url':base_url+'/console/subscription?'+urlencode({'tenant':tenant})})
    url = _safe_url(result.get('url'),'billing.stripe.com')
    if not url:
        raise ValueError('stripe_response_invalid')
    return {'url':url}


def whatsapp_enabled(tenant):
    with connection() as db:
        row = db.execute("SELECT paused,status,next_due FROM billing_contracts WHERE tenant=? AND kind='whatsapp'",(tenant,)).fetchone()
    # Enforce purchased access when a billing contract exists. Preserve legacy integrations until migrated.
    return (not configured() if row is None else not row['paused'] and row['status'] in {'active','trialing'} and (row['next_due'] or 0)>time.time())


def approve_api_charge(tenant, month, amount):
    current = datetime.now(timezone.utc).strftime('%Y-%m')
    if not isinstance(month,str) or not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',month) or month>=current:
        raise ValueError('choose_a_completed_month')
    if type(amount) is not int or not 1<=amount<=10_000_000:
        raise ValueError('invalid_api_charge')
    with connection() as db:
        try:
            db.execute('INSERT INTO billing_api_charges (tenant,month,amount,ref) VALUES (?,?,?,?)',(tenant,month,amount,secrets.token_urlsafe(24)))
        except sqlite3.IntegrityError as exc:
            raise ValueError('month_already_approved') from exc


def usage_months(tenant):
    with closing(analytics_db._conn()) as db:
        api_usage._schema(db)
        rows = db.execute("SELECT substr(ts_utc,1,7) month,COUNT(*) calls,SUM(cost_nano_usd) cost,SUM(cost_nano_usd IS NULL) unpriced FROM api_usage WHERE tenant=? GROUP BY month ORDER BY month DESC LIMIT 24",(tenant.upper(),)).fetchall()
    from service.usage_currency import gbp_rate
    rate = gbp_rate() if rows else None
    return [{'month':row['month'],'calls':row['calls'],'unpriced':row['unpriced'],
             'estimated_pence':int((Decimal(row['cost'])*Decimal(str(rate['rate']))/Decimal(10_000_000)).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if rate and row['cost'] is not None and not row['unpriced'] else None} for row in rows],rate


def report(tenant, include_api=True):
    with connection() as db:
        contracts = [dict(row) for row in db.execute('SELECT kind,status,next_due,paused,cancel_at_end,implementation_paid FROM billing_contracts WHERE tenant=?',(tenant,))]
        invoices = [dict(row) for row in db.execute('SELECT * FROM billing_invoices WHERE tenant=? ORDER BY issued DESC LIMIT 120',(tenant,))]
        approved = [dict(row) for row in db.execute('SELECT month,amount FROM billing_api_charges WHERE tenant=? ORDER BY month DESC LIMIT 24',(tenant,))]
        totals = dict(db.execute("SELECT COALESCE(SUM(paid),0) paid,COALESCE(SUM(CASE WHEN status='open' THEN remaining ELSE 0 END),0) due FROM billing_invoices WHERE tenant=?",(tenant,)).fetchone())
        totals['approved_api_due'] = db.execute("SELECT COALESCE(SUM((amount*120+50)/100),0) FROM billing_api_charges a WHERE tenant=? AND NOT EXISTS (SELECT 1 FROM billing_invoices i WHERE i.tenant=a.tenant AND i.kind='api' AND i.month=a.month)",(tenant,)).fetchone()[0]
    for invoice in invoices:
        invoice['lines'] = json.loads(invoice['lines'])
    if include_api:
        usage, rate = usage_months(tenant)
    else:
        invoices = [row for row in invoices if row['kind']!='api']
        with connection() as db:
            totals = dict(db.execute("SELECT COALESCE(SUM(paid),0) paid,COALESCE(SUM(CASE WHEN status='open' THEN remaining ELSE 0 END),0) due FROM billing_invoices WHERE tenant=? AND kind!='api'", (tenant,)).fetchone())
        totals['approved_api_due'] = 0
        usage, rate, approved = [], None, []
    return {'tenant':tenant,'discount_percent':50 if saved_campaign(tenant) else 0,'configured':configured(),'prices':PRICES,'vat_percent':VAT_PERCENT,'contracts':contracts,'invoices':invoices,'totals':totals,'usage':usage,'exchange_rate':rate,'approved_api_charges':approved,'whatsapp_enabled':whatsapp_enabled(tenant)}
