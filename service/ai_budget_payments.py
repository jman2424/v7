"""Consent-backed fixed GBP 5 recharges; all money settles in usage_wallet."""
from decimal import Decimal, ROUND_HALF_UP
import json
import secrets
import re
import time
from urllib.parse import urlencode

from service import ai_budget as budget, ai_budget_store as store
from service import business_applications as applications, subscriptions, usage_payments, usage_wallet

SETUP_KIND = 'ai_budget_setup'
RECHARGE_KIND = 'ai_budget_recharge'
VERSION = 'ai-budget-authorisation-1'
OPEN = ('reserved','dispatching','processing','requires_action','unknown')


def _terms(cap):
    return (f'I authorise Vertex Seven to charge my saved card £5 and add £5 to my V7 AI balance when '
        f'my settled balance falls below £2, up to £{cap//100} in automatic purchases per calendar month (UTC). '
        'This is separate from subscription payments and manual top-ups. It is not a fixed monthly payment. '
        'I can disable future recharges in AI Budget. An already-started payment may complete. '
        'Funds buy V7 AI processing at the published usage rates; they are not OpenAI credits. '
        'The £5 payment includes any applicable VAT.')


def authorise(tenant, data, actor, base_url):
    allowed = {'accepted_terms','cap_pence','request_id'}
    if (not isinstance(data,dict) or set(data)-allowed or data.get('accepted_terms') is not True
            or type(data.get('cap_pence')) is not int or data['cap_pence'] not in budget.CAPS):
        raise budget.BudgetError('budget_authorisation_required')
    request_id = usage_payments._request_id(data.get('request_id'))
    if not budget.live_recharge_allowed():
        raise budget.BudgetError('budget_live_recharge_not_enabled',409)
    usage_payments._require_payment_mode(subscriptions.client().api_key.startswith(('sk_live_','rk_live_')))
    budget.require_eligible(tenant)
    from service.security import _revision
    revision = _revision(actor)
    if not revision:
        raise budget.BudgetError('budget_owner_not_active',403)
    identity = {key:actor[key] for key in ('id','email','tenant','roles')}
    with store.connection(tenant,write=True) as db:
        current = store.ensure_settings(db,tenant)
        old = db.execute('SELECT * FROM ai_budget_authorisations WHERE tenant=? AND request_id=?',(tenant,request_id)).fetchone()
        if old:
            row = dict(old)
            if row['cap_pence'] != data['cap_pence'] or row['actor'] != json.dumps(identity,sort_keys=True):
                raise budget.BudgetError('budget_authorisation_mismatch',409)
        else:
            pending = db.execute("SELECT 1 FROM ai_budget_recharges WHERE tenant=? AND status IN('reserved','dispatching','processing','requires_action','unknown') LIMIT 1",(tenant,)).fetchone()
            if pending:
                raise budget.BudgetError('budget_payment_in_progress',409)
            identifier = secrets.token_hex(24)
            db.execute("INSERT INTO ai_budget_authorisations(id,tenant,revision,request_id,actor,actor_revision,consent_terms,cap_pence,livemode,status,created,updated) VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?)",
                (identifier,tenant,current['revision']+1,request_id,json.dumps(identity,sort_keys=True),revision,_terms(data['cap_pence']),data['cap_pence'],
                 int(subscriptions.client().api_key.startswith(('sk_live_','rk_live_'))),time.time(),time.time()))
            db.execute("UPDATE ai_budget_authorisations SET status='revoked',updated=? WHERE tenant=? AND id!=? AND status IN('active','pending')",(time.time(),tenant,identifier))
            db.execute("UPDATE ai_budget_settings SET revision=revision+1,authorisation=?,recharge_enabled=0,recharge_cap_pence=?,blocked_reason='authorisation_pending',updated=? WHERE tenant=?",
                (identifier,data['cap_pence'],time.time(),tenant))
            store.audit(db,tenant,'authorisation_requested',actor['id'],{'cap_pence':data['cap_pence'],'terms':_terms(data['cap_pence']),'version':VERSION})
            row = dict(db.execute('SELECT * FROM ai_budget_authorisations WHERE tenant=? AND id=?',(tenant,identifier)).fetchone())
    if row['status'] != 'pending':
        return {'ok':True,'status':row['status']}
    if row['created'] < time.time()-23*3600:
        raise budget.BudgetError('budget_authorisation_needs_review',409)
    if row['checkout']:
        return {'url':row['checkout_url'],'status':'pending'}
    stripe = subscriptions.client()
    usage_payments._require_payment_mode(bool(row['livemode']))
    if not subscriptions.configured():
        raise budget.BudgetError('stripe_setup_required',503)
    customer = row['customer']
    if not customer:
        with subscriptions.connection(tenant) as db:
            saved = db.execute("SELECT customer FROM billing_contracts WHERE tenant=? AND customer IS NOT NULL AND kind IN('platform','implementation') ORDER BY CASE WHEN kind='platform' THEN 0 ELSE 1 END LIMIT 1",(tenant,)).fetchone()
        if saved and saved['customer']:
            customer = usage_payments._id(saved['customer'],'cus')
        else:
            with store.connection(tenant) as db:
                previous=db.execute("SELECT customer FROM ai_budget_authorisations WHERE tenant=? AND id!=? AND customer!='' ORDER BY created DESC LIMIT 1",(tenant,row['id'])).fetchone()
            if previous:
                customer=usage_payments._id(previous['customer'],'cus')
            else:
                result = stripe.stripe_request('POST','/v1/customers',{'metadata[tenant]':tenant,'metadata[kind]':'v7_billing'},idempotency_key='v7-budget-customer-'+row['id'])
                customer = usage_payments._id(result.get('id'),'cus')
        with store.connection(tenant,write=True) as db:
            db.execute('UPDATE ai_budget_authorisations SET customer=? WHERE tenant=? AND id=? AND customer=?',(customer,tenant,row['id'],''))
    return_url = base_url.rstrip('/')+'/console/budget?'+urlencode({'tenant':tenant})
    metadata = {'tenant':tenant,'kind':SETUP_KIND,'budget_authorisation':row['id'],'budget_version':VERSION}
    payload = {'mode':'setup','customer':customer,'payment_method_types[0]':'card',
        'success_url':return_url+'&authorisation=processing','cancel_url':return_url,
        'custom_text[submit][message]':row['consent_terms']}
    for prefix in ('metadata','setup_intent_data[metadata]'):
        payload.update({prefix+'['+key+']':value for key,value in metadata.items()})
    result = stripe.stripe_request('POST','/v1/checkout/sessions',payload,idempotency_key='v7-budget-setup-'+row['id'])
    checkout = usage_payments._id(result.get('id'),'cs')
    url = subscriptions._safe_url(result.get('url'),'checkout.stripe.com')
    if not url:
        raise budget.BudgetError('budget_provider_response_invalid',503)
    with store.connection(tenant,write=True) as db:
        saved = db.execute('SELECT checkout FROM ai_budget_authorisations WHERE tenant=? AND id=?',(tenant,row['id'])).fetchone()
        if saved['checkout'] and saved['checkout'] != checkout:
            raise budget.BudgetError('budget_authorisation_mismatch',409)
        db.execute('UPDATE ai_budget_authorisations SET checkout=?,checkout_url=?,updated=? WHERE tenant=? AND id=?',(checkout,url,time.time(),tenant,row['id']))
    return {'url':url,'status':'pending'}


def _setup_row(metadata):
    if not isinstance(metadata,dict) or metadata.get('kind') != SETUP_KIND or metadata.get('budget_version') != VERSION:
        raise budget.BudgetError('budget_authorisation_mismatch')
    tenant,identifier = metadata.get('tenant'),metadata.get('budget_authorisation')
    from retrieval.storage import Storage
    if (not isinstance(tenant,str) or not isinstance(identifier,str)
            or not re.fullmatch(r'[0-9a-f]{48}',identifier)):
        raise budget.BudgetError('budget_authorisation_mismatch')
    try:
        Storage.validate_tenant_key(tenant)
    except ValueError:
        raise budget.BudgetError('budget_authorisation_mismatch') from None
    with store.connection(tenant) as db:
        row = db.execute('SELECT * FROM ai_budget_authorisations WHERE tenant=? AND id=?',(tenant,identifier)).fetchone()
    if not row:
        raise budget.BudgetError('budget_authorisation_not_found',404)
    return dict(row)


def confirm_authorisation(tenant, checkout=None):
    budget.require_eligible(tenant)
    with store.connection(tenant) as db:
        settings = store.settings(tenant,db)
        saved = db.execute('SELECT * FROM ai_budget_authorisations WHERE tenant=? AND id=?',(tenant,settings['authorisation'])).fetchone()
    if not saved:
        raise budget.BudgetError('budget_authorisation_not_found',404)
    row = dict(saved)
    if not budget.live_recharge_allowed() or not _actor_valid(row):
        raise budget.BudgetError('budget_authorisation_not_active',403)
    checkout = checkout or row['checkout']
    if not checkout or row['checkout'] and row['checkout'] != checkout:
        raise budget.BudgetError('budget_authorisation_mismatch')
    stripe = subscriptions.client()
    session = stripe.stripe_request('GET','/v1/checkout/sessions/'+usage_payments._id(checkout,'cs'))
    proof = _setup_row(session.get('metadata'))
    if proof['id'] != row['id'] or session.get('id') != checkout or session.get('mode') != 'setup' or session.get('customer') != row['customer']:
        raise budget.BudgetError('budget_authorisation_mismatch')
    if session.get('status') != 'complete':
        return {'ok':False,'status':'pending'}
    usage_payments._require_payment_mode(session.get('livemode'))
    if type(session.get('livemode')) is not bool or session['livemode'] != bool(row['livemode']):
        raise budget.BudgetError('budget_authorisation_mismatch')
    intent_id = usage_payments._id(session.get('setup_intent'),'seti')
    intent = stripe.stripe_request('GET','/v1/setup_intents/'+intent_id)
    intent_row = _setup_row(intent.get('metadata'))
    if (intent_row['id'] != row['id'] or intent.get('id') != intent_id or intent.get('customer') != row['customer']
            or intent.get('status') != 'succeeded' or intent.get('usage') != 'off_session'
            or type(intent.get('livemode')) is not bool or intent['livemode'] != bool(row['livemode'])):
        raise budget.BudgetError('budget_authorisation_mismatch')
    method_id = usage_payments._id(intent.get('payment_method'),'pm')
    method = stripe.stripe_request('GET','/v1/payment_methods/'+method_id)
    if (method.get('id') != method_id or method.get('customer') != row['customer'] or method.get('type') != 'card'
            or type(method.get('livemode')) is not bool or method['livemode'] != bool(row['livemode'])):
        raise budget.BudgetError('budget_authorisation_mismatch')
    with store.connection(tenant,write=True) as db:
        current = store.ensure_settings(db,tenant)
        saved = db.execute('SELECT status FROM ai_budget_authorisations WHERE tenant=? AND id=?',(tenant,row['id'])).fetchone()
        if current['authorisation'] != row['id'] or saved['status'] == 'revoked' or not _actor_valid(row):
            return {'ok':False,'status':'revoked'}
        db.execute("UPDATE ai_budget_authorisations SET checkout=?,setup_intent=?,payment_method=?,status='active',updated=? WHERE tenant=? AND id=?",(checkout,intent_id,method_id,time.time(),tenant,row['id']))
        db.execute("UPDATE ai_budget_settings SET recharge_enabled=1,blocked_reason='',updated=? WHERE tenant=?",(time.time(),tenant))
        if saved['status'] != 'active':
            store.audit(db,tenant,'automatic_recharge_enabled',json.loads(row['actor'])['id'],{'cap_pence':row['cap_pence'],'version':VERSION})
    return {'ok':True,'status':'active'}


def disable(tenant, actor):
    with store.connection(tenant,write=True) as db:
        store.ensure_settings(db,tenant)
        db.execute("UPDATE ai_budget_settings SET recharge_enabled=0,blocked_reason='',revision=revision+1,updated=? WHERE tenant=?",(time.time(),tenant))
        db.execute("UPDATE ai_budget_authorisations SET status='revoked',updated=? WHERE tenant=? AND status IN('pending','active')",(time.time(),tenant))
        db.execute("UPDATE ai_budget_recharges SET status='cancelled',updated=? WHERE tenant=? AND status='reserved' AND attempts=0",(time.time(),tenant))
        store.audit(db,tenant,'automatic_recharge_disabled',actor,{})
    # Disable commits before any provider call; an outage cannot prevent opting out.
    # Already-dispatched payments remain recorded and are reconciled even after opt-out.
    # Resolve never-dispatched permits separately; opting out never depends on Stripe.
    with store.connection(tenant) as db:
        cancelled = [row['reference'] for row in db.execute("SELECT reference FROM ai_budget_recharges WHERE tenant=? AND status='cancelled' AND attempts=0",(tenant,))]
    for reference in cancelled:
        applications.expire_budget_permit(tenant,reference)
    return {'ok':True,'status':'disabled'}


def _actor_valid(row):
    from service.security import _revision
    identity = json.loads(row['actor'])
    revision = _revision(identity)
    return bool(revision and revision == row['actor_revision'])


def reserve_recharge(tenant):
    if not budget.live_recharge_allowed():
        return None
    preview=store.settings(tenant)
    if not preview['recharge_enabled'] or preview['blocked_reason']:
        return None
    budget.require_eligible(tenant)
    from service.ai_provider_funding import health
    if health(tenant)['status'] in {'funding_exhausted','usage_limit'}:
        return None
    # Initialise an empty wallet before acquiring budget settings. Lock order
    # remains wallet -> settings for all ledger writers and first-time recharges.
    with usage_wallet._connection(tenant,write=True) as db:
        usage_wallet._locked_wallet(db,tenant)
    with store.connection(tenant,write=True) as db:
        settings = store.ensure_settings(db,tenant)
        if not settings['recharge_enabled'] or settings['blocked_reason']:
            return None
        authorisation = db.execute("SELECT * FROM ai_budget_authorisations WHERE tenant=? AND id=? AND status='active'",(tenant,settings['authorisation'])).fetchone()
        if not authorisation:
            return None
        authorisation = dict(authorisation)
        if not _actor_valid(authorisation):
            db.execute("UPDATE ai_budget_settings SET recharge_enabled=0,blocked_reason='owner_access_changed' WHERE tenant=?",(tenant,))
            return None
        wallet = db.execute('SELECT * FROM usage_wallets WHERE tenant=?',(tenant,)).fetchone()
        if (not wallet or wallet['balance_nano_gbp'] >= 200*usage_wallet.NANO_PER_PENNY
                or wallet['debt_nano_gbp'] or wallet['reconciliation_hold']):
            return None
        if db.execute("SELECT 1 FROM usage_wallet_reservations WHERE tenant=? AND (status IN('unknown','overrun') OR (status='pending' AND created_utc<?)) LIMIT 1",(tenant,usage_wallet._pending_cutoff())).fetchone():
            return None
        if db.execute("SELECT 1 FROM usage_wallet_payments WHERE tenant=? AND dispute_open=1 LIMIT 1",(tenant,)).fetchone():
            return None
        pending = db.execute("SELECT reference FROM ai_budget_recharges WHERE tenant=? AND status IN('reserved','dispatching','processing','requires_action','unknown') LIMIT 1",(tenant,)).fetchone()
        if pending:
            return pending['reference']
        month = store.month_key()
        if store.monthly_reserved(db,tenant,month)+500 > settings['recharge_cap_pence']:
            store.notify(db,tenant,'recharge_cap','cap:'+month,{'cap_pence':settings['recharge_cap_pence']},email=True)
            return None
        reference = secrets.token_hex(24)
        vat = subscriptions.vat_percent()
        subtotal = int((Decimal(500)*100/(100+vat)).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        db.execute("INSERT INTO ai_budget_recharges(reference,tenant,authorisation,month,amount_pence,credit_pence,subtotal_pence,tax_pence,vat_percent,customer,payment_method,livemode,status,created,updated) VALUES (?,?,?,?,500,500,?,?,?,?,?,?,'reserved',?,?)",
            (reference,tenant,authorisation['id'],month,subtotal,500-subtotal,vat,authorisation['customer'],authorisation['payment_method'],authorisation['livemode'],time.time(),time.time()))
        store.audit(db,tenant,'recharge_reserved','budget_worker',{'reference':reference,'amount_pence':500,'month':month})
    try:
        applications.reserve_payment(tenant,reference,RECHARGE_KIND)
    except Exception:
        with store.connection(tenant,write=True) as db:
            db.execute("UPDATE ai_budget_recharges SET status='cancelled',updated=? WHERE tenant=? AND reference=? AND attempts=0",(time.time(),tenant,reference))
        raise
    return reference


def _recharge_row(tenant,reference,db=None):
    if db is None:
        with store.connection(tenant) as handle:
            return _recharge_row(tenant,reference,handle)
    row = db.execute('SELECT * FROM ai_budget_recharges WHERE tenant=? AND reference=?',(tenant,reference)).fetchone()
    if not row:
        raise budget.BudgetError('budget_payment_not_found',404)
    return dict(row)


def process_recharge(tenant,reference):
    row = _recharge_row(tenant,reference)
    if row['status'] in ('succeeded','failed','cancelled','requires_action'):
        return False
    if row['payment_id']:
        reconcile_payment(tenant,reference,row['payment_id'])
        return True
    if not budget.live_recharge_allowed():
        return False
    budget.require_eligible(tenant)
    from service.ai_provider_funding import health
    if health(tenant)['status'] in {'funding_exhausted','usage_limit'}:
        return False
    # Recover an interrupted reservation before any provider side effect.
    applications.reserve_payment(tenant,reference,RECHARGE_KIND)
    row=_claim_dispatch(tenant,reference)
    if row is None:
        return False
    if row['status']=='cancelled':
        applications.expire_budget_permit(tenant,reference)
        return False
    metadata = {'tenant':tenant,'kind':RECHARGE_KIND,'budget_ref':reference,'budget_authorisation':row['authorisation'],'budget_version':VERSION}
    data = {'amount':500,'currency':'gbp','customer':row['customer'],'payment_method':row['payment_method'],
        'off_session':'true','confirm':'true','payment_method_types[0]':'card',
        'description':'V7 AI Budget automatic recharge'}
    data.update({'metadata['+key+']':value for key,value in metadata.items()})
    try:
        result = subscriptions.client().stripe_request('POST','/v1/payment_intents',data,idempotency_key='v7-budget-recharge-'+reference)
        payment_id = usage_payments._id(result.get('id'),'pi')
        reconcile_payment(tenant,reference,payment_id)
    except Exception as exc:
        # A declined off-session confirmation can return its intent in HTTP 402.
        # Only the bounded identifier is retained; status/amount are re-fetched.
        intent = getattr(exc,'payment_intent_id',None)
        if intent:
            reconcile_payment(tenant,reference,intent)
            return True
        with store.connection(tenant,write=True) as db:
            db.execute("UPDATE ai_budget_recharges SET status=CASE WHEN status='dispatching' THEN 'unknown' ELSE status END,updated=? WHERE tenant=? AND reference=?",(time.time(),tenant,reference))
        raise
    return True


def _claim_dispatch(tenant,reference):
    # Match ledger lock order: wallet first, then settings. A concurrent manual
    # top-up must commit before this final balance check or after dispatch starts.
    with usage_wallet._connection(tenant,write=True) as db:
        wallet=usage_wallet._locked_wallet(db,tenant)
        store.schema(db)
        current=store.ensure_settings(db,tenant)
        row=_recharge_row(tenant,reference,db)
        if (row['status'] not in ('reserved','dispatching','unknown') or not current['recharge_enabled']
                or current['authorisation']!=row['authorisation'] or row['lease_until']>time.time()):
            return None
        auth=db.execute('SELECT * FROM ai_budget_authorisations WHERE tenant=? AND id=?',(tenant,row['authorisation'])).fetchone()
        if not auth or auth['status']!='active' or not _actor_valid(dict(auth)):
            return None
        if row['created']<time.time()-23*3600 or row['attempts']>=3:
            db.execute("UPDATE ai_budget_recharges SET status='unknown',failure_code='needs_review',lease_until=?,updated=? WHERE tenant=? AND reference=?",(time.time()+86400,time.time(),tenant,reference))
            store.notify(db,tenant,'payment_review','review:'+reference,{},email=True)
            return None
        month=store.month_key()
        if row['attempts']==0:
            held=db.execute("SELECT 1 FROM usage_wallet_reservations WHERE tenant=? AND (status IN('unknown','overrun') OR (status='pending' AND created_utc<?)) LIMIT 1",(tenant,usage_wallet._pending_cutoff())).fetchone()
            disputed=db.execute('SELECT 1 FROM usage_wallet_payments WHERE tenant=? AND dispute_open=1 LIMIT 1',(tenant,)).fetchone()
            no_longer_needed=(wallet['balance_nano_gbp']>=200*usage_wallet.NANO_PER_PENNY
                or wallet['debt_nano_gbp'] or wallet['reconciliation_hold'] or held or disputed)
            cap_changed=row['month']!=month and store.monthly_reserved(db,tenant,month)+500>current['recharge_cap_pence']
            if no_longer_needed or cap_changed:
                db.execute("UPDATE ai_budget_recharges SET status='cancelled',updated=? WHERE tenant=? AND reference=?",(time.time(),tenant,reference))
                return {**row,'status':'cancelled'}
            if row['month']!=month:
                db.execute('UPDATE ai_budget_recharges SET month=? WHERE tenant=? AND reference=?',(month,tenant,reference))
        db.execute("UPDATE ai_budget_recharges SET status='dispatching',attempts=attempts+1,lease_until=?,updated=? WHERE tenant=? AND reference=?",(time.time()+120,time.time(),tenant,reference))
        store.audit(db,tenant,'recharge_dispatch_started','budget_worker',{'reference':reference,'attempt':row['attempts']+1})
        return row


def reconcile_payment(tenant,reference,payment_id,*,event_id='',canonical_dispute=None):
    row = _recharge_row(tenant,reference)
    stripe = subscriptions.client()
    payment_id = usage_payments._id(payment_id,'pi')
    payment = stripe.stripe_request('GET','/v1/payment_intents/'+payment_id)
    usage_payments._common(payment,row,'pi',payment_id)
    usage_payments._require_payment_mode(bool(row['livemode']))
    metadata = payment.get('metadata') or {}
    expected = {'tenant':tenant,'kind':RECHARGE_KIND,'budget_ref':reference,'budget_authorisation':row['authorisation'],'budget_version':VERSION}
    if (any(metadata.get(key) != value for key,value in expected.items())
            or payment.get('customer') != row['customer'] or payment.get('payment_method') != row['payment_method']
            or payment.get('amount') != 500 or type(payment.get('amount')) is not int):
        raise budget.BudgetError('budget_payment_mismatch')
    if payment.get('status')=='canceled' and row['status']=='cancelled' and row['payment_id']==payment_id:
        return False  # Already verified and its permit expired; harmless replay.
    applications.verify_payment(tenant,reference,RECHARGE_KIND)
    with store.connection(tenant,write=True) as db:
        current = _recharge_row(tenant,reference,db)
        if current['payment_id'] and current['payment_id'] != payment_id:
            raise budget.BudgetError('budget_payment_mismatch')
        db.execute('UPDATE ai_budget_recharges SET payment_id=?,updated=? WHERE tenant=? AND reference=?',(payment_id,time.time(),tenant,reference))
    from service.business_applications import bind_budget_payment
    bind_budget_payment(tenant,reference,payment_id)
    status = payment.get('status')
    if status != 'succeeded':
        if status not in {'canceled','requires_action','requires_payment_method','processing','requires_confirmation','requires_capture'}:
            raise budget.BudgetError('budget_provider_response_invalid',503)
        state = 'cancelled' if status == 'canceled' else 'requires_action' if status in ('requires_action','requires_payment_method') else 'processing'
        failure = 'authentication_required' if status == 'requires_action' else 'payment_failed' if status == 'requires_payment_method' else ''
        with store.connection(tenant,write=True) as db:
            db.execute("UPDATE ai_budget_recharges SET status=?,failure_code=?,lease_until=?,updated=? WHERE tenant=? AND reference=? AND status!='succeeded'",(state,failure,time.time()+30,time.time(),tenant,reference))
            if failure:
                db.execute('UPDATE ai_budget_settings SET blocked_reason=? WHERE tenant=?',(failure,tenant))
                store.notify(db,tenant,failure,failure+':'+reference,{},email=True)
        if state == 'cancelled':
            applications.expire_budget_permit(tenant,reference)
        return False
    usage_payments._integer(payment.get('amount_received'),500)
    charge_id = usage_payments._id(payment.get('latest_charge'),'ch')
    charge = stripe.stripe_request('GET','/v1/charges/'+charge_id)
    usage_payments._common(charge,row,'ch',charge_id)
    if (charge.get('payment_intent') != payment_id or charge.get('customer') != row['customer']
            or charge.get('paid') is not True or charge.get('captured') is not True or charge.get('status') != 'succeeded'):
        raise budget.BudgetError('budget_payment_mismatch')
    usage_payments._integer(charge.get('amount'),500)
    usage_payments._integer(charge.get('amount_captured'),500)
    refunded = usage_payments._integer(charge.get('amount_refunded'))
    if refunded>500:
        raise budget.BudgetError('budget_payment_mismatch')
    disputed,states = usage_payments._disputed(stripe,charge,row,canonical_dispute)
    receipt = subscriptions._safe_url(charge.get('receipt_url'),'pay.stripe.com') or ''
    usage_wallet.apply_payment(tenant,reference,payment_id,500,500,receipt_url=receipt,
        refunded_pence=refunded,disputed=disputed,dispute_states=states,event_id=event_id)
    with store.connection(tenant,write=True) as db:
        db.execute("UPDATE ai_budget_recharges SET status='succeeded',charge_id=?,failure_code='',updated=? WHERE tenant=? AND reference=?",(charge_id,time.time(),tenant,reference))
        store.notify(db,tenant,'recharge_succeeded','paid:'+reference,{'amount_pence':500},email=True)
    applications.settle_payment(tenant,reference)
    return True


def cancel_recharge(tenant,reference):
    """Resolve before replacing consent or withdrawing business approval.

    Ambiguous creations remain held for review, never assumed not to have charged.
    """
    row = _recharge_row(tenant,reference)
    if row['status'] in ('failed','cancelled') and not row['payment_id']:
        applications.expire_budget_permit(tenant,reference)
        return True
    if not row['payment_id']:
        with store.connection(tenant,write=True) as db:
            row = _recharge_row(tenant,reference,db)
            if row['attempts'] or row['payment_id']:
                raise budget.BudgetError('budget_payment_needs_review',409)
            db.execute("UPDATE ai_budget_recharges SET status='cancelled',updated=? WHERE tenant=? AND reference=?",(time.time(),tenant,reference))
        applications.expire_budget_permit(tenant,reference)
        return True
    stripe = subscriptions.client()
    intent = stripe.stripe_request('GET','/v1/payment_intents/'+usage_payments._id(row['payment_id'],'pi'))
    usage_payments._common(intent,row,'pi',row['payment_id'])
    if intent.get('status') in {'requires_action','requires_payment_method','requires_confirmation','requires_capture'}:
        stripe.stripe_request('POST','/v1/payment_intents/'+row['payment_id']+'/cancel',
            idempotency_key='v7-budget-cancel-'+reference)
    reconcile_payment(tenant,reference,row['payment_id'])
    current = _recharge_row(tenant,reference)
    if current['status'] not in {'succeeded','cancelled','failed'}:
        raise budget.BudgetError('budget_payment_in_progress',409)
    return True


def handle_event(event):
    """Called only after the shared webhook has verified the Stripe signature."""
    kind = event.get('type')
    obj = (event.get('data') or {}).get('object')
    if not isinstance(obj,dict):
        return False
    metadata = obj.get('metadata') or {}
    if not isinstance(metadata,dict):
        metadata = {}
    if kind in {'checkout.session.completed','checkout.session.async_payment_succeeded'} and metadata.get('kind') == SETUP_KIND:
        row = _setup_row(metadata)
        if row['status'] in {'revoked','failed'} or not budget.live_recharge_allowed() or not _actor_valid(row):
            return True  # Saving a card is not a payment; never revive withdrawn consent.
        try:
            budget.require_eligible(row['tenant'])
        except (budget.BudgetError,applications.ApplicationError):
            return True
        confirm_authorisation(row['tenant'],obj.get('id'))
        return True
    if isinstance(kind,str) and kind.startswith('payment_intent.') and metadata.get('kind') == RECHARGE_KIND:
        row = _event_recharge(metadata)
        reconcile_payment(row['tenant'],row['reference'],obj.get('id'),event_id=event.get('id',''))
        return True
    if kind not in usage_payments._REVERSALS:
        return False
    stripe = subscriptions.client()
    dispute = None
    if kind.startswith('charge.dispute.'):
        dispute = stripe.stripe_request('GET','/v1/disputes/'+usage_payments._id(obj.get('id'),'dp'))
        charge_id = usage_payments._id(dispute.get('charge'),'ch')
    elif kind.startswith('refund.'):
        refund = stripe.stripe_request('GET','/v1/refunds/'+usage_payments._id(obj.get('id'),'re'))
        charge_id = usage_payments._id(refund.get('charge'),'ch')
    else:
        charge_id = usage_payments._id(obj.get('id'),'ch')
    charge = stripe.stripe_request('GET','/v1/charges/'+charge_id)
    payment_id = usage_payments._id(charge.get('payment_intent'),'pi')
    intent = stripe.stripe_request('GET','/v1/payment_intents/'+payment_id)
    metadata = intent.get('metadata') or {}
    if metadata.get('kind') != RECHARGE_KIND:
        return False
    row = _event_recharge(metadata)
    reconcile_payment(row['tenant'],row['reference'],payment_id,event_id=event.get('id',''),canonical_dispute=dispute)
    return True


def _event_recharge(metadata):
    from retrieval.storage import Storage
    tenant,reference = metadata.get('tenant'),metadata.get('budget_ref')
    try:
        Storage.validate_tenant_key(tenant)
    except (ValueError,TypeError):
        raise budget.BudgetError('budget_payment_mismatch') from None
    if not isinstance(reference,str) or not re.fullmatch(r'[0-9a-f]{48}',reference) or metadata.get('budget_version') != VERSION:
        raise budget.BudgetError('budget_payment_mismatch')
    return _recharge_row(tenant,reference)
