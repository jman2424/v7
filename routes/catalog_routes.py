"""Signed catalog imports and authenticated, tenant-scoped catalog exports."""
import csv
import hashlib
import hmac
import io
import json
import os
import time

from flask import Blueprint, Response, abort, jsonify, request

from routes import get_container
from service.audit import AuditService
from service.business_management import revision
from service.security import authorized_tenant, require_permission
from service import webhook_inbox

bp = Blueprint("catalog", __name__)


def _verify_catalog_signature(raw):
    secret = os.getenv("CATALOG_WEBHOOK_SECRET", "")
    if not secret:
        return False
    try:
        components = [part.strip().split("=", 1) for part in request.headers.get("X-Catalog-Signature", "").split(",")]
        parts = dict(components)
        if len(components) != 2 or set(parts) != {"t", "s"}:
            return False
        timestamp, supplied = parts["t"], parts["s"]
        if (not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12
                or len(supplied) != 64 or any(char not in "0123456789abcdef" for char in supplied)):
            return False
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (ValueError, KeyError):
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), supplied.encode())


def _read(tenant):
    try:
        return get_container().storage.read_json(tenant, "catalog.json")
    except FileNotFoundError:
        abort(404)


@bp.route("/catalog_webhook", methods=["GET", "POST"])
def catalog_webhook():
    if request.method == "GET":
        require_permission("offerings.read")
        return jsonify(_read(authorized_tenant(request.args.get("tenant"))))
    if not _verify_catalog_signature(request.get_data()):
        abort(403)
    if request.args:
        abort(400)
    payload = request.get_json(silent=True)
    if (not isinstance(payload, dict) or set(payload) != {"rows"}
            or not isinstance(payload["rows"], list) or not 1 <= len(payload["rows"]) <= 10000):
        abort(400, description="Nonempty rows list required")
    categories = {}
    for row in payload["rows"]:
        if not isinstance(row, dict) or set(row) - {"category", "name", "price_str", "subcategory", "stock"}:
            abort(400)
        if any(not isinstance(row.get(key, ""), str) or len(row.get(key, "")) > 200
               for key in ("category", "name", "price_str", "subcategory", "stock")):
            abort(400)
        if not all(row.get(key, "").strip() for key in ("category", "name", "price_str")):
            abort(400)
        categories.setdefault(row["category"].strip(), []).append(
            {key: row.get(key, "").strip() for key in ("name", "price_str", "subcategory", "stock")})
    c = get_container()
    tenant = c.settings.BUSINESS_KEY
    signature_parts = dict(part.strip().split("=", 1) for part in request.headers["X-Catalog-Signature"].split(","))
    delivery = hashlib.sha256(signature_parts["t"].encode() + b"." + request.get_data()).hexdigest()
    state, cached = webhook_inbox.claim(tenant, "catalog", delivery)
    if state == "done":
        return jsonify(json.loads(cached))
    if state == "busy":
        abort(409)
    audit = AuditService()
    common = {"user": "catalog_webhook", "role": "integration", "ip": request.remote_addr or "",
              "action": "catalog.import", "target": f"{tenant}/catalog.json"}
    details = {"tenant": tenant, "source": "catalog_webhook", "delivery": delivery}
    try:
        audit.record(**common, extra={**details, "result": "attempted"})
        with c.storage.write_lock(tenant):
            previous = _read(tenant)
            document = {key: previous[key] for key in ("version", "currency") if key in previous}
            document["product_catalog"] = [{"name": name, "items": items} for name, items in categories.items()]
            c.storage._validate_json(document, c.storage._schema_path("catalog-sheet.schema.json"))
            details.update(before_revision=revision(previous), after_revision=revision(document))
            audit.record(**common, extra={**details, "result": "prepared"})
            snapshot = c.storage._write_json(tenant, "catalog.json", document, schema="catalog-sheet.schema.json")
    except Exception:
        webhook_inbox.finish(tenant, "catalog", delivery, None, failed=True)
        raise
    result = {"ok": True, "categories": len(categories), "items": len(payload["rows"])}
    webhook_inbox.finish(tenant, "catalog", delivery, json.dumps(result))
    c.invalidate_tenant(tenant)
    audit.record(**common, extra={**details, "result": "success", "snapshot": snapshot})
    return jsonify(result)


@bp.get("/export_catalog_csv")
def export_catalog_csv():
    require_permission("offerings.read")
    tenant = authorized_tenant(request.args.get("tenant"))
    document = _read(tenant)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["category", "subcategory", "name", "price", "stock"])
    from routes.analytics_routes import _csv_safe
    for category in document.get("product_catalog", document.get("categories", [])):
        for item in category.get("items", []):
            writer.writerow([_csv_safe(value) for value in (
                category.get("name", ""), item.get("subcategory", ""), item.get("name", ""),
                item.get("price_str", item.get("price", "")), item.get("stock", item.get("in_stock", "")))])
    return Response(stream.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=catalog.csv", "Cache-Control": "no-store"})
def _get_catalog_path():
    c = get_container()
    return c.storage.file_path(c.settings.BUSINESS_KEY, "catalog.json")
