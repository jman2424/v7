"""Owner-scoped billing, platform oversight, and verified Stripe callbacks."""
import json
from flask import Blueprint, abort, jsonify, request, session
from routes import get_container
from service.security import management_user, authorized_tenant, is_platform_admin, require_permission, account_permissions
from service import subscriptions

bp = Blueprint('billing', __name__, url_prefix='/billing')


def _owner():
    user = management_user()
    if not is_platform_admin(user) and 'business_owner' not in user['roles']:
        abort(403, description='company_owner_required')
    return user


def _tenant(read_only=False):
    if read_only:
        require_permission('view_subscriptions')
    else:
        _owner()
    tenant = authorized_tenant(request.args.get('tenant'))
    if not get_container().storage.tenant_dir(tenant).is_dir():
        abort(404, description='unknown_tenant')
    return tenant


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data,dict):
        abort(400, description='json_object_required')
    return data


@bp.get('/subscription')
def subscription_get():
    tenant = _tenant(read_only=True)
    user = management_user()
    report = subscriptions.report(tenant, include_api='view_costs' in account_permissions(user))
    if not is_platform_admin(user) and 'business_owner' not in user['roles']:
        for invoice in report['invoices']:
            invoice['url'] = None
    return jsonify(report)


@bp.get('/companies')
def companies_get():
    management_user(platform_only=True)
    from service.tenant_service import TenantService
    companies = TenantService(get_container().storage).list_tenants()
    search = request.args.get('search','')[:100].lower()
    try:
        page = max(1,int(request.args.get('page','1')))
    except ValueError:
        abort(400,description='invalid_page')
    matches = [row for row in companies if search in (row['key']+' '+row['name']).lower()]
    with subscriptions.connection() as db:
        for company in matches[(page-1)*50:page*50]:
            company['contracts'] = [dict(row) for row in db.execute('SELECT kind,status,next_due,paused FROM billing_contracts WHERE tenant=?',(company['key'],))]
            company['totals'] = dict(db.execute("SELECT COALESCE(SUM(paid),0) paid,COALESCE(SUM(CASE WHEN status='open' THEN remaining ELSE 0 END),0) due FROM billing_invoices WHERE tenant=?",(company['key'],)).fetchone())
    return jsonify(companies=matches[(page-1)*50:page*50],total=len(companies),matched=len(matches),page=page,has_next=len(matches)>page*50)


@bp.post('/checkout')
def checkout_post():
    tenant, data = _tenant(), _body()
    try:
        result = subscriptions.checkout(tenant,session['user']['email'],data.get('kind'),get_container().settings.BASE_URL.rstrip('/'),data.get('month',''),discount_code=data.get('discount_code',''))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    from routes.admin_api_routes import _audit
    _audit('billing.checkout',tenant,after={'kind':data.get('kind')})
    return jsonify(result)


@bp.post('/discount')
def discount_post():
    tenant, data = _tenant(), _body()
    try:
        result = subscriptions.redeem_discount(tenant,data.get('code'))
    except ValueError as exc:
        return jsonify(error=str(exc)),400
    from routes.admin_api_routes import _audit
    _audit('billing.discount',tenant,after={'percent':50})
    return jsonify(result)


@bp.post('/portal')
def portal_post():
    tenant = _tenant()
    try:
        return jsonify(subscriptions.portal(tenant,get_container().settings.BASE_URL.rstrip('/')))
    except ValueError as exc:
        return jsonify(error=str(exc)),400


@bp.post('/whatsapp')
def whatsapp_post():
    tenant, data = _tenant(), _body()
    if type(data.get('enabled')) is not bool:
        abort(400,description='enabled_must_be_boolean')
    try:
        subscriptions.change_whatsapp(tenant,data['enabled'])
    except ValueError as exc:
        return jsonify(error=str(exc)),400
    from routes.admin_api_routes import _audit
    _audit('billing.whatsapp',tenant,after={'enabled':data['enabled']})
    return jsonify(ok=True)


@bp.post('/api-charge')
def api_charge_post():
    management_user(platform_only=True)
    tenant, data = _tenant(), _body()
    try:
        subscriptions.approve_api_charge(tenant,data.get('month'),data.get('amount_pence'))
    except ValueError as exc:
        return jsonify(error=str(exc)),400
    from routes.admin_api_routes import _audit
    _audit('billing.api_charge',tenant,after={'month':data['month'],'amount_pence':data['amount_pence']})
    return jsonify(ok=True),201


@bp.post('/stripe/webhook')
def stripe_webhook():
    body = request.get_data()
    stripe = subscriptions.client()
    if stripe.provider != 'stripe' or not stripe.verify_webhook(dict(request.headers),body):
        abort(403,description='invalid_stripe_signature')
    try:
        event = json.loads(body)
        if not isinstance(event,dict) or not isinstance(event.get('data'),dict) or not isinstance(event['data'].get('object'),dict):
            raise ValueError('invalid_event')
        obj = event['data']['object']
        if str(event.get('type','')).startswith('customer.subscription.'):
            subscriptions.sync_subscription(obj['id'])
        elif event.get('type') in {'invoice.paid','invoice.payment_failed','invoice.finalized','invoice.updated','invoice.voided','invoice.marked_uncollectible'}:
            subscriptions.sync_invoice(obj['id'])
        elif event.get('type') == 'checkout.session.completed':
            if obj.get('subscription'):
                subscriptions.sync_subscription(obj['subscription'])
            if obj.get('invoice'):
                subscriptions.sync_invoice(obj['invoice'])
    except (ValueError,KeyError,TypeError):
        # Non-2xx lets Stripe retry transient failures; never log payloads or secrets.
        return jsonify(error='billing_sync_failed'),503
    return jsonify(ok=True)
