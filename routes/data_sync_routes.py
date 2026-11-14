"""Data Sources & Sync: owner-authorised connections, import previews and signed source notifications."""
from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, request, session

from connectors import store_sync
from routes import get_container
from routes.session_auth import clear_authenticated_session, is_authenticated_account_active
from routes.tenancy import is_platform_operator, require_admin_role, resolve_admin_tenant, user_roles
from service import business_sync as sync, data_sources as sources, sync_store as store, sync_worker
from service.audit import AuditService
from service.security import has_permission, management_user, require_permission

bp = Blueprint('data_sync', __name__)
_API = '/admin/api/data-sources'
_STATUS = {'source_not_found': 404, 'change_not_found': 404, 'data_source_changed': 409, 'change_already_handled': 409,
           'changed_since_import': 409, 'undo_unavailable': 409, 'sync_rate_limited': 429, 'data_source_limit': 409}


def _tenant():
    return resolve_admin_tenant(request.args.get('tenant') or '', str(get_container().settings.BUSINESS_KEY))


@bp.before_request
def _guard():
    if not request.path.startswith(_API):
        return  # Source notifications authenticate with their own signature.
    if not session.get('user'):
        abort(401, description='unauthorized')
    if not is_authenticated_account_active(get_container().storage):
        clear_authenticated_session()
        abort(401, description='unauthorized')
    require_admin_role()
    require_permission('integrations.read')
    if request.method == 'GET':
        return
    user, tenant = management_user(), _tenant()
    # Only the owner (or the platform operator setting a business up) can
    # authorise access to a business's systems or change its information in bulk.
    if not is_platform_operator() and 'business_owner' not in user_roles():
        abort(403, description='business_owner_required')
    if not (has_permission(user, 'business_settings.write') and has_permission(user, 'offerings.write')):
        abort(403, description='forbidden')
    if not is_platform_operator():
        from service.tenant_access import require_active
        require_active(tenant)
    AuditService().record(user=user['id'], role=user['roles'][0], ip=request.remote_addr or '',
                          action='data_sources.request', target=f'{tenant}/{request.endpoint}',
                          extra={'tenant': tenant, 'source': 'API', 'result': 'attempted'})


def _start(container, tenant, job):
    """Hand the job to the background worker, or run it here when none is running."""
    if sources.worker_enabled():
        sync_worker.wake()
    else:
        sources.run_now(container, tenant, job)


def _fail(error):
    code = getattr(error, 'code', None) or 'invalid_request'
    return jsonify(error=code), _STATUS.get(code, 400)


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description='json_object_required')
    return data


def _change(changeset, *, offset=0, limit=200):
    rows = [row for row in changeset['changes'] if row['action'] != 'unchanged']
    return {key: changeset[key] for key in ('id', 'source_id', 'origin', 'state', 'summary', 'actor', 'created',
                                            'updated', 'version', 'can_undo')} | {
        'rows': [sources.public_row(row) for row in rows[offset:offset + limit]], 'total_rows': len(rows),
        'next_offset': offset + limit if offset + limit < len(rows) else None}


@bp.get(_API)
def listing():
    tenant = _tenant()
    history = store.list_changesets(tenant)
    response = jsonify(
        sources=[sources.public(row) for row in store.list_sources(tenant) if row['status'] != 'disconnected'],
        reviews=[row for row in history if row['state'] == 'pending'],
        history=[row for row in history if row['state'] in {'applied', 'rejected', 'rolled_back'}][:15],
        authorisation_statement=sources.AUTHORISATION_STATEMENT, terms_version=sync.TERMS_VERSION,
        website_statement=sources.WEBSITE_STATEMENT,
        website=sources.website_address(get_container().storage, tenant)[1],
        permissions=[{key: row[key] for key in ('kind', 'domain', 'statement', 'terms_version', 'account',
                                                'granted', 'ended', 'end_reason', 'ended_by')}
                     for row in store.list_consents(tenant, limit=50)],
        can_manage=bool(is_platform_operator() or 'business_owner' in user_roles()),
        automatic_updates_running=sources.worker_enabled())
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.post(_API)
def connect():
    tenant, container, body = _tenant(), get_container(), _body()
    try:
        if body.get('kind') == 'website':
            source, credentials = sources.connect_website(container.storage, tenant, management_user(), body), {}
        else:
            source, credentials = sources.connect(tenant, management_user(), body)
        job = sources.request_sync(tenant, source['id'], reason='connect')
    except sources.SourceError as exc:
        return _fail(exc)
    _start(container, tenant, job)
    source = store.get_source(tenant, source['id'])
    instant = None if source['kind'] == 'website' else sources.webhook_setup(
        container.settings.BASE_URL, tenant, source, credentials)
    response = jsonify(source=sources.public(source), instant_updates=instant)
    response.headers['Cache-Control'] = 'no-store'
    return response, 201


@bp.put(_API + '/<source_id>')
def settings(source_id):
    try:
        return jsonify(source=sources.public(sources.change_settings(_tenant(), source_id, _body())))
    except sources.SourceError as exc:
        return _fail(exc)


@bp.post(_API + '/<source_id>/sync')
def sync_now(source_id):
    tenant = _tenant()
    try:
        job = sources.request_sync(tenant, source_id)
    except sources.SourceError as exc:
        return _fail(exc)
    _start(get_container(), tenant, job)
    return jsonify(source=sources.public(store.get_source(tenant, source_id)))


@bp.post(_API + '/<source_id>/reconnect')
def reconnect(source_id):
    tenant, container = _tenant(), get_container()
    try:
        source, credentials = sources.reconnect(tenant, management_user(), source_id, _body())
        _start(container, tenant, sources.request_sync(tenant, source_id, reason='reconnect'))
    except sources.SourceError as exc:
        return _fail(exc)
    response = jsonify(source=sources.public(store.get_source(tenant, source_id)),
                       instant_updates=sources.webhook_setup(container.settings.BASE_URL, tenant, source, credentials))
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.post(_API + '/<source_id>/disconnect')
def disconnect(source_id):
    try:
        sources.disconnect(_tenant(), source_id, actor=str(management_user()['id']), storage=get_container().storage)
        get_container().invalidate_tenant(_tenant())
    except sources.SourceError as exc:
        return _fail(exc)
    return jsonify(ok=True)


@bp.post(_API + '/imports')
def create_import():
    try:
        changeset, summary = sources.create_import(get_container(), _tenant(), management_user(), _body())
    except (sources.SourceError, sync.SyncError) as exc:
        return _fail(exc)
    return jsonify(change=_change(changeset) if changeset else None, summary=summary), 201


def _load_change(tenant, change_id):
    try:
        changeset = store.get_changeset(tenant, change_id)
    except ValueError:
        changeset = None
    if changeset is None:
        abort(404)
    return changeset


@bp.get(_API + '/changes/<change_id>')
def change_get(change_id):
    try:
        offset = int(request.args.get('offset') or 0)
    except ValueError:
        abort(400)
    if not 0 <= offset <= 100000:
        abort(400)
    return jsonify(change=_change(_load_change(_tenant(), change_id), offset=offset))


@bp.put(_API + '/changes/<change_id>')
def change_correct(change_id):
    try:
        return jsonify(change=_change(sources.correct(_tenant(), change_id, _body())))
    except sources.SourceError as exc:
        return _fail(exc)


@bp.post(_API + '/changes/<change_id>/<decision>')
def change_decide(change_id, decision):
    if decision not in {'apply', 'reject', 'undo'}:
        abort(404)
    tenant, user, body = _tenant(), management_user(), _body()
    _load_change(tenant, change_id)
    version = body.get('version') if type(body.get('version')) is int else None
    try:
        if decision == 'apply':
            result = sync.apply_changeset(get_container(), tenant, change_id, actor=user['id'], expected_version=version)
        elif decision == 'reject':
            result = sync.reject_changeset(tenant, change_id, actor=user['id'], expected_version=version)
        else:
            result = sync.rollback(get_container(), tenant, change_id, actor=user['id'])
    except sync.SyncError as exc:
        return _fail(exc)
    except ValueError:
        return jsonify(error='change_already_handled'), 409
    return jsonify(change=_change(result, limit=0))


@bp.get(_API + '/diagnostics')
def diagnostics():
    """Operator-only detail. Codes and counts; never payloads or credentials."""
    if not is_platform_operator():
        abort(403)
    tenant = _tenant()
    return jsonify(jobs=store.job_counts(tenant), sources=[
        {key: row[key] for key in ('id', 'kind', 'label', 'status', 'last_error', 'last_success', 'last_attempt',
                                   'next_poll', 'interval_minutes', 'auto_sync', 'auto_apply')}
        for row in store.list_sources(tenant)])


@bp.post('/sync/hooks/<tenant>/<source_id>')
def source_notification(tenant, source_id):
    container = get_container()
    try:
        tenant = container.storage.validate_tenant_key(tenant)
        source = store.get_source(tenant, source_id)
    except ValueError:
        abort(404)
    if source is None or source['status'] == 'disconnected' or source['kind'] in {'upload', 'website'}:
        abort(404)
    raw = request.get_data()
    try:
        credentials = store.unseal(tenant, source['secret'])
    except ValueError:
        abort(404)
    if not store_sync.verify_webhook(source['kind'], source['config'], credentials, request.headers, raw):
        if source['kind'] == 'woocommerce' and raw.startswith(b'webhook_id='):
            return jsonify(ok=True)  # WooCommerce's unsigned set-up ping; nothing is processed.
        abort(401)
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError):
        abort(400)
    event = store_sync.parse_webhook(source['kind'], request.headers, payload, raw)
    if event is None:
        return jsonify(ok=True, ignored=True)
    try:
        job, created = store.enqueue(tenant, source_id, 'event', 'hook:' + str(event['event_id'])[:200], {
            'records': event['records'], 'deleted': event['deleted'], 'replace': bool(event.get('replace'))})
    except ValueError:
        abort(429)
    if created:
        _start(container, tenant, job)
    return jsonify(ok=True, duplicate=not created)
