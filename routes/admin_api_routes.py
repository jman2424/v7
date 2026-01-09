# routes/admin_api_routes.py
from __future__ import annotations
from flask import Blueprint, jsonify, request, session
from datetime import datetime, timedelta, timezone
import csv, io

from service.analytics_db import _conn

bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")

def _require_login():
    if not session.get("user"):
        return jsonify({"error": "unauthorized"}), 401
    return None

def _tenant() -> str:
    # If you have multi-tenant, store it in session; otherwise env fallback
    user = session.get("user") or {}
    return (user.get("tenant") or "").strip() or "default"

@bp.get("/kpis")
def kpis():
    gate = _require_login()
    if gate: return gate

    minutes = int(request.args.get("minutes", "1440"))
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    tenant = request.args.get("tenant") or _tenant()

    with _conn() as con:
        row = con.execute("""
            SELECT
              SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
              SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
              COUNT(DISTINCT session_id) AS sessions,
              COUNT(DISTINCT lead_id) AS leads
            FROM events
            WHERE tenant=? AND ts_utc >= ?;
        """, (tenant, since.replace(microsecond=0).isoformat())).fetchone()

    return jsonify({
        "tenant": tenant,
        "minutes": minutes,
        "inbound": int(row["inbound"] or 0),
        "outbound": int(row["outbound"] or 0),
        "sessions": int(row["sessions"] or 0),
        "leads": int(row["leads"] or 0),
    })

@bp.get("/timeseries")
def timeseries():
    gate = _require_login()
    if gate: return gate

    minutes = int(request.args.get("minutes", "1440"))
    bucket = int(request.args.get("bucket", "60"))  # bucket size in minutes
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    tenant = request.args.get("tenant") or _tenant()

    # SQLite bucketing using substr for ISO timestamps (simple, robust)
    # For bucket=60, group by hour: YYYY-MM-DDTHH
    # For bucket=15, you'd do more complex logic; keep v1 hourly.
    group_key = "substr(ts_utc, 1, 13)"  # YYYY-MM-DDTHH

    with _conn() as con:
        rows = con.execute(f"""
            SELECT
              {group_key} AS t,
              SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
              SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
              COUNT(DISTINCT session_id) AS sessions
            FROM events
            WHERE tenant=? AND ts_utc >= ?
            GROUP BY t
            ORDER BY t ASC;
        """, (tenant, since.replace(microsecond=0).isoformat())).fetchall()

    return jsonify({
        "tenant": tenant,
        "minutes": minutes,
        "bucket_minutes": bucket,
        "points": [
            {"t": r["t"], "inbound": int(r["inbound"] or 0), "outbound": int(r["outbound"] or 0), "sessions": int(r["sessions"] or 0)}
            for r in rows
        ],
    })

@bp.get("/leads")
def leads():
    gate = _require_login()
    if gate: return gate

    tenant = request.args.get("tenant") or _tenant()
    limit = min(int(request.args.get("limit", "50")), 200)

    with _conn() as con:
        rows = con.execute("""
            SELECT lead_id, name, phone, status, tags, last_session_id, updated_utc
            FROM leads
            WHERE tenant=?
            ORDER BY updated_utc DESC
            LIMIT ?;
        """, (tenant, limit)).fetchall()

    return jsonify({
        "tenant": tenant,
        "items": [dict(r) for r in rows]
    })

@bp.get("/leads.csv")
def leads_csv():
    gate = _require_login()
    if gate: return gate

    tenant = request.args.get("tenant") or _tenant()

    with _conn() as con:
        rows = con.execute("""
            SELECT updated_utc, name, phone, status, tags, last_session_id, lead_id
            FROM leads
            WHERE tenant=?
            ORDER BY updated_utc DESC;
        """, (tenant,)).fetchall()

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["updated_utc","name","phone","status","tags","session_id","lead_id"])
    for r in rows:
        w.writerow([r["updated_utc"], r["name"], r["phone"], r["status"], r["tags"], r["last_session_id"], r["lead_id"]])

    return (out.getvalue(), 200, {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="leads.csv"'
    })
