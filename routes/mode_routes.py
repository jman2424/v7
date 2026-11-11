"""Reports the response strategy (v5/v6/v7) a tenant currently runs."""
from flask import Blueprint, jsonify, request

from routes import get_container
from service.security import authorized_tenant, require_management, require_permission

bp = Blueprint("mode", __name__)


@bp.get("/mode")
@require_management()
def get_mode():
    require_permission("business_settings.read")
    c = get_container()
    tenant = authorized_tenant(request.args.get("tenant"))
    from service.ai_mode import tenant_mode
    return jsonify(ok=True, tenant=tenant, mode=tenant_mode(c.for_tenant(tenant).overrides).upper())
