"""Operator-only observations. Unknown expenses are never reported as zero."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from service import ai_budget_store as store, usage_wallet


def operations(storage):
    from service.security import management_user
    management_user(platform_only=True)
    totals={key:0 for key in ('balance_nano_gbp','reserved_nano_gbp','debt_nano_gbp','usage_deductions_nano_gbp',
        'gross_received_pence','refunded_pence','fees_pence','payments','costed_payments','unknown_usage',
        'pending_topups','failed_topups','open_disputes','reconciliation_holds')}
    provider_gbp=Decimal(0)
    provider_usd=0
    models={}
    since=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    week=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
    recent,previous=Decimal(0),Decimal(0)
    for tenant in storage.tenant_keys():
        # Every read runs with the existing scoped backend transaction and RLS.
        usage_wallet.report(tenant,include_costs=False)
        with store.connection(tenant) as db:
            wallet=db.execute('SELECT * FROM usage_wallets WHERE tenant=?',(tenant,)).fetchone()
            if wallet:
                for key in ('balance_nano_gbp','reserved_nano_gbp','debt_nano_gbp'):
                    totals[key]+=wallet[key]
                totals['reconciliation_holds']+=int(bool(wallet['reconciliation_hold']))
            rows=db.execute('SELECT status,cost_nano_usd,fx_rate,charged_nano_gbp,metadata_json,created_utc FROM usage_wallet_reservations WHERE tenant=?',(tenant,)).fetchall()
            for row in rows:
                if row['cost_nano_usd'] is None:
                    totals['unknown_usage']+=1
                    continue
                cost=Decimal(row['cost_nano_usd'])*Decimal(row['fx_rate'])
                provider_gbp+=cost
                provider_usd+=row['cost_nano_usd']
                if row['created_utc']>=since:
                    recent+=cost
                elif row['created_utc']>=week:
                    previous+=cost
                charged=(row['charged_nano_gbp'] or 0) if row['status']=='settled' else 0
                totals['usage_deductions_nano_gbp']+=charged
                import json
                metadata=json.loads(row['metadata_json'])
                model=metadata.get('requested_model') or 'unattributed'
                if not isinstance(model,str) or len(model)>120:
                    model='unattributed'
                part=models.setdefault(model,{'charged_nano_gbp':0,'provider_cost_nano_gbp':Decimal(0),'calls':0})
                part['calls']+=1
                part['charged_nano_gbp']+=charged
                part['provider_cost_nano_gbp']+=cost
            for row in db.execute('SELECT paid_pence,refunded_pence,dispute_open FROM usage_wallet_payments WHERE tenant=?',(tenant,)):
                totals['payments']+=1
                totals['gross_received_pence']+=row['paid_pence']
                totals['refunded_pence']+=row['refunded_pence']
                totals['open_disputes']+=int(bool(row['dispute_open']))
            cost=db.execute('SELECT COUNT(*) count,COALESCE(SUM(fee_pence),0) fees FROM ai_budget_payment_costs WHERE tenant=?',(tenant,)).fetchone()
            totals['costed_payments']+=cost['count']
            totals['fees_pence']+=cost['fees']
            for row in db.execute('SELECT status,COUNT(*) count FROM ai_budget_recharges WHERE tenant=? GROUP BY status',(tenant,)):
                if row['status'] in {'failed','requires_action'}:
                    totals['failed_topups']+=row['count']
                elif row['status'] in {'reserved','dispatching','processing','unknown'}:
                    totals['pending_topups']+=row['count']
    from service import ai_provider_funding as funding
    policy=funding.settings()
    warnings=[]
    if totals['unknown_usage'] or totals['reconciliation_holds']:
        warnings.append('unconfirmed_usage_requires_reconciliation')
    if totals['open_disputes']:
        warnings.append('payment_disputes_open')
    fees_complete=totals['payments']==totals['costed_payments']
    if not fees_complete:
        warnings.append('payment_costs_incomplete')
    declared=policy['owner_reported_reserve_pence']
    target=policy['reserve_target_pence']
    if declared is None or target is None:
        warnings.append('funding_reserve_unverified')
    elif declared<target:
        warnings.append('declared_funding_reserve_below_target')
    model_rows=[]
    for name,part in sorted(models.items()):
        direct=Decimal(part['charged_nano_gbp'])-part['provider_cost_nano_gbp']
        model_rows.append({'model':name,'calls':part['calls'],'usage_deductions_gbp':str(Decimal(part['charged_nano_gbp'])/10**9),
            'provider_cost_gbp_at_usage_fx':str(part['provider_cost_nano_gbp']/10**9),'direct_contribution_before_other_costs_gbp':str(direct/10**9)})
        if direct<0:
            warnings.append('model_cost_exceeds_usage_deductions')
    markup=usage_wallet.markup_percent()
    from service.subscriptions import vat_percent
    example=funding.break_even(policy,markup=markup,vat_percent=vat_percent())
    if example.get('profitable') is False:
        warnings.append('five_pound_recharge_estimated_unprofitable')
    if not example.get('validated'):
        warnings.append('cost_policy_not_financially_validated')
    if recent>10**9 and previous>0 and recent>previous*3/7:
        warnings.append('provider_usage_spike_above_three_times_prior_daily_average')
    return {'scope':'Customer-funded AI operations, all existing tenants; subscription/setup revenue and platform-internal inference are excluded.',
        'usage_deductions_gbp':str(Decimal(totals['usage_deductions_nano_gbp'])/10**9),
        'provider_cost_usd':str(Decimal(provider_usd)/10**9),
        'provider_cost_gbp_at_usage_fx':str(provider_gbp/10**9),
        'prepaid_liability_gbp':str(Decimal(totals['balance_nano_gbp'])/10**9),
        'reserved_usage_gbp':str(Decimal(totals['reserved_nano_gbp'])/10**9),
        'customer_debt_gbp':str(Decimal(totals['debt_nano_gbp'])/10**9),
        'gross_payments_pence':totals['gross_received_pence'],'refunded_pence':totals['refunded_pence'],
        'observed_stripe_fees_pence':totals['fees_pence'] if fees_complete else None,
        'partial_observed_stripe_fees_pence':totals['fees_pence'],'costed_payments':totals['costed_payments'],
        'payments':totals['payments'],'climate_expenditure_pence':None,'actual_fx_fees_pence':None,
        'net_accounting_profit_gbp':None,'available_stripe_cash_pence':None,
        'owner_reported_reserve_pence':declared,'reserve_target_pence':target,'reserve_is_verified':False,
        'unknown_usage':totals['unknown_usage'],'pending_topups':totals['pending_topups'],'failed_topups':totals['failed_topups'],
        'recent_24h_provider_cost_gbp':str(recent/10**9),'prior_seven_day_daily_average_gbp':str(previous/7/10**9),
        'models':model_rows,'warnings':sorted(set(warnings)),
        'limits':'Usage FX is the request snapshot, not verified card FX. Stripe settlement fees are delayed. Climate, actual FX, tax allocations, refunds/dispute fees and infrastructure must be reconciled separately; no net-profit claim is made.'}
