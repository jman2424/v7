# routes/admin_api_routes.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import csv, io, re

from flask import Blueprint, jsonify, request, session

from service.analytics_db import _conn, init_db

bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


# -----------------------------
# Boot safety: ensure DB + migrations
# -----------------------------
@bp.before_app_request
def _ensure_db():
    # Cheap and safe: init_db is idempotent and WAL makes it OK.
    try:
        init_db()
    except Exception:
        pass


# -----------------------------
# Auth / tenant helpers
# -----------------------------
def _require_login():
    if not session.get("user"):
        return jsonify({"error": "unauthorized"}), 401
    return None


def _tenant() -> str:
    t = (request.args.get("tenant") or "").strip()
    if t:
        return t
    user = session.get("user") or {}
    return (user.get("tenant") or "").strip() or "default"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _since(minutes: int) -> datetime:
    return _now_utc() - timedelta(minutes=minutes)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _clamp_int(val: str, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _json_error(where: str, e: Exception, status: int = 500):
    return jsonify({"error": "server_error", "where": where, "detail": str(e)}), status


def _table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (table,),
    ).fetchone()
    return bool(row)


def _table_cols(con, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    return {r["name"] for r in rows}


def _has(con, col: str) -> bool:
    return col in _table_cols(con, "events")


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s\-\?\!\.\,\'\"]+", "", s)
    return s[:160]


def _parse_iso_to_epoch(ts: str) -> Optional[int]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _bucket_start_epoch(ts_epoch: int, bucket_sec: int) -> int:
    return (ts_epoch // bucket_sec) * bucket_sec


# -----------------------------
# Health / schema visibility
# -----------------------------
@bp.get("/health")
def health():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    try:
        with _conn() as con:
            tables = [r["name"] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            ).fetchall()]

            out: Dict[str, Any] = {"ok": True, "tenant": tenant, "tables": tables}

            if "events" in tables:
                cols = _table_cols(con, "events")
                out["events_columns"] = sorted(list(cols))
            if "leads" in tables:
                cols = _table_cols(con, "leads")
                out["leads_columns"] = sorted(list(cols))

        return jsonify(out)
    except Exception as e:
        return _json_error("health", e)


# -----------------------------
# KPIs
# -----------------------------
@bp.get("/kpis")
def kpis():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    since = _iso(_since(minutes))

    try:
        with _conn() as con:
            if not _table_exists(con, "events"):
                return jsonify({
                    "tenant": tenant, "minutes": minutes,
                    "inbound": 0, "outbound": 0, "total_messages": 0,
                    "sessions": 0, "leads": 0, "fallbacks": 0, "errors": 0,
                    "fallback_rate": 0.0, "error_rate": 0.0,
                })

            row = con.execute("""
                SELECT
                  SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                  SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
                  COUNT(DISTINCT session_id) AS sessions,
                  COUNT(DISTINCT lead_id) AS leads,
                  SUM(CASE WHEN event_type IN ('fallback','pipeline_failure') THEN 1 ELSE 0 END) AS fallbacks,
                  SUM(CASE WHEN event_type='error' THEN 1 ELSE 0 END) AS errors
                FROM events
                WHERE tenant=? AND ts_utc >= ?;
            """, (tenant, since)).fetchone()

        inbound = int(row["inbound"] or 0)
        outbound = int(row["outbound"] or 0)
        sessions = int(row["sessions"] or 0)
        leads = int(row["leads"] or 0)
        fallbacks = int(row["fallbacks"] or 0)
        errors = int(row["errors"] or 0)

        total = inbound + outbound
        fallback_rate = (fallbacks / inbound) if inbound else 0.0
        error_rate = (errors / max(1, total))

        return jsonify({
            "tenant": tenant,
            "minutes": minutes,
            "inbound": inbound,
            "outbound": outbound,
            "total_messages": total,
            "sessions": sessions,
            "leads": leads,
            "fallbacks": fallbacks,
            "errors": errors,
            "fallback_rate": round(fallback_rate, 4),
            "error_rate": round(error_rate, 4),
        })
    except Exception as e:
        return _json_error("kpis", e)


# -----------------------------
# Timeseries (bucket in python)
# -----------------------------
@bp.get("/timeseries")
def timeseries():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    bucket = _clamp_int(request.args.get("bucket", "60"), 60, 1, 24 * 60)
    since = _iso(_since(minutes))
    bucket_sec = max(60, bucket * 60)

    try:
        with _conn() as con:
            if not _table_exists(con, "events"):
                return jsonify({"tenant": tenant, "minutes": minutes, "bucket_minutes": bucket, "points": []})

            rows = con.execute("""
                SELECT ts_utc, event_type, session_id
                FROM events
                WHERE tenant=? AND ts_utc >= ?
                ORDER BY ts_utc ASC;
            """, (tenant, since)).fetchall()

        buckets: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            ts_epoch = _parse_iso_to_epoch(r["ts_utc"])
            if ts_epoch is None:
                continue
            b = _bucket_start_epoch(ts_epoch, bucket_sec)
            if b not in buckets:
                buckets[b] = {"inbound": 0, "outbound": 0, "sessions": set()}
            if r["event_type"] == "msg_in":
                buckets[b]["inbound"] += 1
            elif r["event_type"] == "msg_out":
                buckets[b]["outbound"] += 1
            if r["session_id"]:
                buckets[b]["sessions"].add(r["session_id"])

        points = []
        for b in sorted(buckets.keys()):
            dt = datetime.fromtimestamp(b, tz=timezone.utc).replace(microsecond=0).isoformat()
            points.append({
                "t": dt,
                "inbound": int(buckets[b]["inbound"]),
                "outbound": int(buckets[b]["outbound"]),
                "sessions": int(len(buckets[b]["sessions"])),
            })

        return jsonify({
            "tenant": tenant,
            "minutes": minutes,
            "bucket_minutes": bucket,
            "points": points,
        })
    except Exception as e:
        return _json_error("timeseries", e)


# -----------------------------
# Leads + CSV
# -----------------------------
@bp.get("/leads")
def leads():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    limit = _clamp_int(request.args.get("limit", "50"), 50, 1, 500)

    try:
        with _conn() as con:
            if not _table_exists(con, "leads"):
                return jsonify({"tenant": tenant, "items": []})

            rows = con.execute("""
                SELECT lead_id, name, phone, status, tags, last_session_id, updated_utc
                FROM leads
                WHERE tenant=?
                ORDER BY updated_utc DESC
                LIMIT ?;
            """, (tenant, limit)).fetchall()

        return jsonify({"tenant": tenant, "items": [dict(r) for r in rows]})
    except Exception as e:
        return _json_error("leads", e)


@bp.get("/leads.csv")
def leads_csv():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()

    try:
        with _conn() as con:
            rows = []
            if _table_exists(con, "leads"):
                rows = con.execute("""
                    SELECT updated_utc, name, phone, status, tags, last_session_id, lead_id
                    FROM leads
                    WHERE tenant=?
                    ORDER BY updated_utc DESC;
                """, (tenant,)).fetchall()

        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["updated_utc", "name", "phone", "status", "tags", "session_id", "lead_id"])
        for r in rows:
            w.writerow([
                r["updated_utc"], r["name"], r["phone"], r["status"], r["tags"],
                r["last_session_id"], r["lead_id"]
            ])

        return (out.getvalue(), 200, {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="leads.csv"',
        })
    except Exception as e:
        return _json_error("leads_csv", e)


# -----------------------------
# Insights (NEVER 500 on missing columns)
# -----------------------------
@bp.get("/insights")
def insights():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    topn = _clamp_int(request.args.get("top", "20"), 20, 5, 200)
    since = _iso(_since(minutes))

    try:
        with _conn() as con:
            if not _table_exists(con, "events"):
                return jsonify({
                    "tenant": tenant, "minutes": minutes, "top": topn,
                    "common_questions": [], "channels": [], "intents": [],
                    "fallbacks": [], "errors": [], "redirects": [],
                })

            cols = _table_cols(con, "events")
            has_text = "text" in cols
            has_intent = "intent" in cols
            has_channel = "channel" in cols
            has_error_type = "error_type" in cols
            has_error_code = "error_code" in cols
            has_redirect_to = "redirect_to" in cols

            # --- Common questions
            common_questions: List[Dict[str, Any]] = []
            if has_text:
                rows = con.execute("""
                    SELECT COALESCE(text,'') AS t, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND event_type='msg_in' AND ts_utc >= ?
                    GROUP BY COALESCE(text,'')
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, since, topn * 3)).fetchall()

                merged: Dict[str, int] = {}
                for r in rows:
                    t = _norm_text(r["t"])
                    if not t:
                        continue
                    merged[t] = merged.get(t, 0) + int(r["n"] or 0)

                common_questions = [
                    {"text": k, "count": v}
                    for k, v in sorted(merged.items(), key=lambda x: x[1], reverse=True)[:topn]
                ]

            # --- Channels
            channels: List[Dict[str, Any]] = []
            if has_channel:
                rows = con.execute("""
                    SELECT COALESCE(channel,'unknown') AS k, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                    GROUP BY k
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, since, topn)).fetchall()
                channels = [{"key": r["k"], "count": int(r["n"] or 0)} for r in rows]

            # --- Intents
            intents: List[Dict[str, Any]] = []
            if has_intent:
                rows = con.execute("""
                    SELECT COALESCE(intent,'unknown') AS k, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ? AND COALESCE(intent,'') != ''
                    GROUP BY k
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, since, topn)).fetchall()
                intents = [{"key": r["k"], "count": int(r["n"] or 0)} for r in rows]

            # --- Fallbacks
            if has_intent:
                rows = con.execute("""
                    SELECT COALESCE(intent,'system_fallback') AS k, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND (event_type IN ('fallback','pipeline_failure') OR COALESCE(intent,'')='system_fallback')
                    GROUP BY k
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, since, topn)).fetchall()
            else:
                rows = con.execute("""
                    SELECT 'system_fallback' AS k, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND event_type IN ('fallback','pipeline_failure')
                    GROUP BY k
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, since, topn)).fetchall()

            fallbacks = [{"key": r["k"], "count": int(r["n"] or 0)} for r in rows]

            # --- Errors
            if has_error_code or has_error_type or has_intent:
                parts = []
                if has_error_code: parts.append("error_code")
                if has_error_type: parts.append("error_type")
                if has_intent: parts.append("intent")
                key_expr = "COALESCE(" + ", ".join(parts) + ", 'unknown')"

                rows = con.execute(f"""
                    SELECT {key_expr} AS k, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND event_type IN ('error','pipeline_failure')
                    GROUP BY k
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, since, topn)).fetchall()
            else:
                rows = con.execute("""
                    SELECT 'error' AS k, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND event_type IN ('error','pipeline_failure')
                    GROUP BY k
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, since, topn)).fetchall()

            errors = [{"key": r["k"], "count": int(r["n"] or 0)} for r in rows]

            # --- Redirects
            redirects: List[Dict[str, Any]] = []
            if has_redirect_to:
                rows = con.execute("""
                    SELECT COALESCE(redirect_to,'unknown') AS k, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ? AND event_type='redirect'
                    GROUP BY k
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, since, topn)).fetchall()
                redirects = [{"key": r["k"], "count": int(r["n"] or 0)} for r in rows]

        return jsonify({
            "tenant": tenant,
            "minutes": minutes,
            "top": topn,
            "common_questions": common_questions,
            "channels": channels,
            "intents": intents,
            "fallbacks": fallbacks,
            "errors": errors,
            "redirects": redirects,
        })
    except Exception as e:
        return _json_error("insights", e)


# -----------------------------
# Compatibility endpoints (older JS)
# -----------------------------
@bp.get("/top_questions")
def top_questions():
    gate = _require_login()
    if gate:
        return gate
    try:
        payload = insights().get_json()  # type: ignore[union-attr]
        return jsonify({"items": payload.get("common_questions", [])})
    except Exception as e:
        return _json_error("top_questions", e)


@bp.get("/fallbacks")
def fallbacks_proxy():
    gate = _require_login()
    if gate:
        return gate
    try:
        payload = insights().get_json()  # type: ignore[union-attr]
        return jsonify({"items": payload.get("fallbacks", [])})
    except Exception as e:
        return _json_error("fallbacks", e)


@bp.get("/errors")
def errors_proxy():
    gate = _require_login()
    if gate:
        return gate
    try:
        payload = insights().get_json()  # type: ignore[union-attr]
        return jsonify({"items": payload.get("errors", [])})
    except Exception as e:
        return _json_error("errors", e)
