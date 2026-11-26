"""Owner-authorized changes; Stripe confirms prices, payment and cancellation.

Moves to a higher plan or a longer interval are charged now through Stripe's
hosted confirmation. Moves to a lower plan or a shorter interval are scheduled
for the renewal date with a Stripe subscription schedule; nothing is charged
today and the current plan stays until then.
"""
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlencode

from service import plan_catalog, subscriptions
from service.plan_catalog import INTERVALS, PLANS, get_plan, price_pence

PLAN_RANK = {plan_id: rank for rank, plan_id in enumerate(PLANS)}
INTERVAL_RANK = {interval: rank for rank, interval in enumerate(INTERVALS)}
# A scheduled change may be confirmed up to this long after its renewal date
# (Stripe retries a failed renewal for several days).
SCHEDULE_WINDOW = 30 * 86400


def schema(db):
    if subscriptions.session_store._using_postgres():
        return
    db.execute('CREATE TABLE IF NOT EXISTS billing_plan_changes ('
               'ref TEXT PRIMARY KEY, tenant TEXT NOT NULL, billing_ref TEXT NOT NULL, '
               'subscription TEXT NOT NULL, from_plan TEXT NOT NULL, plan_id TEXT NOT NULL, '
               'price_id TEXT NOT NULL, setup_plan TEXT NOT NULL, status TEXT NOT NULL, '
               'created INTEGER NOT NULL, expires INTEGER NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS billing_plan_changes_lookup '
               'ON billing_plan_changes(tenant,subscription,billing_ref,price_id,status)')


def _identifier(value, prefix):
    return isinstance(value, str) and bool(re.fullmatch(prefix + r'_[A-Za-z0-9]+', value))


def _price(item):
    price = item.get('price')
    return price if isinstance(price, dict) else {}


def _valid_price(price, plan, interval='month'):
    recurring = price.get('recurring') or {}
    return (price.get('currency') == 'gbp' and type(price.get('unit_amount')) is int
            and price['unit_amount'] == price_pence(plan, interval)
            and price.get('tax_behavior') == 'exclusive'
            and recurring.get('interval') == interval
            and recurring.get('interval_count', 1) == 1
            and recurring.get('usage_type', 'licensed') == 'licensed')


def _invoice_price(line):
    price = line.get('price')
    if isinstance(price, dict):
        return price.get('id')
    if isinstance(price, str):
        return price
    return ((line.get('pricing') or {}).get('price_details') or {}).get('price')


def applied_interval(db, tenant, billing_ref, subscription_id=None):
    """The interval of the latest paid plan change, else the one chosen at checkout."""
    schema(db)
    if subscription_id:
        row = db.execute("SELECT ref FROM billing_plan_changes WHERE tenant=? AND billing_ref=? AND subscription=? "
                         "AND status='applied' ORDER BY created DESC,ref DESC LIMIT 1",
                         (tenant, billing_ref, subscription_id)).fetchone()
        if row:
            return subscriptions.bound_interval(db, tenant, row['ref'])
    return subscriptions.bound_interval(db, tenant, billing_ref)


def locked_subscription(db, tenant, subscription_id, data):
    schema(db)
    # Serialize every status refresh, including accounts without plan changes.
    # A canonical response obtained before the lock can already be stale.
    if subscriptions.session_store._using_postgres():
        db.execute("SELECT ref FROM billing_contracts WHERE tenant=? AND kind='platform' FOR UPDATE", (tenant,)).fetchone()
    else:
        db.execute('BEGIN IMMEDIATE')
    fresh = subscriptions.client().stripe_request('GET', '/v1/subscriptions/' + subscription_id)
    subscriptions._verify_payment_environment(fresh)
    if (fresh.get('metadata') or {}).get('tenant') != tenant:
        raise ValueError('unknown_billing_reference')
    return fresh


def confirmed_plan(db, tenant, billing_ref, subscription_id, data, original_plan):
    """Keep the checkout binding; prove separately authorized changes and payment."""
    schema(db)
    rows = db.execute('SELECT * FROM billing_plan_changes WHERE tenant=? AND billing_ref=? '
                      'AND subscription=? ORDER BY created DESC,ref DESC',
                      (tenant, billing_ref, subscription_id)).fetchall()
    if not rows:
        return original_plan
    state = db.execute('SELECT active_plan FROM billing_plan_state WHERE tenant=?', (tenant,)).fetchone()
    baseline = (get_plan(state['active_plan']) if state and any(
        row['status'] == 'applied' and row['plan_id'] == state['active_plan'] for row in rows) else original_plan)
    items = (data.get('items') or {}).get('data') or []
    if len(items) != 1 or items[0].get('quantity', 1) != 1:
        raise ValueError('unknown_billing_plan')
    price = _price(items[0])
    matching = [row for row in rows if row['price_id'] == price.get('id') and row['status'] not in {'cancelled', 'failed'}]
    if not matching:
        if not any(row['status'] == 'applied' for row in rows):
            return baseline
        raise ValueError('unknown_billing_plan')
    row = matching[0]
    plan = get_plan(row['plan_id'])
    if not _valid_price(price, plan, subscriptions.bound_interval(db, tenant, row['ref'])):
        raise ValueError('unknown_billing_plan')
    if row['status'] == 'applied' and state and state['active_plan'] == plan['id']:
        return plan
    if row['status'] == 'scheduled' and PLAN_RANK[plan['id']] <= PLAN_RANK[baseline['id']]:
        # Stripe moved the subscription to the scheduled lower (or equal) plan at
        # renewal. Entitlements only go down, so no payment evidence is needed.
        db.execute("UPDATE billing_plan_changes SET status='applied' WHERE tenant=? AND ref=?", (tenant, row['ref']))
        return plan
    invoice = data.get('latest_invoice')
    if isinstance(invoice, str) and _identifier(invoice, 'in'):
        invoice = subscriptions.client().stripe_request('GET', '/v1/invoices/' + invoice)
    if not isinstance(invoice, dict):
        return baseline
    subscriptions._verify_payment_environment(invoice)
    linked = ((invoice.get('parent') or {}).get('subscription_details') or {}).get('subscription') or invoice.get('subscription')
    created = invoice.get('created')
    paid = (invoice.get('status') == 'paid' and invoice.get('currency') == 'gbp'
            and linked == subscription_id and type(created) is int
            and row['created'] - 5 <= created <= row['expires']
            and any(_invoice_price(line) == row['price_id']
                    for line in (invoice.get('lines') or {}).get('data', [])))
    if not paid:
        return baseline
    db.execute("UPDATE billing_plan_changes SET status='applied' WHERE tenant=? AND ref=?", (tenant, row['ref']))
    return plan


def summary(tenant):
    with subscriptions.connection(tenant) as db:
        contract = db.execute("SELECT subscription,status,cancel_at_end FROM billing_contracts "
                              "WHERE tenant=? AND kind='platform'", (tenant,)).fetchone()
    state = subscriptions.plan_state(tenant)
    regular = not subscriptions.internal_business(tenant) and not subscriptions.complimentary_plan(tenant)
    cancel = bool(regular and contract and _identifier(contract['subscription'], 'sub')
                  and contract['status'] in {'active', 'trialing', 'past_due', 'unpaid'})
    scheduled = _scheduled_row(tenant, contract['subscription']) if cancel else None
    return {'can_cancel': cancel and not bool(contract['cancel_at_end']) and not scheduled,
            'can_change_plan': bool(cancel and contract['status'] == 'active' and not scheduled
                                    and not contract['cancel_at_end'] and state and state['active_plan']),
            'can_reactivate': bool(cancel and contract['cancel_at_end'] and contract['status'] != 'unpaid'),
            'scheduled_change': ({'plan_id': scheduled['plan_id'], 'interval': scheduled['interval'],
                                  'effective': scheduled['expires'] - SCHEDULE_WINDOW} if scheduled else None)}


def _scheduled_row(tenant, subscription_id):
    with subscriptions.connection(tenant) as db:
        schema(db)
        row = db.execute("SELECT ref,plan_id,expires FROM billing_plan_changes WHERE tenant=? AND subscription=? "
                         "AND status='scheduled' AND expires>? ORDER BY created DESC,ref DESC LIMIT 1",
                         (tenant, subscription_id, int(time.time()))).fetchone()
        if not row:
            return None
        return {**dict(row), 'interval': subscriptions.bound_interval(db, tenant, row['ref'])}


def _verified_subscription(tenant, *, change=False, allow_schedule=False, allow_cancelling=False):
    if not subscriptions.configured():
        raise ValueError('stripe_setup_required')
    if subscriptions.internal_business(tenant) or subscriptions.complimentary_plan(tenant):
        raise ValueError('subscription_required')
    with subscriptions.connection(tenant) as db:
        contract = db.execute("SELECT * FROM billing_contracts WHERE tenant=? AND kind='platform'", (tenant,)).fetchone()
        if not contract or not _identifier(contract['subscription'], 'sub') or not _identifier(contract['customer'], 'cus'):
            raise ValueError('subscription_required')
        contract = dict(contract)
    data = subscriptions.client().stripe_request('GET', '/v1/subscriptions/' + contract['subscription'])
    subscriptions._verify_payment_environment(data)
    metadata = data.get('metadata') or {}
    if (data.get('id') != contract['subscription'] or data.get('customer') != contract['customer']
            or metadata.get('tenant') != tenant or metadata.get('kind') != 'platform'
            or metadata.get('billing_ref') != contract['ref']):
        raise ValueError('unknown_billing_reference')
    with subscriptions.connection(tenant) as db:
        plan = subscriptions._confirmed_plan(db, metadata, {'tenant': tenant, 'kind': 'platform'})
    if data.get('status') not in {'active', 'trialing', 'past_due', 'unpaid'}:
        raise ValueError('active_platform_subscription_required')
    if (data.get('cancel_at_period_end') or data.get('cancel_at')) and not allow_cancelling:
        raise ValueError('subscription_already_cancelling')
    if data.get('schedule') and not allow_schedule and _settle_applied_schedule(tenant, contract, data):
        data = subscriptions.client().stripe_request('GET', '/v1/subscriptions/' + contract['subscription'])
        subscriptions._verify_payment_environment(data)
        if data.get('id') != contract['subscription'] or (data.get('metadata') or {}).get('tenant') != tenant:
            raise ValueError('unknown_billing_reference')
    if data.get('schedule') and not allow_schedule:
        if _scheduled_row(tenant, contract['subscription']):
            raise ValueError('scheduled_change_pending')
        raise ValueError('scheduled_subscription_requires_review')
    if change:
        state = subscriptions.plan_state(tenant)
        # Optional assistance is not a condition of changing plan.
        if not plan or not state or not state['active_plan']:
            raise ValueError('existing_setup_requires_review')
        items = (data.get('items') or {}).get('data') or []
        if (data.get('status') != 'active' or data.get('pending_update')
                or data.get('collection_method', 'charge_automatically') != 'charge_automatically'
                or len(items) != 1 or not _identifier(items[0].get('id'), 'si')
                or items[0].get('quantity', 1) != 1):
            raise ValueError('subscription_change_requires_review')
        with subscriptions.connection(tenant) as db:
            interval = applied_interval(db, tenant, contract['ref'], contract['subscription'])
        if not _valid_price(_price(items[0]), get_plan(state['active_plan']), interval):
            raise ValueError('payment_processing_refresh_soon')
        contract['billing_interval'] = interval
    return contract, data


def _configuration(features):
    payload = {'features[customer_update][enabled]': 'false',
               'features[payment_method_update][enabled]': 'false',
               'features[invoice_history][enabled]': 'true',
               'features[subscription_cancel][enabled]': 'false',
               'features[subscription_update][enabled]': 'false', **features}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
    result = subscriptions.client().stripe_request('POST', '/v1/billing_portal/configurations', payload,
                                                   idempotency_key='v7-management-config-' + digest)
    if not _identifier(result.get('id'), 'bpc'):
        raise ValueError('stripe_response_invalid')
    return result['id']


def _session(tenant, contract, base_url, config, flow, fields):
    return_url = base_url + '/console/subscription?' + urlencode({'tenant': tenant})
    result = subscriptions.client().stripe_request('POST', '/v1/billing_portal/sessions', {
        'customer': contract['customer'], 'configuration': config, 'return_url': return_url,
        'flow_data[type]': flow, 'flow_data[after_completion][type]': 'redirect',
        'flow_data[after_completion][redirect][return_url]': return_url, **fields})
    url = subscriptions._safe_url(result.get('url'), 'billing.stripe.com')
    if not url:
        raise ValueError('stripe_response_invalid')
    return {'url': url}


def cancel_subscription(tenant, base_url):
    contract, _ = _verified_subscription(tenant)
    config = _configuration({'features[subscription_cancel][enabled]': 'true',
                             'features[subscription_cancel][mode]': 'at_period_end',
                             'features[subscription_cancel][proration_behavior]': 'none'})
    return _session(tenant, contract, base_url, config, 'subscription_cancel',
                    {'flow_data[subscription_cancel][subscription]': contract['subscription']})


def change_plan(tenant, plan_id, base_url, interval=None):
    from service.business_applications import require_eligible
    require_eligible(tenant)
    plan = get_plan(plan_id)
    plan_catalog.require_purchasable(plan)
    if interval is not None and interval not in INTERVALS:
        raise ValueError('invalid_billing_interval')
    contract, data = _verified_subscription(tenant, change=True)
    state = subscriptions.plan_state(tenant)
    current_interval = contract['billing_interval']
    interval = current_interval if interval is None else interval
    if state['active_plan'] == plan_id and interval == current_interval:
        raise ValueError('subscription_plan_already_active')
    if interval != 'month':
        # A business already billed yearly may change plan; nobody may newly move to yearly.
        if interval != current_interval and not plan_catalog.interval_offered(interval):
            raise ValueError('yearly_billing_unavailable')
        with subscriptions.connection(tenant) as db:
            if not subscriptions.intervals_ready(db):
                raise ValueError('yearly_billing_unavailable')
    now_change = (PLAN_RANK[plan_id] >= PLAN_RANK[state['active_plan']]
                  and INTERVAL_RANK[interval] >= INTERVAL_RANK[current_interval])
    amount = price_pence(plan, interval)
    result = subscriptions.client().stripe_request('POST', '/v1/prices', {
        'currency': 'gbp', 'unit_amount': amount, 'recurring[interval]': interval,
        'tax_behavior': 'exclusive', 'product_data[name]': 'V7 ' + plan['name'],
        'metadata[v7_plan_id]': plan['id']},
        idempotency_key='v7-management-price-' + plan['id'] + '-' + str(amount) + ('' if interval == 'month' else '-' + interval))
    subscriptions._verify_payment_environment(result)
    if (not _identifier(result.get('id'), 'price') or not _identifier(result.get('product'), 'prod')
            or not _valid_price(result, plan, interval)):
        raise ValueError('stripe_response_invalid')
    price_id = result['id']
    if not now_change:
        return _schedule_change(tenant, contract, data, state, plan, interval, price_id)
    config = _configuration({'features[subscription_update][enabled]': 'true',
                             'features[subscription_update][default_allowed_updates][0]': 'price',
                             'features[subscription_update][proration_behavior]': 'always_invoice',
                             # A new interval starts a new billing period today.
                             'features[subscription_update][billing_cycle_anchor]': 'unchanged' if interval == current_interval else 'now',
                             'features[subscription_update][products][0][product]': result['product'],
                             'features[subscription_update][products][0][prices][0]': price_id})
    ref, now = secrets.token_urlsafe(24), int(time.time())
    with subscriptions.connection(tenant) as db:
        schema(db)
        db.execute('INSERT INTO billing_plan_changes '
                   '(ref,tenant,billing_ref,subscription,from_plan,plan_id,price_id,setup_plan,status,created,expires) '
                   "VALUES (?,?,?,?,?,?,?,?,'pending',?,?)",
                   (ref, tenant, contract['ref'], contract['subscription'], state['active_plan'], plan_id,
                    price_id, state['setup_plan'] or state['active_plan'], now, now + 86400))
        if interval != 'month':
            db.execute('INSERT INTO billing_interval_choices (ref,tenant,billing_interval) VALUES (?,?,?)',
                       (ref, tenant, interval))
    return _session(tenant, contract, base_url, config, 'subscription_update_confirm', {
        'flow_data[subscription_update_confirm][subscription]': contract['subscription'],
        'flow_data[subscription_update_confirm][items][0][id]': data['items']['data'][0]['id'],
        'flow_data[subscription_update_confirm][items][0][quantity]': 1,
        'flow_data[subscription_update_confirm][items][0][price]': price_id})


def _phase_fields(index, phase, price_id):
    """One schedule phase, carrying over the subscription's tax rates and discounts."""
    fields = {f'phases[{index}][items][0][price]': price_id, f'phases[{index}][items][0][quantity]': 1,
              f'phases[{index}][proration_behavior]': 'none'}
    for number, rate in enumerate(phase.get('default_tax_rates') or []):
        rate = rate.get('id') if isinstance(rate, dict) else rate
        if not _identifier(rate, 'txr'):
            raise ValueError('subscription_change_requires_review')
        fields[f'phases[{index}][default_tax_rates][{number}]'] = rate
    for number, discount in enumerate(phase.get('discounts') or []):
        if not isinstance(discount, dict):
            raise ValueError('subscription_change_requires_review')
        for key in ('coupon', 'discount', 'promotion_code'):
            value = discount.get(key)
            value = value.get('id') if isinstance(value, dict) else value
            if value:
                if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
                    raise ValueError('subscription_change_requires_review')
                fields[f'phases[{index}][discounts][{number}][{key}]'] = value
    return fields


def _settle_applied_schedule(tenant, contract, data):
    """Release our own schedule once its change has taken effect; True if released."""
    schedule_id = data.get('schedule')
    schedule_id = schedule_id.get('id') if isinstance(schedule_id, dict) else schedule_id
    if not _identifier(schedule_id, 'sub_sched'):
        return False
    with subscriptions.connection(tenant) as db:
        schema(db)
        # Only scheduled changes have a window beyond the one-day hosted confirmation.
        ours = db.execute("SELECT 1 FROM billing_plan_changes WHERE tenant=? AND subscription=? AND status='applied' "
                          'AND expires>created+86400 LIMIT 1', (tenant, contract['subscription'])).fetchone()
    if not ours:
        return False  # A schedule V7 never created still needs review.
    schedule = subscriptions.client().stripe_request('GET', '/v1/subscription_schedules/' + schedule_id)
    subscriptions._verify_payment_environment(schedule)
    ref = (schedule.get('metadata') or {}).get('v7_plan_change')
    phases = schedule.get('phases') or []
    started = (schedule.get('current_phase') or {}).get('start_date')
    if (schedule.get('subscription') != contract['subscription'] or schedule.get('status') != 'active'
            or not isinstance(ref, str) or len(phases) != 2 or started != phases[1].get('start_date')):
        return False
    with subscriptions.connection(tenant) as db:
        schema(db)
        applied = db.execute("SELECT 1 FROM billing_plan_changes WHERE tenant=? AND ref=? AND subscription=? "
                             "AND status='applied'", (tenant, ref, contract['subscription'])).fetchone()
    if not applied:
        return False
    _release(schedule_id, ref)
    return True


def _release(schedule_id, key):
    released = subscriptions.client().stripe_request('POST', '/v1/subscription_schedules/' + schedule_id + '/release',
                                                     idempotency_key='v7-schedule-release-' + key)
    if released.get('id') != schedule_id or released.get('status') != 'released':
        raise ValueError('stripe_response_invalid')


def _schedule_change(tenant, contract, data, state, plan, interval, price_id):
    """Move to ``plan`` at the renewal date. Nothing is charged today."""
    items = data['items']['data']
    current_price = _price(items[0]).get('id')
    period_end = items[0].get('current_period_end')
    if not _identifier(current_price, 'price') or type(period_end) is not int or period_end <= time.time():
        raise ValueError('subscription_change_requires_review')
    ref, now = secrets.token_urlsafe(24), int(time.time())
    with subscriptions.connection(tenant) as db:
        schema(db)
        # Recorded before Stripe is changed, so a renewal on the new price is never unexplained.
        db.execute('INSERT INTO billing_plan_changes '
                   '(ref,tenant,billing_ref,subscription,from_plan,plan_id,price_id,setup_plan,status,created,expires) '
                   "VALUES (?,?,?,?,?,?,?,?,'scheduled',?,?)",
                   (ref, tenant, contract['ref'], contract['subscription'], state['active_plan'], plan['id'],
                    price_id, state['setup_plan'] or state['active_plan'], now, period_end + SCHEDULE_WINDOW))
        if interval != 'month':
            db.execute('INSERT INTO billing_interval_choices (ref,tenant,billing_interval) VALUES (?,?,?)',
                       (ref, tenant, interval))
    stripe = subscriptions.client()
    schedule_id = None
    try:
        schedule = stripe.stripe_request('POST', '/v1/subscription_schedules',
                                         {'from_subscription': contract['subscription']},
                                         idempotency_key='v7-schedule-' + ref)
        subscriptions._verify_payment_environment(schedule)
        schedule_id = schedule.get('id')
        phases = schedule.get('phases') or []
        if (not _identifier(schedule_id, 'sub_sched') or schedule.get('subscription') != contract['subscription']
                or len(phases) != 1 or phases[0].get('end_date') != period_end
                or type(phases[0].get('start_date')) is not int):
            raise ValueError('subscription_change_requires_review')
        current = phases[0]
        phase_items = current.get('items') or []
        if (len(phase_items) != 1 or phase_items[0].get('quantity', 1) != 1
                or (phase_items[0].get('price') if isinstance(phase_items[0].get('price'), str)
                    else _price(phase_items[0]).get('id')) != current_price):
            raise ValueError('subscription_change_requires_review')
        # Stripe-Version 2025-06-30.basil: a phase length is ``iterations``
        # (``duration`` replaces it from 2025-07-30). Release keeps the new price.
        payload = {'end_behavior': 'release', 'proration_behavior': 'none',
                   'phases[0][start_date]': current['start_date'], 'phases[0][end_date]': period_end,
                   **_phase_fields(0, current, current_price), **_phase_fields(1, current, price_id),
                   'phases[1][iterations]': 1, 'metadata[v7_plan_change]': ref}
        result = stripe.stripe_request('POST', '/v1/subscription_schedules/' + schedule_id, payload,
                                       idempotency_key='v7-schedule-phases-' + ref)
        later = (result.get('phases') or [{}, {}])[1:2]
        later_items = (later[0].get('items') or []) if later else []
        later_price = later_items[0].get('price') if later_items else None
        later_price = later_price.get('id') if isinstance(later_price, dict) else later_price
        if result.get('id') != schedule_id or later_price != price_id:
            raise ValueError('stripe_response_invalid')
    except Exception:
        with subscriptions.connection(tenant) as db:
            db.execute("UPDATE billing_plan_changes SET status='failed' WHERE tenant=? AND ref=?", (tenant, ref))
        if schedule_id and _identifier(schedule_id, 'sub_sched'):
            try:
                _release(schedule_id, ref)
            except Exception:
                pass  # The subscription keeps its current price either way.
        raise
    return {'scheduled': True, 'plan_id': plan['id'], 'interval': interval, 'effective': period_end}


def cancel_scheduled_change(tenant):
    """Keep the current plan: release the schedule so renewal stays as it is."""
    contract, data = _verified_subscription(tenant, allow_schedule=True)
    row = _scheduled_row(tenant, contract['subscription'])
    schedule_id = data.get('schedule')
    schedule_id = schedule_id.get('id') if isinstance(schedule_id, dict) else schedule_id
    if not row or not _identifier(schedule_id, 'sub_sched'):
        raise ValueError('no_scheduled_change')
    schedule = subscriptions.client().stripe_request('GET', '/v1/subscription_schedules/' + schedule_id)
    subscriptions._verify_payment_environment(schedule)
    if (schedule.get('subscription') != contract['subscription']
            or (schedule.get('metadata') or {}).get('v7_plan_change') != row['ref']):
        raise ValueError('scheduled_subscription_requires_review')
    if schedule.get('status') in {'active', 'not_started'}:
        _release(schedule_id, row['ref'])
    with subscriptions.connection(tenant) as db:
        db.execute("UPDATE billing_plan_changes SET status='cancelled' WHERE tenant=? AND subscription=? AND status='scheduled'",
                   (tenant, contract['subscription']))
    return {'ok': True}


def reactivate_subscription(tenant):
    """Undo a cancellation before it takes effect. Nothing is charged today."""
    contract, data = _verified_subscription(tenant, allow_cancelling=True)
    if data.get('status') not in {'active', 'trialing', 'past_due'}:
        raise ValueError('active_platform_subscription_required')
    if not (data.get('cancel_at_period_end') or data.get('cancel_at')):
        raise ValueError('subscription_not_cancelling')
    fields = {'cancel_at_period_end': 'false'} if data.get('cancel_at_period_end') else {'cancel_at': ''}
    marker = str(data.get('cancel_at') or '') + '-' + str(int(bool(data.get('cancel_at_period_end'))))
    result = subscriptions.client().stripe_request('POST', '/v1/subscriptions/' + contract['subscription'], fields,
                                                   idempotency_key='v7-reactivate-' + contract['ref'] + '-' + marker)
    subscriptions._verify_payment_environment(result)
    if result.get('id') != contract['subscription'] or result.get('cancel_at_period_end') or result.get('cancel_at'):
        raise ValueError('stripe_response_invalid')
    subscriptions.sync_subscription(contract['subscription'])
    return {'ok': True}
