"""Existing MFA sessions/CSRF protect application and platform review APIs."""
from flask import Blueprint, abort, current_app, jsonify, request

from routes import get_container
from service import business_applications as applications
from service.security import authorized_tenant, is_platform_admin, management_user

bp = Blueprint('business_applications', __name__, url_prefix='/business-applications')


@bp.errorhandler(applications.ApplicationError)
def application_error(error):
    return jsonify(error=error.code), error.status


def _body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        abort(400, description='json_object_required')
    return value


def _tenant(*, write=False, operator=False):
    user = management_user(platform_only=operator)
    if write and not is_platform_admin(user) and 'business_owner' not in user['roles']:
        abort(403, description='company_owner_required')
    tenant = authorized_tenant(request.args.get('tenant'))
    if not get_container().storage.tenant_exists(tenant):
        abort(404, description='unknown_tenant')
    return tenant, user


@bp.get('/policy')
def policy_get():
    return jsonify(applications.settings(public=True))


@bp.get('/current')
def current_get():
    tenant, _ = _tenant()
    storage = get_container().storage
    profile = storage.read_json(tenant, 'store_info.json')
    profile = profile if isinstance(profile, dict) else {}
    return jsonify(application=applications.get(tenant), policy=applications.settings(public=True),
                   prefill={'business_name': str(profile.get('name') or '')[:120],
                            'website': str(profile.get('website') or '')[:2048]})


@bp.post('/current')
def current_post():
    tenant, user = _tenant(write=True)
    # Contact verification comes from the authenticated account, never JSON.
    result = applications.submit_verified(tenant, user['email'], _body())
    return jsonify(application=result), 201


@bp.put('/current')
def current_put():
    tenant, user = _tenant(write=True)
    return jsonify(application=applications.update(tenant, _body(), user['email'], actor=user['id']))


@bp.post('/cancel')
def cancel_post():
    tenant, user = _tenant(write=True)
    return jsonify(application=applications.cancel(tenant, _body(), user['id']))


@bp.post('/close-payments')
def close_payments_post():
    tenant, _ = _tenant(write=True)
    try:
        return jsonify(applications.close_payments(tenant))
    except applications.ApplicationError:
        raise
    except Exception as exc:
        current_app.logger.warning('Application checkout reconciliation failed error_type=%s', type(exc).__name__)
        return jsonify(error='application_checkout_reconciliation_failed'), 409


@bp.get('/queue')
def queue_get():
    management_user(platform_only=True)
    page = request.args.get('page', '1')
    if not page.isascii() or not page.isdigit() or len(page) > 5:
        abort(400, description='invalid_application_page')
    return jsonify(applications.list_applications(status=request.args.get('status', ''),
                   search=request.args.get('search', ''), sort=request.args.get('sort', 'newest'), page=int(page)))


@bp.get('/review')
def review_get():
    tenant, _ = _tenant(operator=True)
    value = applications.get(tenant, private=True)
    if value is None:
        abort(404, description='application_not_found')
    return jsonify(application=value)


@bp.post('/review')
def review_post():
    tenant, _ = _tenant(write=True, operator=True)
    return jsonify(application=applications.review(tenant, _body()))


@bp.get('/settings')
def settings_get():
    management_user(platform_only=True)
    return jsonify(settings=applications.settings())


@bp.put('/settings')
def settings_put():
    management_user(platform_only=True)
    return jsonify(settings=applications.save_settings(_body()))


@bp.post('/research')
def research_post():
    tenant, _ = _tenant(write=True, operator=True)
    from service.application_research import queue
    queue(tenant, _body())
    return jsonify(queued=True), 202
