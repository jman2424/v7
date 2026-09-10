from flask import Blueprint, jsonify, request, session

from routes import get_container
from service import session_store
from service.security import (
    authenticate_user,
    management_user,
    start_management_session,
    verify_totp,
)

bp = Blueprint("auth_api", __name__, url_prefix="/auth")


@bp.get("/session")
def session_info():
    user = management_user() if session.get("management_token") else None
    return jsonify(user=user, csrf_token=session["_csrf"])


@bp.post("/login")
def login_post():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error="json_object_required"), 400
    user = authenticate_user(get_container(), email=data.get("email"), password=data.get("password"))
    if not user or not verify_totp(user.get("totp_secret"), data.get("totp", "")):
        return jsonify(ok=False, error="invalid_credentials"), 401
    identity = start_management_session(user)
    return jsonify(ok=True, user=identity, csrf_token=session["_csrf"])


@bp.post("/logout")
def logout_post():
    session_store.revoke(session.get("management_token"))
    session.clear()
    return jsonify(ok=True)
