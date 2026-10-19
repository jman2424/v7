"""Public widget sales actions and owner-only requests."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, make_response, request, render_template
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer, URLSafeSerializer

from routes import get_container
from service.conversion_actions import (
    ActionError,
    public_availability,
    submit_action,
    load_actions,
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
        value = storage.canonical_tenant_key(value)
        exists = storage.tenant_exists(value)
    except ValueError:
        abort(400, description="invalid_tenant")
    if not exists:
        abort(404, description="tenant_not_found")
    from service.tenant_access import require_active
    require_active(value)
    return value


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
    configured_url = urlsplit(get_container().settings.BASE_URL)
    same_origin = f"{configured_url.scheme}://{configured_url.netloc}"
    request_url = urlsplit(request.host_url)
    loopback_names = {"localhost", "127.0.0.1", "::1"}
    local_preview_origin = (
        configured_url.hostname in loopback_names
        and request_url.hostname in loopback_names
        and origin == request.host_url.rstrip("/")
    )
    if origin != same_origin and not local_preview_origin and origin not in origins:
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


def _verify_token(value: object, tenant: str) -> str:
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
    return identity['id']


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
    if request.args.get("tenant") and _tenant(request.args["tenant"]) != tenant:
        return _cors(jsonify(error="tenant_mismatch")), 400
    _origin_allowed(tenant)
    try:
        conversation_id = _verify_token(data.get("conversation_token"), tenant)
        remote_ip = request.remote_addr or "unknown"
        ip_digest = hmac.new(
            current_app.secret_key.encode("utf-8"), remote_ip.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        result = submit_action(get_container().storage, tenant, data, ip_digest, conversation_id=conversation_id)
        if data.get('action') == 'consultation' and result.get('status') == 'confirmed':
            try:
                from service.booking_management import receipt_claims
                if load_actions(get_container().storage, tenant)['consultation'].get('manage_bookings', False):
                    result['receipt_token'] = _receipt_signer().dumps(receipt_claims(tenant, result['reference']))
            except Exception as error:
                from service.chat_diagnostics import emit
                emit('chat_optional_failure', phase='booking_receipt', error_type=type(error).__name__)
    except ActionError as error:
        return _cors(jsonify(error=error.code)), error.status
    return _cors(jsonify(result))


def _receipt_signer():
    return URLSafeSerializer(current_app.secret_key, salt='native-booking-receipt-v1')


@bp.get('/chat/booking')
def booking_page():
    tenant = _tenant(request.args.get('tenant'))
    return render_template('booking.html', tenant=tenant)


@bp.route('/chat/booking', methods=['POST', 'OPTIONS'])
def booking_operation():
    data = request.get_json(silent=True)
    if request.method == 'OPTIONS':
        tenant = _tenant(request.args.get('tenant'))
        _origin_allowed(tenant)
        return _cors(make_response('', 204))
    if not isinstance(data, dict):
        return _cors(jsonify(error='json_object_required')), 400
    tenant = _tenant(data.get('tenant'))
    _origin_allowed(tenant)
    try:
        token = data.get('receipt_token')
        if not isinstance(token, str) or len(token) > 2048:
            raise ActionError('invalid_receipt', 403)
        try:
            receipt = _receipt_signer().loads(token)
        except (BadSignature, SignatureExpired):
            raise ActionError('invalid_receipt', 403) from None
        if not isinstance(receipt, dict) or receipt.get('tenant') != tenant:
            raise ActionError('invalid_receipt', 403)
        import time
        if type(receipt.get('expires')) is not int or receipt['expires'] <= time.time():
            raise ActionError('invalid_receipt', 403)
        operation = data.get('operation', 'view')
        if operation != 'view' and data.get('confirm') is not True:
            raise ActionError('confirmation_required')
        if operation != 'view':
            from service.conversion_actions import _consume_rate_postgres, _consume_rate, _database
            from service import session_store
            digest = hmac.new(current_app.secret_key.encode(), (request.remote_addr or 'unknown').encode(), hashlib.sha256).hexdigest()
            if session_store._using_postgres():
                _consume_rate_postgres(digest)
            else:
                db = _database()
                try:
                    _consume_rate(db, digest)
                finally:
                    db.close()
        from service.booking_management import manage_booking
        result = manage_booking(get_container().storage, tenant, receipt.get('reference'), operation,
                                slot_id=data.get('slot_id'), expected_slot_id=data.get('expected_slot_id'))
        if operation != 'view':
            try:
                from service.audit import AuditService
                AuditService().record(user='booking receipt holder', role='customer', ip=request.remote_addr or '',
                    action='booking.'+operation, target=tenant+'/bookings/'+result['reference'],
                    after={'status':result['status'], 'slot_id':result['slot_id']})
            except Exception as error:
                from service.chat_diagnostics import emit
                emit('chat_optional_failure', phase='booking_audit', error_type=type(error).__name__)
        try:
            slots = public_availability(get_container().storage, tenant)['consultation']['slots']
        except ActionError:
            slots = []  # A committed cancellation must not become a false failure.
        return _cors(jsonify(ok=True, booking=result, slots=slots))
    except ActionError as error:
        return _cors(jsonify(error=error.code)), error.status
