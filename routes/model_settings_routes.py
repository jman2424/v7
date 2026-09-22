"""Two explicit confirmation steps before committing a tenant model change."""
import secrets
import time
from flask import Blueprint, abort, jsonify, request, session
from routes import get_container
from service.security import management_user, authorized_tenant, is_platform_admin
from service import model_settings
from service.audit import AuditService

bp = Blueprint('model_settings',__name__,url_prefix='/admin/api/ai-model')


def identity():
    user = management_user()
    if not is_platform_admin(user) and user.get('roles') != ['business_owner']:
        abort(403)
    tenant = authorized_tenant(request.args.get('tenant'))
    storage = get_container().storage
    if not storage.tenant_dir(tenant).is_dir(): abort(404)
    if not is_platform_admin(user):
        from service.tenant_access import require_active
        require_active(tenant)
    return user,tenant,storage


def body():
    data = request.get_json(silent=True)
    if not isinstance(data,dict): abort(400)
    return data


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
    data = body()
    if data.get('model') not in model_settings.MODELS: abort(400)
    change = {'actor':user['id'],'tenant':tenant,'model':data['model'],
              'revision':model_settings.revision(model_settings.document(storage,tenant)),
              'stage':'review','expires':time.time()+600,'token':secrets.token_urlsafe(24)}
    session['model_change'] = change
    return jsonify(token=change['token'],model=change['model'])


@bp.post('/confirm')
def confirm():
    user,tenant,_ = identity()
    data = body()
    change = pending(data,user,tenant,'review')
    if data.get('acknowledge_cost_and_responses') is not True: abort(400)
    session['model_change'] = {**change,'stage':'save','token':secrets.token_urlsafe(24)}
    return jsonify(token=session['model_change']['token'],model=change['model'])


@bp.put('')
def save():
    user,tenant,storage = identity()
    data = body()
    change = pending(data,user,tenant,'save')
    if data.get('confirm_and_save') is not True: abort(400)
    with storage.write_lock():
        before = model_settings.document(storage,tenant)
        if model_settings.revision(before) != change['revision']:
            abort(409,description='Settings changed. Review and confirm again.')
        AuditService().record(user=user['id'],role=user['roles'][0],ip=request.remote_addr or '',
            action='ai_model.change',target=tenant,before={'model':before.get('model')},
            after={'model':change['model']},extra={'result':'prepared'})
        storage._write_json(tenant,model_settings.FILENAME,{'model':change['model'],'generation':secrets.token_hex(16)})
    session.pop('model_change',None)
    return jsonify(ok=True,model=change['model'])
