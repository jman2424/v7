"""Owner-authorized changes; Stripe confirms prices, payment and cancellation."""
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlencode

from service import subscriptions
from service.plan_catalog import get_plan


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


def _valid_price(price, plan):
    recurring = price.get('recurring') or {}
    return (price.get('currency') == 'gbp' and type(price.get('unit_amount')) is int
            and price['unit_amount'] == plan['monthly_pence']
            and price.get('tax_behavior') == 'exclusive'
            and recurring.get('interval') == 'month'
            and recurring.get('interval_count', 1) == 1
            and recurring.get('usage_type', 'licensed') == 'licensed')


def _invoice_price(line):
    price = line.get('price')
    if isinstance(price, dict):
        return price.get('id')
    if isinstance(price, str):
        return price
    return ((line.get('pricing') or {}).get('price_details') or {}).get('price')


def locked_subscription(db, tenant, subscription_id, data):
    schema(db)
    if not db.execute('SELECT 1 FROM billing_plan_changes WHERE tenant=? AND subscription=? LIMIT 1',
                      (tenant, subscription_id)).fetchone():
        return data
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
    matching = [row for row in rows if row['price_id'] == price.get('id')]
    if not matching:
        if not any(row['status'] == 'applied' for row in rows):
            return baseline
        raise ValueError('unknown_billing_plan')
    row = matching[0]
    plan = get_plan(row['plan_id'])
    if not _valid_price(price, plan):
        raise ValueError('unknown_billing_plan')
    if row['status'] == 'applied' and state and state['active_plan'] == plan['id']:
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


def paid_setup_covers(tenant, active_plan, setup_plan, *, db=None):
    if active_plan == setup_plan:
        return bool(active_plan)
    if db is None:
        with subscriptions.connection(tenant) as connection:
            return paid_setup_covers(tenant, active_plan, setup_plan, db=connection)
    schema(db)
    # Paid plan-change proof remains tenant-bound across cancellation and a new
    # checkout generation. Pending requests cannot waive a different plan's setup.
    row = db.execute("SELECT 1 FROM billing_plan_changes c JOIN billing_references r "
                     "ON r.tenant=c.tenant AND r.ref=c.billing_ref AND r.kind='platform' "
                     "JOIN billing_plan_choices p ON p.tenant=c.tenant AND p.ref=c.billing_ref "
                     "AND p.kind='platform' WHERE c.tenant=? AND c.plan_id=? AND c.setup_plan=? "
                     "AND c.status='applied' LIMIT 1", (tenant, active_plan, setup_plan)).fetchone()
    return bool(row)


def summary(tenant):
    with subscriptions.connection(tenant) as db:
        contract = db.execute("SELECT subscription,status,cancel_at_end FROM billing_contracts "
                              "WHERE tenant=? AND kind='platform'", (tenant,)).fetchone()
    state = subscriptions.plan_state(tenant)
    regular = not subscriptions.internal_business(tenant) and not subscriptions.complimentary_plan(tenant)
    cancel = bool(regular and contract and _identifier(contract['subscription'], 'sub')
                  and contract['status'] in {'active', 'trialing', 'past_due', 'unpaid'})
    return {'can_cancel': cancel and not bool(contract['cancel_at_end']),
            'can_change_plan': bool(cancel and contract['status'] == 'active'
                                    and not contract['cancel_at_end'] and state and state['active_plan'])}


def _verified_subscription(tenant, *, change=False):
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
    if data.get('cancel_at_period_end') or data.get('cancel_at'):
        raise ValueError('subscription_already_cancelling')
    if data.get('schedule'):
        raise ValueError('scheduled_subscription_requires_review')
    if change:
        state = subscriptions.plan_state(tenant)
        if (not plan or not state or not state['active_plan'] or not state['setup_plan']
                or not contract['implementation_paid']):
            raise ValueError('existing_setup_requires_review')
        items = (data.get('items') or {}).get('data') or []
        if (data.get('status') != 'active' or data.get('pending_update')
                or data.get('collection_method', 'charge_automatically') != 'charge_automatically'
                or len(items) != 1 or not _identifier(items[0].get('id'), 'si')
                or items[0].get('quantity', 1) != 1):
            raise ValueError('subscription_change_requires_review')
        if not _valid_price(_price(items[0]), get_plan(state['active_plan'])):
            raise ValueError('payment_processing_refresh_soon')
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


def change_plan(tenant, plan_id, base_url):
    plan = get_plan(plan_id)
    contract, data = _verified_subscription(tenant, change=True)
    state = subscriptions.plan_state(tenant)
    if state['active_plan'] == plan_id:
        raise ValueError('subscription_plan_already_active')
    amount = plan['monthly_pence']
    result = subscriptions.client().stripe_request('POST', '/v1/prices', {
        'currency': 'gbp', 'unit_amount': amount, 'recurring[interval]': 'month',
        'tax_behavior': 'exclusive', 'product_data[name]': 'V7 ' + plan['name'],
        'metadata[v7_plan_id]': plan['id']},
        idempotency_key='v7-management-price-' + plan['id'] + '-' + str(amount))
    subscriptions._verify_payment_environment(result)
    if not _identifier(result.get('id'), 'price') or not _identifier(result.get('product'), 'prod') or not _valid_price(result, plan):
        raise ValueError('stripe_response_invalid')
    price_id = result['id']
    config = _configuration({'features[subscription_update][enabled]': 'true',
                             'features[subscription_update][default_allowed_updates][0]': 'price',
                             'features[subscription_update][proration_behavior]': 'always_invoice',
                             'features[subscription_update][billing_cycle_anchor]': 'unchanged',
                             'features[subscription_update][products][0][product]': result['product'],
                             'features[subscription_update][products][0][prices][0]': price_id})
    ref, now = secrets.token_urlsafe(24), int(time.time())
    with subscriptions.connection(tenant) as db:
        schema(db)
        db.execute('INSERT INTO billing_plan_changes '
                   '(ref,tenant,billing_ref,subscription,from_plan,plan_id,price_id,setup_plan,status,created,expires) '
                   "VALUES (?,?,?,?,?,?,?,?,'pending',?,?)",
                   (ref, tenant, contract['ref'], contract['subscription'], state['active_plan'], plan_id,
                    price_id, state['setup_plan'], now, now + 86400))
    return _session(tenant, contract, base_url, config, 'subscription_update_confirm', {
        'flow_data[subscription_update_confirm][subscription]': contract['subscription'],
        'flow_data[subscription_update_confirm][items][0][id]': data['items']['data'][0]['id'],
        'flow_data[subscription_update_confirm][items][0][quantity]': 1,
        'flow_data[subscription_update_confirm][items][0][price]': price_id})
