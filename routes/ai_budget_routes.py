"""AI Budget: authenticated tenant owners; provider finances: platform only."""
from flask import Blueprint, current_app, jsonify, request

from routes import get_container
from routes.usage_billing_routes import _tenant, _page
from service import ai_budget as budget, ai_budget_payments as payments, ai_budget_store as store
from service import ai_provider_funding as funding, usage_payments
from service.security import management_user
from service.business_applications import ApplicationError

bp = Blueprint('ai_budget',__name__,url_prefix='/billing/ai-budget')


@bp.errorhandler(budget.BudgetError)
def budget_error(error):
    return jsonify(error=error.code),error.status


@bp.errorhandler(ApplicationError)
def application_error(error):
    return jsonify(error=error.code),error.status


@bp.errorhandler(ValueError)
def provider_value_error(error):
    current_app.logger.warning('AI Budget request rejected error_type=%s',type(error).__name__)
    return jsonify(error='budget_request_unavailable'),409


def _body(fields=None):
    value = request.get_json(silent=True)
    if not isinstance(value,dict) or fields is not None and set(value)-set(fields):
        raise budget.BudgetError('invalid_budget_request')
    return value


@bp.get('')
def budget_get():
    tenant,_ = _tenant()
    return jsonify(budget.customer_report(tenant,page=_page()))


@bp.get('/rates')
def rates_get():
    _tenant()
    from service.ai_budget_rates import public_rates
    return jsonify(public_rates())


@bp.post('/preferences')
def preferences_post():
    tenant,actor = _tenant(owner=True)
    budget.save_preferences(tenant,_body(),actor['id'])
    return jsonify(ok=True)


@bp.post('/checkout')
def checkout_post():
    tenant,actor = _tenant(owner=True)
    data = _body({'pack_id','request_id'})
    if not isinstance(data.get('pack_id'),str) or data['pack_id'] not in {'gbp_10','gbp_25','gbp_50'}:
        raise budget.BudgetError('invalid_usage_pack')
    try:
        result = usage_payments.checkout(tenant,actor['email'],data['pack_id'],data.get('request_id'),get_container().settings.BASE_URL.rstrip('/'))
    except ApplicationError as exc:
        return jsonify(error=exc.code),exc.status
    except ValueError:
        current_app.logger.warning('AI Budget checkout rejected')
        return jsonify(error='budget_checkout_unavailable'),409
    from routes.admin_api_routes import _audit
    _audit('billing.ai_budget_checkout',tenant,after={'pack_id':data['pack_id']})
    return jsonify({key:result.get(key) for key in ('url','status','credit_pence','total_pence')})


@bp.post('/automatic-recharge/authorise')
def authorise_post():
    tenant,actor = _tenant(owner=True)
    return jsonify(payments.authorise(tenant,_body(),actor,get_container().settings.BASE_URL))


@bp.post('/automatic-recharge/confirm')
def confirm_post():
    tenant,_ = _tenant(owner=True)
    _body(set())
    return jsonify(payments.confirm_authorisation(tenant))


@bp.post('/automatic-recharge/disable')
def disable_post():
    tenant,actor = _tenant(owner=True)
    _body(set())
    return jsonify(payments.disable(tenant,actor['id']))


@bp.post('/automatic-recharge/resolve')
def resolve_post():
    tenant,actor = _tenant(owner=True)
    _body(set())
    with store.connection(tenant) as db:
        rows=[r['reference'] for r in db.execute("SELECT reference FROM ai_budget_recharges WHERE tenant=? AND status IN('reserved','dispatching','processing','requires_action','unknown')",(tenant,))]
    for reference in rows:
        payments.cancel_recharge(tenant,reference)
    with store.connection(tenant,write=True) as db:
        store.audit(db,tenant,'pending_payments_resolved',actor['id'],{'count':len(rows)})
    return jsonify(ok=True)


@bp.post('/notifications/seen')
def seen_post():
    tenant,_ = _tenant(owner=True)
    data = _body({'id'})
    identifier = data.get('id')
    if not isinstance(identifier,str) or len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):
        raise budget.BudgetError('invalid_budget_notification')
    with store.connection(tenant,write=True) as db:
        row = db.execute('SELECT id FROM ai_budget_notifications WHERE tenant=? AND id=?',(tenant,identifier)).fetchone()
        if not row:
            raise budget.BudgetError('budget_notification_not_found',404)
        db.execute('UPDATE ai_budget_notifications SET seen=1 WHERE tenant=? AND id=?',(tenant,identifier))
    return jsonify(ok=True)


@bp.get('/provider-funding')
def funding_get():
    management_user(platform_only=True)
    from service.ai_budget_finance import operations
    return jsonify({**funding.report(),'operations':operations(get_container().storage)})


@bp.post('/provider-funding/settings')
def funding_settings_post():
    actor = management_user(platform_only=True)
    try:
        return jsonify(settings=funding.save_settings(_body(),actor['id']))
    except ValueError:
        return jsonify(error='invalid_provider_funding_settings'),400


@bp.post('/provider-funding/sync')
def funding_sync_post():
    management_user(platform_only=True)
    data = _body({'days'})
    try:
        costs=funding.sync_costs(days=data.get('days',7))
        limits=funding.sync_limits()
        return jsonify(costs=costs,limits=limits)
    except Exception as exc:
        current_app.logger.warning('Provider funding sync failed error_type=%s',type(exc).__name__)
        return jsonify(error='provider_funding_sync_unavailable'),503
