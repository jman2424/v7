"""OAuth sign-in uses explicit existing-account links and the normal MFA policy."""
from flask import Blueprint, jsonify, redirect, request, session
from werkzeug.exceptions import HTTPException

from service import oidc_login
from service.audit import AuditService
from service.security import management_user

bp = Blueprint('oidc_login', __name__, url_prefix='/auth/oidc')


def _audit(action, provider, user):
    AuditService().record(user=user['email'], role=','.join(user['roles']), ip=request.remote_addr or '',
                         action=action, target=provider)


@bp.get('/providers')
def providers():
    user = management_user() if session.get('user') else None
    return jsonify(oidc_login.providers_status(user))


@bp.post('/<provider>/start')
def start(provider):
    from service.session_store import allow_login
    if not allow_login(request.remote_addr or 'unknown'):
        return jsonify(error='try_again_later'), 429
    try:
        result = oidc_login.start(provider, request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(result)


@bp.get('/<provider>/callback')
def callback(provider):
    if provider not in oidc_login.PROVIDERS:
        return jsonify(error='unknown_provider'), 404
    result, user, trusted = 'failed', None, None
    if (len(request.args.getlist('state')) == 1 and len(request.args.getlist('code')) <= 1
            and len(request.args.getlist('error')) <= 1):
        try:
            result, user, trusted = oidc_login.finish(provider, request.args['state'], request.args.get('code'),
                                                     provider_error='error' in request.args)
        except (ValueError, HTTPException):
            # Never echo provider messages, tokens, internal errors or return URLs.
            result = 'failed'
    if user:
        _audit('auth.oidc.' + result, provider, user)
    response = redirect('/console/?oidc=' + result + '&provider=' + provider, code=303)
    response.headers['Referrer-Policy'] = 'no-referrer'
    if trusted:
        from service.trusted_devices import set_cookie
        response = set_cookie(response, trusted[1], trusted[2])
    return response


@bp.delete('/<provider>/link')
def disconnect(provider):
    user = management_user()
    try:
        oidc_login.disconnect(provider, user)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    _audit('auth.oidc.disconnect', provider, user)
    return jsonify(ok=True)
