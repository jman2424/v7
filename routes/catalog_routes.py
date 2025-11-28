# routes/catalog_routes.py

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import time
from typing import Dict, List

from flask import Blueprint, current_app, jsonify, request, Response

# Match pattern used elsewhere: routes.* exposes `bp`
bp = Blueprint("catalog", __name__)

# Env vars
CATALOG_WEBHOOK_SECRET_ENV = "CATALOG_WEBHOOK_SECRET"
CATALOG_FILE_ENV = "CATALOG_FILE"
CATALOG_WEBHOOK_DISABLE_HMAC_ENV = "CATALOG_WEBHOOK_DISABLE_HMAC"  # optional dev bypass


def _get_catalog_secret() -> str | None:
    secret = os.getenv(CATALOG_WEBHOOK_SECRET_ENV)
    if not secret:
        current_app.logger.warning(
            "Catalog webhook: no %s set in environment",
            CATALOG_WEBHOOK_SECRET_ENV,
        )
    return secret


def _get_catalog_path() -> pathlib.Path:
    # default to Tariq catalog.json if env missing
    path = os.getenv(CATALOG_FILE_ENV, "business/TARIQ/catalog.json")
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_catalog_doc() -> Dict:
    path = _get_catalog_path()
    if not path.exists():
        return {"product_catalog": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        current_app.logger.error(
            "Catalog webhook: failed to read catalog file %s: %s",
            path,
            e,
        )
        return {"product_catalog": []}


def _save_catalog_doc(doc: Dict) -> None:
    path = _get_catalog_path()
    try:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        current_app.logger.error(
            "Catalog webhook: failed to write catalog file %s: %s",
            path,
            e,
        )


def _verify_catalog_signature(raw_body: bytes) -> bool:
    """
    Apps Script does:

        const raw = ts + '.' + body;
        const sigBytes = Utilities.computeHmacSha256Signature(raw, secret, Utilities.Charset.UTF_8);
        header: X-Catalog-Signature = 't=' + ts + ', s=' + hex(sigBytes)

    We must:
      - read X-Catalog-Signature
      - parse t and s
      - recompute HMAC_SHA256(ts + "." + body_utf8, secret)

    In dev, if CATALOG_WEBHOOK_DISABLE_HMAC is a *true-ish* value
    ("1", "true", "yes", "on"), we bypass verification.
    """

    # -------- optional bypass for dev --------
    disable_flag = (os.getenv(CATALOG_WEBHOOK_DISABLE_HMAC_ENV, "") or "").strip().lower()
    if disable_flag in ("1", "true", "yes", "on"):
        current_app.logger.warning(
            "Catalog webhook: HMAC verification DISABLED via %s (value=%r); accepting all POSTs",
            CATALOG_WEBHOOK_DISABLE_HMAC_ENV,
            disable_flag,
        )
        return True

    secret = _get_catalog_secret()
    if not secret:
        return False

    header = request.headers.get("X-Catalog-Signature", "")
    if not header:
        current_app.logger.warning("Catalog webhook: missing X-Catalog-Signature header")
        return False

    try:
        parts = dict(
            p.strip().split("=", 1)
            for p in header.split(",")
            if "=" in p
        )
    except Exception:
        current_app.logger.warning(
            "Catalog webhook: bad X-Catalog-Signature format: %s",
            header,
        )
        return False

    ts = parts.get("t")
    sig_hex = parts.get("s")
    if not ts or not sig_hex:
        current_app.logger.warning(
            "Catalog webhook: missing t or s in signature header: %s",
            header,
        )
        return False

    # Timestamp check (5 min window)
    try:
        ts_int = int(ts)
    except ValueError:
        current_app.logger.warning(
            "Catalog webhook: non-integer timestamp in signature: %s",
            ts,
        )
        return False

    now = int(time.time())
    delta = now - ts_int
    if abs(delta) > 300:
        current_app.logger.warning(
            "Catalog webhook: signature timestamp too old or skewed: ts=%s now=%s delta=%s",
            ts,
            now,
            delta,
        )
        return False

    # Rebuild the exact string Apps Script signed
    body_str = raw_body.decode("utf-8")
    msg = f"{ts}.{body_str}".encode("utf-8")

    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=msg,
        digestmod=hashlib.sha256,
    ).hexdigest()

    body_sha256 = hashlib.sha256(raw_body).hexdigest()

    # Loud debug so you can compare with Apps Script logs
    current_app.logger.warning(
        "Catalog webhook debug: header=%s ts=%s now=%s delta=%s body_sha256=%s expected_hmac=%s got_hmac=%s",
        header,
        ts,
        now,
        delta,
        body_sha256,
        expected,
        sig_hex,
    )

    ok = hmac.compare_digest(expected, sig_hex)
    if not ok:
        current_app.logger.warning("Catalog webhook: signature mismatch (see debug line above)")
    return ok


@bp.route("/catalog_webhook", methods=["GET", "POST"])
def catalog_webhook() -> Response:
    """
    GET  → return current catalog JSON for pullCatalogJsonFlatten()
    POST → verify HMAC + replace product_catalog from Google Sheet rows
    """
    if request.method == "GET":
        doc = _load_catalog_doc()
        return jsonify(doc), 200

    # POST: verify signature
    raw_body = request.get_data(cache=False)  # bytes, untouched
    if not _verify_catalog_signature(raw_body):
        return jsonify({"error": "forbidden"}), 403

    # ---- parse JSON + debug rows ----
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []

    try:
        rows_count = len(rows) if isinstance(rows, list) else "n/a"
        sample = rows[:3] if isinstance(rows, list) else rows
        current_app.logger.warning(
            "Catalog webhook: received rows_count=%s sample=%r",
            rows_count,
            sample,
        )
    except Exception:
        current_app.logger.exception("Catalog webhook: failed to log incoming rows")

    # rows come from Apps Script: {category, subcategory, name, price_str, stock}
    by_cat: Dict[str, List[Dict]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        cat = (r.get("category") or "").strip()
        name = (r.get("name") or "").strip()
        price_str = (r.get("price_str") or "").strip()
        subcat = (r.get("subcategory") or "").strip()
        stock = (r.get("stock") or "").strip()

        # same validity rules as sheetDoctor()
        if not cat or not name or not price_str:
            continue

        by_cat.setdefault(cat, []).append(
            {
                "name": name,
                "subcategory": subcat,
                "price_str": price_str,
                "stock": stock,
            }
        )

    product_catalog = [
        {"name": cname, "items": items}
        for cname, items in by_cat.items()
    ]

    if not product_catalog:
        current_app.logger.warning(
            "Catalog webhook: product_catalog EMPTY after grouping (rows_count=%s)",
            len(rows) if isinstance(rows, list) else "n/a",
        )

    doc = _load_catalog_doc()
    doc["product_catalog"] = product_catalog
    _save_catalog_doc(doc)

    total_items = sum(len(c["items"]) for c in product_catalog)
    current_app.logger.info(
        "Catalog updated via webhook: %d categories, %d items",
        len(product_catalog),
        total_items,
    )

    return jsonify(
        {
            "ok": True,
            "categories": len(product_catalog),
            "items": total_items,
        }
    ), 200


@bp.route("/export_catalog_csv", methods=["GET"])
def export_catalog_csv() -> Response:
    """
    CSV snapshot for pullCatalogCsv().

    Columns:
      category, subcategory, name, price_str, stock
    """
    doc = _load_catalog_doc()
    pc = doc.get("product_catalog") or []

    lines = ["category,subcategory,name,price_str,stock"]
    for cat in pc:
        cname = (cat or {}).get("name") or ""
        for item in (cat or {}).get("items") or []:
            if not item:
                continue
            subcat = (item.get("subcategory") or "").replace(",", " ")
            name = (item.get("name") or "").replace(",", " ")
            price_str = (item.get("price_str") or "").replace(",", " ")
            stock = (item.get("stock") or "").replace(",", " ")
            line = ",".join([cname, subcat, name, price_str, stock])
            lines.append(line)

    csv_body = "\n".join(lines)
    return Response(
        csv_body,
        status=200,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=catalog.csv"},
    )
