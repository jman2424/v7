"""Owner-scoped billing, platform oversight, and verified Stripe callbacks."""
import json
from flask import Blueprint, abort, jsonify, request, session
from service.business_applications import ApplicationError
from routes import get_container
from routes.public_errors import validation_error
from service.security import management_user, authorized_tenant, is_platform_admin, require_permission, account_permissions
from service import subscriptions

bp = Blueprint('billing', __name__, url_prefix='/billing')

_PROVIDER_ERRORS = ('stripe_not_configured', 'stripe_request_failed', 'stripe_response_invalid',
                    'stripe_setup_required', 'stripe_live_payments_required')
_PLAN_ERRORS = (
    'invalid_subscription_plan', 'existing_subscription_requires_review',
    'paid_setup_plan_requires_review', 'existing_setup_requires_review',
    'internal_business_has_no_customer_subscription', 'cancel_pending_checkout_before_changing_plan',
)
_DISCOUNT_ERRORS = (
    'invalid_discount_code', 'promotion_unavailable', 'discount_does_not_stack',
    'first_month_discount_new_subscription_only', 'implementation_already_paid',
    'discount_not_applicable', 'checkout_promotion_changed_refresh', 'stripe_discount_invalid',
)
_SUBSCRIPTION_ERRORS = (
    'subscription_required', 'active_platform_subscription_required', 'subscription_already_cancelling',
    'scheduled_subscription_requires_review', 'subscription_change_requires_review',
    'payment_processing_refresh_soon', 'subscription_plan_already_active', 'existing_setup_requires_review',
)
_CHECKOUT_ERRORS = (
    'invalid_billing_item', 'plan_not_applicable_to_billing_item', 'whatsapp_included_in_subscription',
    'extra_usage_charges_disabled', 'active_platform_subscription_required', 'api_charge_not_approved',
    'subscription_already_exists', 'checkout_plan_changed_refresh', 'checkout_creation_in_progress',
    'payment_processing_refresh_soon', 'stripe_tax_rate_must_be_20_percent_exclusive',
)
_REFERRAL_ERRORS = (
    'invalid_referral_setting', 'invalid_referral_code', 'referral_already_accepted',
    'referral_program_disabled', 'invalid_or_self_referral', 'referral_requires_new_business_before_checkout',
    'referral_does_not_stack_with_existing_discount', 'active_paid_subscription_required',
    'no_available_referral_reward', 'referral_discount_not_confirmed', 'invalid_referral_coupon',
)


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
    if not get_container().storage.tenant_exists(tenant):
        abort(404, description='unknown_tenant')
    return tenant


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data,dict):
        abort(400, description='json_object_required')
    return data


@bp.post('/change-plan')
def change_plan_post():
    from service import billing_management
    tenant, data = _tenant(), _body()
    try:
        result = billing_management.change_plan(tenant, data.get('plan_id'), get_container().settings.BASE_URL.rstrip('/'))
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed',
                                public_messages=_PROVIDER_ERRORS + _SUBSCRIPTION_ERRORS + _PLAN_ERRORS)
    from routes.admin_api_routes import _audit
    _audit('billing.change_plan_review', tenant, after={'plan_id': data.get('plan_id')})
    return jsonify(result)


@bp.post('/cancel-subscription')
def cancel_subscription_post():
    from service import billing_management
    tenant = _tenant()
    try:
        result = billing_management.cancel_subscription(tenant, get_container().settings.BASE_URL.rstrip('/'))
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed', public_messages=_PROVIDER_ERRORS + _SUBSCRIPTION_ERRORS)
    from routes.admin_api_routes import _audit
    _audit('billing.cancel_subscription_review', tenant)
    return jsonify(result)


@bp.get('/referrals')
def referrals_get():
    from service import referrals
    tenant = _tenant()
    return jsonify(referrals.report(tenant, _owner()['email'], get_container().settings.BASE_URL.rstrip('/')))


@bp.post('/referrals/<action>')
def referrals_post(action):
    from service import referrals, session_store
    if action == 'program':
        management_user(platform_only=True)
        require_permission('offers.write')
    tenant = _tenant()
    data = _body()
    try:
        if action == 'claim':
            result = referrals.claim(tenant, _owner()['email'], data.get('code'))
        elif action == 'apply':
            result = referrals.apply_next_month(tenant)
        elif action == 'program':
            result = referrals.set_program(tenant, data.get('enabled'), session_store._digest(session.get('management_token')))
        else:
            abort(404)
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'referral_request_failed', public_messages=_PROVIDER_ERRORS + _REFERRAL_ERRORS)
    from routes.admin_api_routes import _audit
    _audit('billing.referral.'+action, tenant, after=result)
    return jsonify(result)


@bp.get('/subscription')
def subscription_get():
    tenant = _tenant(read_only=True)
    user = management_user()
    report = subscriptions.report(tenant, include_api='view_costs' in account_permissions(user))
    from service import business_applications
    report['business_application'] = business_applications.get(tenant)
    try:
        business_applications.require_eligible(tenant)
        report['business_purchase_allowed'] = True
    except ApplicationError:
        report['business_purchase_allowed'] = False
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
    def billing_details(company, db):
        company['contracts'] = [dict(row) for row in db.execute('SELECT kind,status,next_due,paused FROM billing_contracts WHERE tenant=?',(company['key'],))]
        totals = dict(db.execute("SELECT COALESCE(SUM(paid),0) paid,COALESCE(SUM(CASE WHEN status='open' THEN remaining ELSE 0 END),0) due FROM billing_invoices WHERE tenant=?",(company['key'],)).fetchone())
        company['totals'] = {key: int(value) for key, value in totals.items()}
    if subscriptions.session_store._using_postgres():
        for company in matches[(page-1)*50:page*50]:
            with subscriptions.connection(company['key']) as db:
                billing_details(company, db)
    else:
        with subscriptions.connection() as db:
            for company in matches[(page-1)*50:page*50]:
                billing_details(company, db)
    from service import plan_usage
    for company in matches[(page-1)*50:page*50]:
        company['plan_state'] = subscriptions.plan_state(company['key'])
        company['allowance'] = plan_usage.report(company['key'])
    return jsonify(companies=matches[(page-1)*50:page*50],total=len(companies),matched=len(matches),page=page,has_next=len(matches)>page*50)


@bp.post('/complimentary-plan')
def complimentary_plan_post():
    management_user(platform_only=True)
    tenant = _tenant()
    data = _body()
    reason = data.get('reason')
    enabled = data.get('enabled', True)
    if not isinstance(enabled, bool) or data.get('plan_id') != 'scale' or not isinstance(reason, str) or not 5 <= len(reason.strip()) <= 500:
        return jsonify(error='invalid_plan_grant'), 400
    try:
        state = subscriptions.grant_complimentary_scale(tenant, enabled=enabled)
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'invalid_plan_grant',
                                public_messages=('existing_stripe_subscription_requires_review',))
    from routes.admin_api_routes import _audit
    _audit('billing.complimentary_plan', tenant, after={'plan':'scale', 'enabled':enabled, 'reason':reason.strip()})
    return jsonify(ok=True, plan_state=state)


@bp.post('/checkout')
def checkout_post():
    tenant, data = _tenant(), _body()
    try:
        result = subscriptions.checkout(tenant,session['user']['email'],data.get('kind'),get_container().settings.BASE_URL.rstrip('/'),data.get('month',''),discount_code=data.get('discount_code',''),plan_id=data.get('plan_id'))
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed',
                                public_messages=_PROVIDER_ERRORS + _PLAN_ERRORS + _DISCOUNT_ERRORS + _CHECKOUT_ERRORS)
    from routes.admin_api_routes import _audit
    _audit('billing.checkout',tenant,after={'kind':data.get('kind'),'plan_id':data.get('plan_id')})
    return jsonify(result)


@bp.post('/select-plan')
def select_plan_post():
    tenant, data = _tenant(), _body()
    try:
        state = subscriptions.select_plan(tenant, data.get('plan_id'))
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed', public_messages=_PLAN_ERRORS)
    from routes.admin_api_routes import _audit
    _audit('billing.select_plan',tenant,after={'plan_id':state['selected_plan']})
    return jsonify(ok=True,plan_state=state)


@bp.post('/cancel-checkout')
def cancel_checkout_post():
    tenant = _tenant()
    try:
        result = subscriptions.cancel_pending_checkouts(tenant)
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed', public_messages=_PROVIDER_ERRORS + _CHECKOUT_ERRORS)
    from routes.admin_api_routes import _audit
    _audit('billing.cancel_checkout',tenant)
    return jsonify(result)


@bp.post('/discount')
def discount_post():
    tenant, data = _tenant(), _body()
    try:
        result = subscriptions.redeem_discount(tenant,data.get('code'))
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed', public_messages=_DISCOUNT_ERRORS)
    from routes.admin_api_routes import _audit
    _audit('billing.discount',tenant,after={key:result[key] for key in ('discount_percent','setup_discount_percent','first_month_discount_percent') if key in result})
    return jsonify(result)


@bp.post('/portal')
def portal_post():
    tenant = _tenant()
    try:
        return jsonify(subscriptions.portal(tenant,get_container().settings.BASE_URL.rstrip('/')))
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed', public_messages=_PROVIDER_ERRORS + _SUBSCRIPTION_ERRORS)


@bp.post('/whatsapp')
def whatsapp_post():
    tenant, data = _tenant(), _body()
    if type(data.get('enabled')) is not bool:
        abort(400,description='enabled_must_be_boolean')
    try:
        subscriptions.change_whatsapp(tenant,data['enabled'])
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed', public_messages=('whatsapp_subscription_required',))
    from routes.admin_api_routes import _audit
    _audit('billing.whatsapp',tenant,after={'enabled':data['enabled']})
    return jsonify(ok=True)


@bp.post('/api-charge')
def api_charge_post():
    management_user(platform_only=True)
    tenant, data = _tenant(), _body()
    try:
        subscriptions.approve_api_charge(tenant,data.get('month'),data.get('amount_pence'))
    except ApplicationError as exc:
        return jsonify(error=exc.code), exc.status
    except ValueError as exc:
        return validation_error(exc, 'billing_request_failed', public_messages=('prepaid_usage_requires_topup',))
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
        from service.ai_budget_payments import handle_event as handle_budget_event
        if handle_budget_event(event):
            return jsonify(ok=True)
        from service.usage_payments import handle_usage_event
        if handle_usage_event(event):
            return jsonify(ok=True)
        from service import referrals
        referrals.handle_reversal(event)
        if str(event.get('type','')).startswith('customer.subscription.'):
            subscriptions.sync_subscription(obj['id'])
        elif event.get('type') in {'invoice.paid','invoice.payment_failed','invoice.finalized','invoice.updated','invoice.voided','invoice.marked_uncollectible'}:
            subscriptions.sync_invoice(obj['id'])
        elif event.get('type') == 'checkout.session.completed':
            if obj.get('subscription'):
                subscriptions.sync_subscription(obj['subscription'])
            if obj.get('invoice'):
                subscriptions.sync_invoice(obj['invoice'])
            elif not obj.get('subscription'):
                subscriptions.sync_zero_setup_checkout(obj['id'])
    except (ValueError,KeyError,TypeError):
        # Non-2xx lets Stripe retry transient failures; never log payloads or secrets.
        return jsonify(error='billing_sync_failed'),503
    return jsonify(ok=True)
