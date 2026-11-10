"""Owner-controlled marketing drafts, approval and provider submission."""
from flask import Blueprint, abort, jsonify, request

from routes import get_container
from service import email_campaigns as campaigns
from service.security import authorized_tenant, is_platform_admin, management_user, require_permission
from service.tenant_access import require_active


bp = Blueprint('email_campaigns', __name__, url_prefix='/admin/api/email-campaigns')


def _context(*, active=False):
    user = management_user()
    if not is_platform_admin(user) and 'business_owner' not in user['roles']:
        abort(403)
    require_permission('business_settings.write', user=user)
    tenant = authorized_tenant(request.args.get('tenant'))
    if active:
        require_active(tenant)
    return get_container(), tenant, user['id']


def _body(*fields):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - {'csrf_token'} != set(fields):
        raise campaigns.CampaignError('invalid_campaign_request')
    return {field: data[field] for field in fields}


@bp.errorhandler(campaigns.CampaignError)
def _campaign_error(error):
    return jsonify(error=error.code), error.status


@bp.after_request
def _private(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.get('')
def list_campaigns():
    container, tenant, _ = _context()
    return jsonify(campaigns.listing(container.storage, tenant))


@bp.post('')
def create_campaign():
    container, tenant, actor = _context()
    row = campaigns.create(container.storage, tenant, actor, **_body('title', 'subject', 'body'))
    return jsonify(campaign=row), 201


@bp.put('/<identifier>')
def edit_campaign(identifier):
    container, tenant, _ = _context()
    row = campaigns.edit(container.storage, tenant, identifier, **_body('revision', 'title', 'subject', 'body'))
    return jsonify(campaign=row)


@bp.post('/generate')
def generate_campaign():
    from service.channel_intelligence import draft_campaign

    container, tenant, _ = _context(active=True)
    brief = campaigns.checked_text(_body('brief')['brief'], 1200, multiline=True)
    campaigns.reserve_generation(container.storage, tenant)
    body = draft_campaign(container, tenant, brief)
    if not body:
        raise campaigns.CampaignError('campaign_draft_unavailable', 422)
    return jsonify(body=campaigns.checked_text(body, 6000, multiline=True))


@bp.post('/<identifier>/review')
def review_campaign(identifier):
    container, tenant, actor = _context(active=True)
    data = _body('revision', 'consent_confirmed')
    if data['consent_confirmed'] is not True:
        raise campaigns.CampaignError('campaign_consent_confirmation_required')
    row = campaigns.review(container.storage, tenant, identifier, data['revision'], actor)
    return jsonify(campaign=row)


@bp.post('/<identifier>/send')
def send_campaign(identifier):
    container, tenant, actor = _context(active=True)
    data = _body('revision', 'confirmed')
    if data['confirmed'] is not True:
        raise campaigns.CampaignError('campaign_send_confirmation_required')
    row = campaigns.send(container.storage, tenant, identifier, data['revision'], actor)
    return jsonify(campaign=row)


@bp.post('/<identifier>/reconcile')
def reconcile_campaign(identifier):
    container, tenant, _ = _context()
    row = campaigns.reconcile(container.storage, tenant, identifier, _body('revision')['revision'])
    return jsonify(campaign=row)
