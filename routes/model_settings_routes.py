"""Two explicit confirmation steps before committing a tenant model change."""
import secrets
import time
from flask import Blueprint, abort, jsonify, request, session
from routes import get_container
from service.security import management_user, authorized_tenant, is_platform_admin, require_permission, has_permission
from service import model_settings
from service.audit import AuditService

bp = Blueprint('model_settings',__name__,url_prefix='/admin/api/ai-model')


def identity(write=True, require_activation=True):
    user = management_user()
    if not is_platform_admin(user) and user.get('roles') != ['business_owner']:
        abort(403)
    permission = ('models.' if is_platform_admin(user) else 'business_settings.') + ('write' if write else 'read')
    require_permission(permission, user=user)
    tenant = authorized_tenant(request.args.get('tenant'))
    storage = get_container().storage
    if not storage.tenant_exists(tenant): abort(404)
    if require_activation and not is_platform_admin(user):
        from service.tenant_access import require_active
        require_active(tenant)
    return user,tenant,storage


def body(allowed):
    data = request.get_json(silent=True)
    if not isinstance(data,dict) or set(data) - {*allowed, 'csrf_token'}: abort(400)
    return data


@bp.get('/parameters')
def parameters_get():
    _, tenant, storage = identity(write=False)
    return jsonify(model_settings.parameter_status(storage, tenant))


@bp.get('/memory')
def memory_get():
    from service.conversation_memory import status
    _, tenant, storage = identity(write=False)
    return jsonify(status(storage, tenant))


@bp.route('/memory', methods=['PUT', 'DELETE'])
def memory_save():
    from service.conversation_memory import status, validated
    user, tenant, storage = identity()
    data = body({'settings', 'revision'})
    if not isinstance(data.get('revision'), str):
        abort(400, description='invalid_memory_revision')
    clearing = request.method == 'DELETE'
    try:
        config = None if clearing else validated(data.get('settings'))
    except ValueError as exc:
        abort(400, description=str(exc))
    with storage.write_lock(tenant):
        before = model_settings.document(storage, tenant)
        if model_settings.revision(before) != data['revision']:
            abort(409, description='Memory settings changed. Reload before saving.')
        after = dict(before)
        if config is not None:
            after['memory'] = config
        if clearing or (config is not None and not config['enabled']):
            after['memory_generation'] = secrets.token_hex(16)
        if clearing and not any(key in after for key in ('model', 'parameters', 'memory')):
            after['memory'] = validated({})
        entry = dict(user=user['id'], role=user['roles'][0], ip=request.remote_addr or '',
                     action='ai_memory.clear' if clearing else 'ai_memory.settings', target=tenant,
                     before=before.get('memory', {}), after=after.get('memory', {}))
        audit = AuditService()
        audit.record(**entry, extra={'result': 'prepared', 'source': 'API'})
        storage._write_json(tenant, model_settings.FILENAME, after)
    audit.record(**entry, extra={'result': 'success', 'source': 'API'})
    return jsonify(status(storage, tenant, after))


@bp.get('')
def model_get():
    user, tenant, storage = identity(write=False, require_activation=False)
    permission = 'models.write' if is_platform_admin(user) else 'business_settings.write'
    from service.tenant_access import activation
    return jsonify(**model_settings.parameter_status(storage, tenant),
                   model_options=model_settings.options(),
                   can_change_model=has_permission(user, permission)
                   and (is_platform_admin(user) or activation(tenant)['active']))


@bp.put('/parameters')
def parameters_put():
    user, tenant, storage = identity()
    data = body({'parameters', 'revision'})
    if set(data) - {'parameters', 'revision', 'csrf_token'} or not isinstance(data.get('revision'), str):
        abort(400, description='invalid_ai_parameters')
    try:
        parameters = model_settings.validated_parameters(data.get('parameters'))
    except ValueError as exc:
        abort(400, description=str(exc))
    with storage.write_lock(tenant):
        before = model_settings.document(storage, tenant)
        if model_settings.revision(before) != data['revision']:
            abort(409, description='Settings changed. Reload the AI parameters.')
        status = model_settings.parameter_status(storage, tenant, before)
        if ('reasoning_effort' in parameters
                and parameters['reasoning_effort'] not in status['capabilities']['reasoning_efforts']):
            abort(400, description='invalid_reasoning_effort')
        after = {**before, 'parameters': parameters}
        audit = AuditService()
        entry = dict(user=user['id'], role=user['roles'][0], ip=request.remote_addr or '',
            action='ai_model.parameters', target=tenant, before=before.get('parameters', {}),
            after=parameters)
        metadata = {'tenant': tenant, 'source': 'API', 'before_revision': data['revision'],
                    'after_revision': model_settings.revision(after)}
        audit.record(**entry, extra={**metadata, 'result': 'prepared'})
        storage._write_json(tenant, model_settings.FILENAME, after)
    audit.record(**entry, extra={**metadata, 'result': 'success'})
    return jsonify(model_settings.parameter_status(storage, tenant, after))


def pending(data, user, tenant, stage):
    change = session.get('model_change') or {}
    token = data.get('token')
    if (not isinstance(token,str) or change.get('stage') != stage
            or change.get('actor') != user['id'] or change.get('tenant') != tenant
            or change.get('expires',0) < time.time()
            or not secrets.compare_digest(token,change.get('token',''))):
        abort(409,description='Review and confirm the model change again.')
    return change


@bp.post('/review')
def review():
    user,tenant,storage = identity()
    data = body({'model'})
    if data.get('model') not in model_settings.MODELS: abort(400)
    change = {'actor':user['id'],'tenant':tenant,'model':data['model'],
              'revision':model_settings.revision(model_settings.document(storage,tenant)),
              'stage':'review','expires':time.time()+600,'token':secrets.token_urlsafe(24)}
    session['model_change'] = change
    return jsonify(token=change['token'],model=change['model'])


@bp.post('/confirm')
def confirm():
    user,tenant,_ = identity()
    data = body({'token', 'acknowledge_cost_and_responses'})
    change = pending(data,user,tenant,'review')
    if data.get('acknowledge_cost_and_responses') is not True: abort(400)
    session['model_change'] = {**change,'stage':'save','token':secrets.token_urlsafe(24)}
    return jsonify(token=session['model_change']['token'],model=change['model'])


@bp.put('')
def save():
    user,tenant,storage = identity()
    data = body({'token', 'confirm_and_save'})
    change = pending(data,user,tenant,'save')
    if data.get('confirm_and_save') is not True: abort(400)
    with storage.write_lock(tenant):
        before = model_settings.document(storage,tenant)
        if model_settings.revision(before) != change['revision']:
            abort(409,description='Settings changed. Review and confirm again.')
        parameters = model_settings.validated_parameters(before.get('parameters', {}))
        if parameters.get('reasoning_effort') not in model_settings.capabilities(change['model'])['reasoning_efforts']:
            parameters.pop('reasoning_effort', None)
        after = {**before, 'model':change['model'], 'parameters': parameters, 'generation':secrets.token_hex(16)}
        audit = AuditService()
        entry = {'user': user['id'], 'role': user['roles'][0], 'ip': request.remote_addr or '',
                 'action': 'ai_model.change', 'target': tenant,
                 'before': {'model': before.get('model')}, 'after': {'model': change['model']}}
        metadata = {'tenant': tenant, 'source': 'API', 'before_revision': change['revision'],
                    'after_revision': model_settings.revision(after)}
        audit.record(**entry, extra={**metadata, 'result':'prepared'})
        storage._write_json(tenant,model_settings.FILENAME,after)
    # Record completion after the repository transaction has committed.
    audit.record(**entry, extra={**metadata, 'result':'success'})
    session.pop('model_change',None)
    return jsonify(ok=True,model=change['model'])
