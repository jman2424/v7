# routes/admin_api_routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from datetime import datetime, timedelta, timezone
import csv, io, re
from typing import Any, Dict, List, Optional

from service.analytics_db import _conn

bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")


# -----------------------------
# Helpers
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


def _clamp_int(raw: str, default: int, lo: int, hi: int) -> int:
    try:
        n = int(raw)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s\-\?\!\.\,\'\"]+", "", s)
    return s[:160]


def _parse_iso_to_epoch(ts: str) -> Optional[int]:
    try:
        dt = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _bucket_epoch(epoch: int, bucket_sec: int) -> int:
    return (epoch // bucket_sec) * bucket_sec


def _json_error(where: str, e: Exception, status: int = 500):
    return jsonify({"error": "server_error", "where": where, "detail": str(e)}), status


def _has_column(con, table: str, col: str) -> bool:
    try:
        rows = con.execute(f"PRAGMA table_info({table});").fetchall()
        return any(r["name"] == col for r in rows)
    except Exception:
        return False


# -----------------------------
# Health / schema
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
            ev = {}
            if "events" in tables:
                ev = {
                    "tenant": _has_column(con, "events", "tenant"),
                    "ts_utc": _has_column(con, "events", "ts_utc"),
                    "event_type": _has_column(con, "events", "event_type"),
                    "session_id": _has_column(con, "events", "session_id"),
                    "lead_id": _has_column(con, "events", "lead_id"),
                    "channel": _has_column(con, "events", "channel"),
                    "intent": _has_column(con, "events", "intent"),
                    "text": _has_column(con, "events", "text"),
                    "error_type": _has_column(con, "events", "error_type"),
                    "error_code": _has_column(con, "events", "error_code"),
                    "redirect_to": _has_column(con, "events", "redirect_to"),
                }
        return jsonify({"ok": True, "tenant": tenant, "tables": tables, "events_cols": ev})
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
    since = _since(minutes)

    try:
        with _conn() as con:
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
            """, (tenant, _iso(since))).fetchone()

        inbound = int(row["inbound"] or 0)
        outbound = int(row["outbound"] or 0)
        sessions = int(row["sessions"] or 0)
        leads = int(row["leads"] or 0)
        fallbacks = int(row["fallbacks"] or 0)
        errors = int(row["errors"] or 0)

        total_msgs = inbound + outbound

        return jsonify({
            "tenant": tenant,
            "minutes": minutes,
            "inbound": inbound,
            "outbound": outbound,
            "total_messages": total_msgs,
            "sessions": sessions,
            "leads": leads,
            "fallbacks": fallbacks,
            "errors": errors,
            "fallback_rate": round((fallbacks / inbound) if inbound else 0.0, 4),
            "error_rate": round(errors / max(1, total_msgs), 4),
        })
    except Exception as e:
        return _json_error("kpis", e)


# -----------------------------
# Timeseries (true integer buckets)
# -----------------------------
@bp.get("/timeseries")
def timeseries():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    bucket_min = _clamp_int(request.args.get("bucket", "60"), 60, 1, 24 * 60)
    since = _since(minutes)
    bucket_sec = max(60, bucket_min * 60)

    try:
        with _conn() as con:
            rows = con.execute("""
                SELECT ts_utc, event_type, session_id
                FROM events
                WHERE tenant=? AND ts_utc >= ?
                ORDER BY ts_utc ASC;
            """, (tenant, _iso(since))).fetchall()

        buckets: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            epoch = _parse_iso_to_epoch(r["ts_utc"])
            if epoch is None:
                continue
            b = _bucket_epoch(epoch, bucket_sec)
            if b not in buckets:
                buckets[b] = {"in": 0, "out": 0, "sessions": set()}
            et = r["event_type"] or ""
            if et == "msg_in":
                buckets[b]["in"] += 1
            elif et == "msg_out":
                buckets[b]["out"] += 1
            sid = r["session_id"]
            if sid:
                buckets[b]["sessions"].add(sid)

        points = []
        for b in sorted(buckets.keys()):
            dt = datetime.fromtimestamp(b, tz=timezone.utc)
            points.append({
                "t": dt.replace(microsecond=0).isoformat(),
                "inbound": int(buckets[b]["in"]),
                "outbound": int(buckets[b]["out"]),
                "sessions": int(len(buckets[b]["sessions"])),
            })

        return jsonify({
            "tenant": tenant,
            "minutes": minutes,
            "bucket_minutes": bucket_min,
            "points": points,
        })
    except Exception as e:
        return _json_error("timeseries", e)


# -----------------------------
# Leads
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
            w.writerow([r["updated_utc"], r["name"], r["phone"], r["status"], r["tags"], r["last_session_id"], r["lead_id"]])

        return (out.getvalue(), 200, {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="leads.csv"',
        })
    except Exception as e:
        return _json_error("leads_csv", e)


# -----------------------------
# Insights: top questions, fallbacks, errors, intents, channels, redirects
# -----------------------------
@bp.get("/insights")
def insights():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    topn = _clamp_int(request.args.get("top", "20"), 20, 5, 200)
    since = _since(minutes)

    try:
        with _conn() as con:
            has_text = _has_column(con, "events", "text")
            has_intent = _has_column(con, "events", "intent")
            has_channel = _has_column(con, "events", "channel")
            has_error_type = _has_column(con, "events", "error_type")
            has_error_code = _has_column(con, "events", "error_code")
            has_redirect_to = _has_column(con, "events", "redirect_to")

            # Top questions (msg_in)
            common_questions: List[Dict[str, Any]] = []
            if has_text:
                rows = con.execute("""
                    SELECT COALESCE(text,'') AS text, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND event_type='msg_in' AND ts_utc >= ?
                    GROUP BY COALESCE(text,'')
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, _iso(since), topn)).fetchall()

                merged: Dict[str, int] = {}
                for r in rows:
                    t = _norm_text(r["text"])
                    if not t:
                        continue
                    merged[t] = merged.get(t, 0) + int(r["n"] or 0)
                common_questions = [{"text": k, "count": int(v)} for k, v in sorted(merged.items(), key=lambda x: x[1], reverse=True)][:topn]

            # Fallbacks
            fb = con.execute("""
                SELECT COALESCE(intent,'system_fallback') AS key, COUNT(*) AS n
                FROM events
                WHERE tenant=? AND ts_utc >= ?
                  AND event_type IN ('fallback','pipeline_failure')
                GROUP BY key
                ORDER BY n DESC
                LIMIT ?;
            """, (tenant, _iso(since), topn)).fetchall()
            fallbacks = [{"key": r["key"], "count": int(r["n"] or 0)} for r in fb]

            # Errors
            err_key = "COALESCE(error_code, error_type, intent, 'unknown')" if (has_error_code or has_error_type or has_intent) else "'error'"
            er = con.execute(f"""
                SELECT {err_key} AS key, COUNT(*) AS n
                FROM events
                WHERE tenant=? AND ts_utc >= ?
                  AND event_type IN ('error','pipeline_failure')
                GROUP BY key
                ORDER BY n DESC
                LIMIT ?;
            """, (tenant, _iso(since), topn)).fetchall()
            errors = [{"key": r["key"], "count": int(r["n"] or 0)} for r in er]

            # Intents
            intents = []
            if has_intent:
                ir = con.execute("""
                    SELECT intent AS key, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND COALESCE(intent,'') != ''
                    GROUP BY intent
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, _iso(since), topn)).fetchall()
                intents = [{"key": r["key"], "count": int(r["n"] or 0)} for r in ir]

            # Channels
            channels = []
            if has_channel:
                cr = con.execute("""
                    SELECT channel AS key, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND COALESCE(channel,'') != ''
                    GROUP BY channel
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, _iso(since), topn)).fetchall()
                channels = [{"key": r["key"], "count": int(r["n"] or 0)} for r in cr]

            # Redirects
            redirects = []
            if has_redirect_to:
                rr = con.execute("""
                    SELECT COALESCE(redirect_to,'unknown') AS key, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND event_type='redirect'
                    GROUP BY key
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, _iso(since), topn)).fetchall()
                redirects = [{"key": r["key"], "count": int(r["n"] or 0)} for r in rr]

        return jsonify({
            "tenant": tenant,
            "minutes": minutes,
            "top": topn,
            "common_questions": common_questions,
            "fallbacks": fallbacks,
            "errors": errors,
            "intents": intents,
            "channels": channels,
            "redirects": redirects,
        })
    except Exception as e:
        return _json_error("insights", e)


# -----------------------------
# Backwards-compatible endpoints (so your UI stops 404-ing)
# -----------------------------
@bp.get("/errors")
def errors_alias():
    gate = _require_login()
    if gate:
        return gate
    try:
        minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
        data = insights().get_json()  # type: ignore
        return jsonify({"tenant": data["tenant"], "minutes": minutes, "items": data["errors"]})
    except Exception as e:
        return _json_error("errors_alias", e)


@bp.get("/fallbacks")
def fallbacks_alias():
    gate = _require_login()
    if gate:
        return gate
    try:
        minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
        data = insights().get_json()  # type: ignore
        return jsonify({"tenant": data["tenant"], "minutes": minutes, "items": data["fallbacks"]})
    except Exception as e:
        return _json_error("fallbacks_alias", e)


@bp.get("/top_questions")
def top_questions_alias():
    gate = _require_login()
    if gate:
        return gate
    try:
        minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
        data = insights().get_json()  # type: ignore
        return jsonify({"tenant": data["tenant"], "minutes": minutes, "items": data["common_questions"]})
    except Exception as e:
        return _json_error("top_questions_alias", e)
