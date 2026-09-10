"""Signed catalog imports and authenticated, tenant-scoped catalog exports."""
import csv
import hashlib
import hmac
import io
import os
import time

from flask import Blueprint, Response, abort, jsonify, request

from routes import get_container
from service.audit import AuditService
from service.security import authorized_tenant, management_user

bp = Blueprint("catalog", __name__)


def _verify_catalog_signature(raw):
    secret = os.getenv("CATALOG_WEBHOOK_SECRET", "")
    if not secret:
        return False
    try:
        parts = dict(part.strip().split("=", 1) for part in request.headers.get("X-Catalog-Signature", "").split(","))
        timestamp, supplied = parts["t"], parts["s"]
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
        return jsonify(_read(authorized_tenant(request.args.get("tenant"))))
    if not _verify_catalog_signature(request.get_data()):
        abort(403)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list) or not payload["rows"]:
        abort(400, description="Nonempty rows list required")
    categories = {}
    for row in payload["rows"]:
        if not isinstance(row, dict):
            abort(400)
        if any(not isinstance(row.get(key, ""), str) for key in ("category", "name", "price_str", "subcategory", "stock")):
            abort(400)
        if not all(row.get(key, "").strip() for key in ("category", "name", "price_str")):
            abort(400)
        categories.setdefault(row["category"].strip(), []).append(
            {key: row.get(key, "").strip() for key in ("name", "price_str", "subcategory", "stock")})
    c = get_container()
    tenant = c.settings.BUSINESS_KEY
    document = _read(tenant)
    document["product_catalog"] = [{"name": name, "items": items} for name, items in categories.items()]
    snapshot = c.storage.write_json(tenant, "catalog.json", document, schema="catalog-sheet.schema.json")
    AuditService().record(user="catalog_webhook", role="integration", ip=request.remote_addr or "",
                          action="catalog.import", target=f"{tenant}/catalog.json", extra={"snapshot": snapshot})
    return jsonify(ok=True, categories=len(categories), items=len(payload["rows"]))


@bp.get("/export_catalog_csv")
def export_catalog_csv():
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
