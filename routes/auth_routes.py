# routes/auth_routes.py
from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, request, session
from routes import get_container
from routes.session_auth import clear_authenticated_session, establish_authenticated_session, is_authenticated_account_active
from retrieval.storage import Storage
from service.security import public_identity

# Unique blueprint name to avoid: "auth already registered"
bp = Blueprint("auth_api", __name__, url_prefix="/auth")


@bp.get('/registration')
def registration_status():
    from service import registration, registration_mail
    return jsonify(enabled=registration_mail.configured(), request=registration.status())


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
    if not isinstance(data, dict) or any(not isinstance(data.get(key, ""), str) for key in ("email", "password", "totp", "tenant")):
        return jsonify({"ok": False, "error": "invalid_credentials"}), 400
    if any(len(data.get(key, "")) > limit for key, limit in {"email": 320, "password": 1024, "totp": 32, "tenant": 64}.items()):
        return jsonify({"ok": False, "error": "invalid_credentials"}), 400
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    totp = (data.get("totp") or None)
    tenant = str(data.get("tenant") or c.settings.BUSINESS_KEY).strip()
    try:
        tenant = Storage.validate_tenant_key(tenant)
        if not c.storage.tenant_dir(tenant).is_dir():
            return jsonify({"ok": False, "error": "unknown_tenant"}), 404
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_tenant"}), 400

    limiter = current_app.extensions["auth_login_limiter"]
    attempt_key = limiter.key(client_address=request.remote_addr or "unknown", tenant=tenant, identifier=email)
    retry_after = limiter.retry_after(attempt_key)
    if retry_after:
        return jsonify({"ok": False, "error": "try_again_later", "retry_after": retry_after}), 429

    from service.security import authenticate_user, verify_totp

    # IMPORTANT: pass container
    user = authenticate_user(c, email=email, password=password, tenant=tenant)
    if not user:
        limiter.record_failure(attempt_key)
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    if user.get("totp_secret") and totp:
        if not verify_totp(user["totp_secret"], totp):
            limiter.record_failure(attempt_key)
            return jsonify({"ok": False, "error": "invalid_credentials"}), 401
    else:
        from service.account_mfa import begin
        mfa = begin(user, tenant)
        return jsonify(ok=False, mfa_required=True, mfa=mfa, csrf_token=session['_csrf']), 202

    limiter.reset(attempt_key)
    identity = establish_authenticated_session(user, tenant, mfa_verified=True)
    return jsonify({"ok": True, "user": public_identity(identity), "csrf_token": session.get("_csrf", "")})


@bp.get("/session")
def session_get():
    user = session.get("user")
    if not isinstance(user, dict):
        from service.account_mfa import pending
        return jsonify({"ok": True, "user": None, "mfa": pending(), "csrf_token": session.get("_csrf", "")})
    if not is_authenticated_account_active(get_container().storage):
        clear_authenticated_session()
        abort(401, description="unauthorized")
    return jsonify({"ok": True, "user": public_identity(user), "csrf_token": session.get("_csrf", "")})


@bp.post("/logout")
def logout_post():
    clear_authenticated_session()
    return jsonify({"ok": True})


@bp.post('/mfa/confirm')
def mfa_confirm():
    from service.account_mfa import confirm
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('code'), str) or len(data['code']) > 32:
        return jsonify(error='invalid_authenticator_code'), 400
    try:
        user = confirm(data['code'])
    except ValueError as exc:
        return jsonify(error=str(exc)), 401
    identity = establish_authenticated_session(user, user['tenant'], mfa_verified=True)
    return jsonify(ok=True, user=public_identity(identity), csrf_token=session['_csrf'])
