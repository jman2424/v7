# routes/auth_routes.py
from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, request, session
from routes import get_container
from routes.session_auth import clear_authenticated_session, establish_authenticated_session, is_authenticated_account_active
from retrieval.storage import Storage
from service.security import public_identity
from service.login_limiter import LoginThrottled

# Unique blueprint name to avoid: "auth already registered"
bp = Blueprint("auth_api", __name__, url_prefix="/auth")


@bp.get('/registration')
def registration_status():
    from service import registration, registration_mail
    return jsonify(enabled=registration_mail.configured(), sender=registration_mail.sender_address(),
                   request=registration.status())


@bp.post('/register')
def register_post():
    from service import registration
    if session.get('user'):
        return jsonify(error='Use Companies or Team access from your signed-in account.'), 400
    try:
        result = registration.start(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503
    return jsonify(request=result), 202


@bp.post('/register/confirm')
def register_confirm():
    from service import registration
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Enter your verification code.'), 400
    try:
        result = registration.confirm(data.get('code'))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    from service.audit import AuditService
    AuditService().record(user=result['email'], role='registration', ip=request.remote_addr or '',
                         action='registration.verified', target=result['tenant'], extra={'status': result['status']})
    return jsonify(request=result)


@bp.post("/login")
def login_post():
    c = get_container()

    if not request.is_json:
        return jsonify({"ok": False, "error": "json_required"}), 400

    data = request.get_json(silent=True) or {}
    if isinstance(data, dict) and set(data) - {'email', 'password', 'totp', 'tenant', 'csrf_token', 'remember_device'}:
        return jsonify(ok=False, error='invalid_credentials'), 400
    if not isinstance(data, dict) or any(not isinstance(data.get(key, ""), str) for key in ("email", "password", "totp", "tenant")):
        return jsonify({"ok": False, "error": "invalid_credentials"}), 400
    if not isinstance(data.get('remember_device', False), bool):
        return jsonify(ok=False, error='invalid_credentials'), 400
    if any(len(data.get(key, "")) > limit for key, limit in {"email": 254, "password": 1024, "totp": 32, "tenant": 64}.items()):
        return jsonify({"ok": False, "error": "invalid_credentials"}), 400
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    totp = (data.get("totp") or None)
    tenant = str(data.get("tenant") or c.settings.BUSINESS_KEY).strip()
    try:
        tenant = c.storage.canonical_tenant_key(Storage.validate_tenant_key(tenant))
        if not c.storage.tenant_exists(tenant):
            return jsonify({"ok": False, "error": "unknown_tenant"}), 404
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_tenant"}), 400

    from service.security import authenticate_user, login_tenant_scope
    from service.account_mfa import begin, complete_login
    from service import trusted_devices
    limiter = current_app.extensions["auth_login_limiter"]
    attempt_key = limiter.key(tenant=login_tenant_scope(c, email=email, tenant=tenant), identifier=email)
    try:
        attempt = limiter.begin(attempt_key)
    except LoginThrottled as exc:
        return jsonify(ok=False, error='try_again_later', retry_after=exc.retry_after), 429

    # IMPORTANT: pass container
    user = authenticate_user(c, email=email, password=password, tenant=tenant)
    if not user:
        limiter.fail(attempt_key, attempt)
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    trusted = trusted_devices.password_login(user, tenant) if not totp else None
    if trusted:
        identity, token, expires = trusted
        response = jsonify(ok=True, user=public_identity(identity), csrf_token=session.get('_csrf', ''))
        return trusted_devices.set_cookie(response, token, expires)

    if user.get("totp_secret") and totp:
        try:
            identity = complete_login(user, tenant, totp)
        except ValueError as exc:
            limiter.fail(attempt_key, attempt)
            error = 'authenticator_code_reused' if str(exc) == 'authenticator_code_reused' else 'invalid_credentials'
            return jsonify(ok=False, error=error), 401
    else:
        try:
            mfa = begin(user, tenant)
        except ValueError:
            limiter.fail(attempt_key, attempt)
            return jsonify(ok=False, error='invalid_credentials'), 401
        if not mfa:
            limiter.fail(attempt_key, attempt)
            return jsonify(ok=False, error='invalid_credentials'), 401
        # The password passed, but previous account failures remain until MFA
        # succeeds. Release only this request's temporary reservation.
        limiter.release(attempt_key, attempt)
        response = jsonify(ok=False, mfa_required=True, mfa=mfa, csrf_token=session['_csrf'])
        if request.cookies.get(trusted_devices.COOKIE_NAME):
            trusted_devices.clear_cookie(response)
        return response, 202

    response = jsonify({"ok": True, "user": public_identity(identity), "csrf_token": session.get("_csrf", "")})
    if data.get('remember_device', False):
        try:
            token, expires = trusted_devices.issue(user, tenant)
        except ValueError:
            clear_authenticated_session()
            return jsonify(ok=False, error='invalid_credentials'), 401
        trusted_devices.set_cookie(response, token, expires)
    return response


@bp.get("/session")
def session_get():
    user = session.get("user")
    if not isinstance(user, dict):
        from service.account_mfa import pending
        container = get_container()
        login_tenant = container.storage.canonical_tenant_key(container.settings.BUSINESS_KEY)
        return jsonify({"ok": True, "user": None, "mfa": pending(), "csrf_token": session.get("_csrf", ""),
                        "login_tenant": login_tenant})
    if not is_authenticated_account_active(get_container().storage):
        clear_authenticated_session()
        abort(401, description="unauthorized")
    return jsonify({"ok": True, "user": public_identity(user), "csrf_token": session.get("_csrf", "")})


@bp.post("/logout")
def logout_post():
    from service.trusted_devices import clear_cookie
    clear_authenticated_session(revoke_device=True)
    return clear_cookie(jsonify({"ok": True}))


@bp.get('/devices')
def devices_get():
    from service.security import management_user
    from service.trusted_devices import status
    return jsonify(status(management_user()))


@bp.delete('/devices')
def devices_delete():
    from service.security import management_user
    from service.trusted_devices import clear_cookie, revoke_account
    revoke_account(management_user())
    return clear_cookie(jsonify(ok=True))


@bp.post('/mfa/confirm')
def mfa_confirm():
    from service.account_mfa import confirm
    data = request.get_json(silent=True)
    if isinstance(data, dict) and set(data) - {'code', 'csrf_token', 'remember_device'}:
        return jsonify(error='invalid_authenticator_code'), 400
    if not isinstance(data, dict) or not isinstance(data.get('code'), str) or len(data['code']) > 32:
        return jsonify(error='invalid_authenticator_code'), 400
    if not isinstance(data.get('remember_device', False), bool):
        return jsonify(error='invalid_credentials'), 400
    try:
        user = confirm(data['code'])
    except LoginThrottled as exc:
        return jsonify(error='try_again_later', retry_after=exc.retry_after), 429
    except ValueError as exc:
        return jsonify(error=str(exc)), 401
    identity = establish_authenticated_session(user, user['tenant'], mfa_verified=True)
    response = jsonify(ok=True, user=public_identity(identity), csrf_token=session['_csrf'])
    if data.get('remember_device', False):
        from service import trusted_devices
        try:
            token, expires = trusted_devices.issue(user, user['tenant'])
        except ValueError:
            clear_authenticated_session()
            return jsonify(ok=False, error='invalid_credentials'), 401
        trusted_devices.set_cookie(response, token, expires)
    return response
