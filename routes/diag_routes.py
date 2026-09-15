from flask import Blueprint, jsonify, request

from routes import get_container
from service.security import authorized_tenant, require_management

bp = Blueprint("diag", __name__, url_prefix="/__diag")


@bp.get("/validate")
@bp.get("/selfrepair")
@bp.get("/self_repair")
@require_management()
def validate_all():
    c = get_container()
    tenant = authorized_tenant(request.args.get("tenant"))
    report = c.storage.validate_tenant(tenant)
    # Schema errors can contain the rejected document. Return status, not data.
    for item in report["files"].values():
        if item.get("error"):
            item["error"] = "Saved data could not be read or did not match its schema."
    return jsonify(ok=all(item["valid"] is not False for item in report["files"].values()),
                   validation=report)


@bp.get("/catalog_env")
@require_management(platform_only=True)
def catalog_env():
    import os
    return jsonify(CATALOG_WEBHOOK_SECRET_present=bool(os.getenv("CATALOG_WEBHOOK_SECRET")))
