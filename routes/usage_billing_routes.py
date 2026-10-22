"""Authenticated, tenant-scoped prepaid AI billing; Stripe owns payment status."""
from flask import Blueprint, abort, jsonify, request

from routes import get_container
from service import subscriptions, usage_payments, usage_wallet
from service.security import management_user, authorized_tenant, is_platform_admin, require_permission

bp = Blueprint('usage_billing', __name__, url_prefix='/billing/usage-credit')


def _tenant(*, owner=False):
    user = management_user()
    require_permission('view_costs')
    if owner and not is_platform_admin(user) and 'business_owner' not in user.get('roles', []):
        abort(403, description='company_owner_required')
    tenant = authorized_tenant(request.args.get('tenant'))
    if not get_container().storage.tenant_exists(tenant):
        abort(404, description='unknown_tenant')
    return tenant, user


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description='json_object_required')
    return data


def _page():
    value = request.args.get('page', '1')
    if not value.isascii() or not value.isdigit() or len(value)>7 or not 1<=int(value)<=1000000:
        abort(400, description='invalid_page')
    return int(value)


@bp.get('')
def credit_get():
    tenant, user = _tenant()
    page = _page()
    requests = usage_payments.checkout_requests(tenant)
    return jsonify(tenant=tenant, configured=usage_payments.payments_ready(), currency='GBP',
                   packs=usage_payments.packs(), vat_percent=subscriptions.vat_percent(),
                   wallet=usage_wallet.report(tenant, offset=(page-1)*20, limit=20), page=page,
                   policy={'mode':'prepaid', 'included_credit_pence':0, 'automatic_recharge':False},
                   internal=subscriptions.internal_business(tenant), checkout_requests=requests,
                   pending_checkouts=[row for row in requests if row['status'] in {'preparing','pending'}],
                   usage_reviews=usage_wallet.unconfirmed_usage(tenant) if is_platform_admin(user) else [])


@bp.post('/checkout')
def checkout_post():
    tenant, user = _tenant(owner=True)
    data = _body()
    try:
        result = usage_payments.checkout(tenant, user['email'], data.get('pack_id'), data.get('request_id'),
                                         get_container().settings.BASE_URL.rstrip('/'))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    from routes.admin_api_routes import _audit
    _audit('billing.usage_checkout', tenant, after={'pack_id':result['pack_id'], 'reference':result['reference']})
    return jsonify(result)


@bp.get('/companies')
def companies_get():
    management_user(platform_only=True)
    require_permission('view_costs')
    from service.tenant_service import TenantService
    companies = TenantService(get_container().storage).list_tenants()
    search = request.args.get('search', '')[:100].casefold()
    page = _page()
    matches = [row for row in companies if search in (row['key']+' '+row['name']).casefold()]
    selected = matches[(page-1)*20:page*20]
    # A separate transaction for every exact company sets the private RLS scope.
    result = [{**row, 'wallet':usage_wallet.report(row['key'], limit=1),
               'internal':subscriptions.internal_business(row['key'])} for row in selected]
    return jsonify(companies=result, total=len(companies), matched=len(matches), page=page, has_next=len(matches)>page*20)


@bp.post('/adjust')
def adjustment_post():
    management_user(platform_only=True)
    tenant, user = _tenant(owner=True)
    data = _body()
    try:
        result = usage_wallet.adjust(tenant, data.get('amount_pence'), data.get('reason'), user['email'],
                                     request_id=usage_payments._request_id(data.get('request_id')))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not result['duplicate']:
        from routes.admin_api_routes import _audit
        _audit('billing.usage_adjustment', tenant, after={'amount_pence':data['amount_pence'], 'reason':data['reason']})
    return jsonify(**result, wallet=usage_wallet.report(tenant))


@bp.post('/waive-unconfirmed')
def waive_unconfirmed_post():
    management_user(platform_only=True)
    tenant, user = _tenant(owner=True)
    data = _body()
    if data.get('platform_absorbs_provider_cost') is not True:
        return jsonify(error='usage_review_confirmation_required'), 400
    try:
        result = usage_wallet.waive_unconfirmed_usage(tenant,data.get('reference'),data.get('reason'),user['email'])
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not result['duplicate']:
        from routes.admin_api_routes import _audit
        _audit('billing.usage_charge_waived',tenant,after={
            'reference':data['reference'],'reason':data['reason'],'provider_cost_status':'unknown',
            'client_charge_outcome':'waived_platform_absorbs_provider_cost'})
    return jsonify(**result,wallet=usage_wallet.report(tenant))
