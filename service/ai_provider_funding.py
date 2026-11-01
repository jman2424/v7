"""Official read-only provider monitoring and private cost-policy analysis.

No OpenAI credit-balance, card, purchase or auto-recharge API is assumed. Provider
costs are delayed observations; a manual reserve declaration is never a verified
OpenAI balance. None of these settings changes a customer's agreed usage price.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from threading import Lock

from service import ai_budget_store as store, session_store, usage_wallet

BILLING_URL = 'https://platform.openai.com/settings/organization/billing/overview'
USAGE_URL = 'https://platform.openai.com/usage'
DEFAULTS = {'reserve_target_pence':None,'owner_reported_reserve_pence':None,
    'stripe_percent_bps':None,'stripe_fixed_pence':None,'climate_bps':None,
    'fx_cost_bps':None,'refund_dispute_risk_bps':None,'infrastructure_bps':None,
    'target_margin_bps':None,'financial_review_completed':False,'updated_by':'','updated':None}
KNOWN_BILLING_ERRORS = {'credit_balance_exhausted','insufficient_quota','usage_limit_reached',
    'organization_spend_limit_exceeded','project_spend_limit_exceeded'}
_health_cache, _cache_lock = {}, Lock()


class _NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError('provider_monitoring_redirect_refused')


def _cache_key():
    from flask import current_app, has_app_context
    return (os.getpid(),os.getenv('SECURITY_DB_PATH',''),id(current_app._get_current_object()) if has_app_context() else 0)


def _invalidate_health():
    with _cache_lock:
        _health_cache.pop(_cache_key(),None)


def _platform_tenant():
    from flask import current_app
    return current_app.container.settings.PLATFORM_MARKETING_TENANT


def settings(tenant=None):
    tenant = tenant or _platform_tenant()
    with store.connection(tenant) as db:
        row = db.execute('SELECT value FROM ai_provider_funding_settings WHERE id=1').fetchone()
    return {**DEFAULTS, **json.loads(row['value'])} if row else dict(DEFAULTS)


def save_settings(data, actor):
    from service.security import management_user
    management_user(platform_only=True)
    allowed = set(DEFAULTS)-{'updated_by','updated'}
    if not isinstance(data,dict) or set(data)-allowed:
        raise ValueError('invalid_provider_funding_settings')
    value = settings()
    for name,amount in data.items():
        if name == 'financial_review_completed':
            if type(amount) is not bool:
                raise ValueError('invalid_provider_funding_settings')
        elif amount is not None and (type(amount) is not int or not 0<=amount<=(100_000_000 if name.endswith('pence') else 10000)):
            raise ValueError('invalid_provider_funding_settings')
        value[name] = amount
    if value['target_margin_bps'] is not None and value['target_margin_bps'] >= 10000:
        raise ValueError('invalid_provider_funding_settings')
    value.update(updated_by=actor,updated=time.time())
    with store.connection(_platform_tenant(),write=True,operator=True) as db:
        db.execute('INSERT INTO ai_provider_funding_settings VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value,updated=excluded.updated',
            (json.dumps(value,sort_keys=True,allow_nan=False),time.time()))
        store.audit(db,_platform_tenant(),'provider_funding_assumptions_changed',actor,{key:value[key] for key in sorted(data)})
    return value


def safe_identifier(name):
    value = os.getenv(name,'')
    return value if re.fullmatch(r'[A-Za-z0-9_-]{1,160}',value) else None


def _get(path, params=None):
    from urllib.parse import urlencode
    project=safe_identifier('OPENAI_PROJECT_ID') or safe_identifier('OPENAI_PROJECT')
    allowed={'/v1/organization/costs','/v1/organization/spend_limit'}
    if project:
        allowed.add('/v1/organization/projects/'+project+'/spend_limit')
    if path not in allowed:
        raise ValueError('unsupported_provider_monitoring_endpoint')
    secret = os.getenv('OPENAI_ADMIN_KEY','')
    if not secret:
        raise ValueError('provider_cost_monitoring_not_configured')
    url = 'https://api.openai.com'+path+('?' + urlencode(params or {},doseq=True) if params else '')
    request = urllib.request.Request(url,headers={'Authorization':'Bearer '+secret,'Accept':'application/json'})
    with urllib.request.build_opener(_NoCredentialRedirect()).open(request,timeout=8) as response:
        raw = response.read(1_048_577)
        if len(raw)>1_048_576:
            raise ValueError('invalid_provider_monitoring_response')
    result = json.loads(raw)
    if not isinstance(result,dict):
        raise ValueError('invalid_provider_monitoring_response')
    return result


def sync_limits():
    project=safe_identifier('OPENAI_PROJECT_ID') or safe_identifier('OPENAI_PROJECT')
    sources=[('organisation','/v1/organization/spend_limit','organization.spend_limit')]
    if project:
        sources.append(('project','/v1/organization/projects/'+project+'/spend_limit','project.spend_limit'))
    observations=[]
    for scope,path,object_type in sources:
        try:
            result=_get(path)
            enforcement=result.get('enforcement')
            if (result.get('object')!=object_type or result.get('currency')!='USD' or result.get('interval')!='month'
                    or type(result.get('threshold_amount')) is not int or result['threshold_amount']<0
                    or not isinstance(enforcement,dict) or enforcement.get('status') not in {'inactive','enforcing'}):
                raise ValueError('invalid_provider_monitoring_response')
            value={'available':True,'threshold_cents_usd':result['threshold_amount'],'interval':'month',
                'enforcement':enforcement['status'],'source':'official_openai_spend_limit','project_id':project if scope=='project' else None}
        except Exception:
            # No unsupported fallback or inferred zero limit. Preserve the older
            # observation separately and clearly mark this read unavailable.
            value={'available':False,'source':'official_openai_spend_limit'}
        observations.append((scope,json.dumps(value,sort_keys=True),time.time()))
    with store.connection(_platform_tenant(),write=True) as db:
        for row in observations:
            db.execute('INSERT INTO ai_provider_limit_snapshots VALUES (?,?,?) ON CONFLICT(scope) DO UPDATE SET value=excluded.value,observed=excluded.observed',row)
    return {'ok':True,'scopes':len(observations)}


def sync_costs(*, days=7):
    if type(days) is not int or not 1<=days<=90:
        raise ValueError('invalid_provider_monitoring_period')
    end = datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    params = {'start_time':int((end-timedelta(days=days)).timestamp()),'end_time':int(end.timestamp()),
        'bucket_width':'1d','limit':days,'group_by':['project_id']}
    project = safe_identifier('OPENAI_PROJECT_ID') or safe_identifier('OPENAI_PROJECT')
    if project:
        params['project_ids'] = [project]
    records, pages = [], set()
    for _ in range(12):
        response = _get('/v1/organization/costs',params)
        if not isinstance(response.get('data'),list):
            raise ValueError('invalid_provider_monitoring_response')
        for bucket in response['data']:
            if (not isinstance(bucket,dict) or type(bucket.get('start_time')) is not int
                    or type(bucket.get('end_time')) is not int or not isinstance(bucket.get('results'),list)):
                raise ValueError('invalid_provider_monitoring_response')
            if not params['start_time']<=bucket['start_time']<bucket['end_time']<=params['end_time']:
                raise ValueError('invalid_provider_monitoring_response')
            if not bucket['results']:
                records.append((bucket['start_time'],bucket['end_time'],'official_openai_costs','usd','0',project or ''))
            for row in bucket['results']:
                amount = row.get('amount') if isinstance(row,dict) else None
                if not isinstance(amount,dict) or amount.get('currency') != 'usd':
                    raise ValueError('invalid_provider_monitoring_response')
                try:
                    cost = Decimal(str(amount.get('value')))
                except InvalidOperation:
                    raise ValueError('invalid_provider_monitoring_response') from None
                if not cost.is_finite() or abs(cost)>Decimal('1000000000'):
                    raise ValueError('invalid_provider_monitoring_response')
                project_id = row.get('project_id') or ''
                if not isinstance(project_id,str) or len(project_id)>160 or (project and project_id != project):
                    raise ValueError('invalid_provider_monitoring_response')
                records.append((bucket['start_time'],bucket['end_time'],'official_openai_costs','usd',str(cost),project_id))
        if not response.get('has_more'):
            break
        page = response.get('next_page')
        if not isinstance(page,str) or not 0<len(page)<=1000 or page in pages:
            raise ValueError('invalid_provider_monitoring_response')
        pages.add(page)
        params['page'] = page
    else:
        raise ValueError('provider_cost_monitoring_incomplete')
    totals = {}
    for start,end,source,currency,amount,project_id in records:
        key = (start,end,source,currency,project_id)
        totals[key] = totals.get(key,Decimal(0))+Decimal(amount)
    with store.connection(_platform_tenant(),write=True) as db:
        for key,amount in totals.items():
            identifier = hashlib.sha256(json.dumps(key).encode()).hexdigest()
            db.execute('INSERT INTO ai_provider_cost_snapshots VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(start_utc,end_utc,source,currency,project_id) DO UPDATE SET amount_decimal=excluded.amount_decimal,observed=excluded.observed',
                (identifier,*key[:4],str(amount),key[4],time.time()))
    return {'ok':True,'buckets':len(totals),'source':'official_openai_costs','balance_available':False}


def health(tenant=None, *, cached=False):
    tenant = tenant or _platform_tenant()
    key = _cache_key()
    if cached:
        with _cache_lock:
            saved = _health_cache.get(key)
            if saved and saved[0]>time.monotonic():
                return dict(saved[1])
    with store.connection(tenant) as db:
        row = db.execute('SELECT status,error_code,observed,retry_after FROM ai_provider_health WHERE id=1').fetchone()
    result = dict(row) if row else {'status':'unknown','error_code':'','observed':None,'retry_after':0}
    if cached:
        with _cache_lock:
            if len(_health_cache)>32:
                _health_cache.clear()
            _health_cache[key] = (time.monotonic()+1,result)
    return result


def classify(error):
    from openai import APIStatusError
    if not isinstance(error,APIStatusError) or error.status_code != 429:
        return None
    from service.api_usage import _field
    body = _field(error,'body',{})
    body = _field(body,'error',body)
    code = _field(body,'code') or _field(body,'type')
    if code in KNOWN_BILLING_ERRORS:
        return ('funding_exhausted' if code in {'credit_balance_exhausted','insufficient_quota'} else 'usage_limit'),code
    return None


def record_error(error,tenant):
    result = classify(error)
    if not result:
        return
    status,code = result
    with store.connection(tenant,write=True) as db:
        db.execute('INSERT INTO ai_provider_health VALUES (1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,error_code=excluded.error_code,observed=excluded.observed,retry_after=excluded.retry_after',
            (status,code,time.time(),time.time()+30))
    _invalidate_health()


def record_success(tenant):
    if health(tenant,cached=True)['status'] == 'available':
        return
    with store.connection(tenant,write=True) as db:
        # A successful paid API response demonstrates recovery, not a verified
        # balance, successful recharge, or remaining organisation spend limit.
        db.execute("INSERT INTO ai_provider_health VALUES (1,'available','',?,0) ON CONFLICT(id) DO UPDATE SET status='available',error_code='',observed=excluded.observed,retry_after=0 WHERE ai_provider_health.status!='available'",(time.time(),))
    _invalidate_health()


def allow_request(tenant):
    current = health(tenant,cached=True)
    if current['status'] not in {'funding_exhausted','usage_limit'}:
        return True
    with store.connection(tenant,write=True) as db:
        row = db.execute('SELECT * FROM ai_provider_health WHERE id=1'+(' FOR UPDATE' if session_store._using_postgres() else '')).fetchone()
        if not row or row['status'] not in {'funding_exhausted','usage_limit'}:
            return True
        if row['retry_after']>time.time():
            return False
        # One bounded probe per cooldown; an outage cannot create a request storm.
        db.execute('UPDATE ai_provider_health SET retry_after=? WHERE id=1',(time.time()+30,))
        return True


def break_even(policy, *, amount_pence=500, vat_percent=0, markup=None):
    required = ('stripe_percent_bps','stripe_fixed_pence','climate_bps','fx_cost_bps',
                'refund_dispute_risk_bps','infrastructure_bps','target_margin_bps')
    missing = [name for name in required if policy.get(name) is None]
    if missing or markup is None:
        return {'validated':False,'missing':missing+(['usage_markup'] if markup is None else []),'amount_pence':amount_pence}
    cash = Decimal(amount_pence)
    net = cash*100/(100+vat_percent)
    fee = (cash*Decimal(policy['stripe_percent_bps'])/10000+policy['stripe_fixed_pence']).quantize(Decimal(1),rounding=ROUND_CEILING)
    climate = cash*Decimal(policy['climate_bps'])/10000
    overhead = net*sum(Decimal(policy[name]) for name in ('fx_cost_bps','refund_dispute_risk_bps','infrastructure_bps'))/10000
    provider = cash/(1+Decimal(str(markup))/100)
    contribution = net-fee-climate-overhead-provider
    maximum_provider = net*(1-Decimal(policy['target_margin_bps'])/10000)-fee-climate-overhead
    minimum_markup = ((cash/maximum_provider-1)*100) if maximum_provider>0 else None
    return {'validated':bool(policy.get('financial_review_completed')),'amount_pence':amount_pence,
        'net_revenue_pence':str(net),'processing_fee_pence':str(fee),'climate_pence':str(climate),
        'other_overhead_pence':str(overhead),'estimated_provider_cost_pence':str(provider),
        'gross_contribution_pence':str(contribution),'profitable':contribution>=0,
        'minimum_markup_for_target_percent':str(minimum_markup.quantize(Decimal('0.01'))) if minimum_markup is not None else None,
        'assumption':'Full advertised balance consumed at the current usage markup; configured fees and overhead estimates, not a verified future margin.'}


def report():
    from service.security import management_user
    from service.subscriptions import vat_percent
    management_user(platform_only=True)
    tenant = _platform_tenant()
    value = settings(tenant)
    project=safe_identifier('OPENAI_PROJECT_ID') or safe_identifier('OPENAI_PROJECT')
    with store.connection(tenant) as db:
        snapshots = [dict(row) for row in db.execute('SELECT start_utc,end_utc,currency,amount_decimal,project_id,observed FROM ai_provider_cost_snapshots'+(' WHERE project_id=?' if project else '')+' ORDER BY start_utc DESC LIMIT 90',(project,) if project else ())]
        limits=[{'scope':row['scope'],'observed':row['observed'],**json.loads(row['value'])} for row in db.execute('SELECT * FROM ai_provider_limit_snapshots ORDER BY scope')]
    try:
        markup = str(usage_wallet.markup_percent())
    except usage_wallet.UsagePaused:
        markup = None
    return {'provider':'OpenAI','organisation_id':safe_identifier('OPENAI_ORG_ID') or safe_identifier('OPENAI_ORGANIZATION'),
        'project_id':safe_identifier('OPENAI_PROJECT_ID') or safe_identifier('OPENAI_PROJECT'),
        'official_cost_monitoring_configured':bool(os.getenv('OPENAI_ADMIN_KEY')),
        'provider_balance':None,'balance_status':'No supported balance endpoint is configured. View the official billing dashboard.',
        'billing_settings_url':BILLING_URL,'usage_url':USAGE_URL,'health':health(tenant),'settings':value,
        'cost_observations':snapshots,'spend_limit_observations':limits,'usage_markup_percent':markup,
        'recharge_break_even':break_even(value,markup=markup,vat_percent=vat_percent()),
        'funding_separation':'Stripe receipts and customer AI balances do not replenish OpenAI. Configure provider auto-recharge and its limits in OpenAI billing settings.',
        'cost_warning':'Official cost observations can be delayed and can include other projects if no project filter is configured. They do not establish available cash or provider credit.'}
