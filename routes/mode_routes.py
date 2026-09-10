from flask import Blueprint, jsonify, request

from routes import get_container
from service.security import authorized_tenant, require_management

bp = Blueprint("mode", __name__)


@bp.get("/mode")
@require_management()
def get_mode():
    c = get_container()
    tenant = authorized_tenant(request.args.get("tenant"))
    return jsonify(ok=True, tenant=tenant, mode=c.settings.MODE)
