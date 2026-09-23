"""Public widget sales actions and owner-only requests."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from flask import Blueprint, abort, current_app, jsonify, make_response, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from routes import get_container
from service.conversion_actions import (
    ActionError,
    public_availability,
    submit_action,
)
from connectors.web_widget import allowed_origins_from_branding


bp = Blueprint("conversion", __name__)


def _tenant(value: object) -> str:
    if value is None:
        value = get_container().settings.BUSINESS_KEY
    if not isinstance(value, str):
        abort(400, description="invalid_tenant")
    storage = get_container().storage
    try:
        path = storage.tenant_dir(value)
    except ValueError:
        abort(400, description="invalid_tenant")
    if not path.is_dir():
        abort(404, description="tenant_not_found")
    from service.tenant_access import require_active
    require_active(value)
    # Use the directory's actual case for signed tokens and SQLite keys on
    # case-insensitive filesystems, so one tenant cannot split slot inventory.
    return next(
        entry.name for entry in storage.business_root.iterdir()
        if entry.is_dir() and entry.name.casefold() == value.casefold()
    )


def _origin_allowed(tenant: str) -> None:
    origin = request.headers.get("Origin")
    if origin is None:
        # Browser cross-origin requests supply Origin; requests without one still
        # need a signed tenant token before they can create an action.
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403, description="origin_forbidden")
        return
    try:
        branding = get_container().storage.read_json(tenant, "branding.json")
    except (FileNotFoundError, OSError, ValueError):
        branding = {}
    origins = allowed_origins_from_branding(branding)
    same_origin = request.host_url.rstrip("/")
    if origin != same_origin and origin not in origins:
        abort(403, description="origin_forbidden")


def _cors(response):
    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Cache-Control"] = "no-store"
    return response


def _signer():
    # The existing web chat token can be reused for an action in that tenant.
    return URLSafeTimedSerializer(current_app.secret_key, salt="web-conversation-v1")


def _verify_token(value: object, tenant: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ActionError("conversation_required", 403)
    try:
        identity = _signer().loads(value, max_age=86400)
    except (BadSignature, SignatureExpired):
        raise ActionError("conversation_expired", 403) from None
    if (
        not isinstance(identity, dict)
        or identity.get("tenant") != tenant
        or not isinstance(identity.get("id"), str)
        or not identity["id"]
    ):
        raise ActionError("invalid_conversation", 403)


@bp.route("/chat/actions", methods=["OPTIONS"])
def options_chat_actions():
    tenant = _tenant(request.args.get("tenant"))
    _origin_allowed(tenant)
    return _cors(make_response("", 204))


@bp.get("/chat/actions")
def get_chat_actions():
    tenant = _tenant(request.args.get("tenant"))
    _origin_allowed(tenant)
    try:
        availability = public_availability(get_container().storage, tenant)
    except ActionError as error:
        return _cors(jsonify(error=error.code)), error.status
    availability["conversation_token"] = _signer().dumps(
        {"tenant": tenant, "id": "action:" + secrets.token_urlsafe(24)}
    )
    return _cors(jsonify(availability))


@bp.post("/chat/actions")
def post_chat_actions():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _cors(jsonify(error="json_object_required")), 400
    tenant = _tenant(data.get("tenant"))
    if request.args.get("tenant") and request.args["tenant"] != tenant:
        return _cors(jsonify(error="tenant_mismatch")), 400
    _origin_allowed(tenant)
    try:
        _verify_token(data.get("conversation_token"), tenant)
        remote_ip = request.remote_addr or "unknown"
        ip_digest = hmac.new(
            current_app.secret_key.encode("utf-8"), remote_ip.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        result = submit_action(get_container().storage, tenant, data, ip_digest)
    except ActionError as error:
        return _cors(jsonify(error=error.code)), error.status
    return _cors(jsonify(result))
