# routes/admin_api_routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from datetime import datetime, timedelta, timezone
import csv, io, re
from typing import Any, Dict, List, Optional, Tuple

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
    """
    Priority:
      1) explicit query param ?tenant=...
      2) session user.tenant
      3) "default"
    """
    t = (request.args.get("tenant") or "").strip()
    if t:
        return t

    user = session.get("user") or {}
    t2 = (user.get("tenant") or "").strip()
    return t2 or "default"


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


def _table_cols(con, table: str) -> List[str]:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    # row fields: cid, name, type, notnull, dflt_value, pk
    return [r["name"] for r in rows]


def _has_cols(con, table: str, cols: List[str]) -> Dict[str, bool]:
    existing = set(_table_cols(con, table))
    return {c: (c in existing) for c in cols}


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s\-\?\!\.\,\'\"]+", "", s)  # keep it readable
    return s[:160]


def _bucket_seconds(bucket_minutes: int) -> int:
    return max(60, int(bucket_minutes) * 60)


def _bucket_start_epoch(ts_epoch: int, bucket_sec: int) -> int:
    return (ts_epoch // bucket_sec) * bucket_sec


def _parse_iso_to_epoch(ts: str) -> Optional[int]:
    """
    We store ts_utc as ISO in SQLite. Parse safely.
    """
    try:
        # supports "2026-01-16T02:47:16+00:00" and "2026-01-16T02:47:16"
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


# -----------------------------
# 1) Health / Schema diagnostics
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

            events_cols = {}
            leads_cols = {}
            if "events" in tables:
                events_cols = _has_cols(con, "events", [
                    "tenant", "ts_utc", "event_type", "session_id", "lead_id",
                    "channel", "intent", "text", "meta_json",
                    "error_type", "error_code", "redirect_to"
                ])
            if "leads" in tables:
                leads_cols = _has_cols(con, "leads", [
                    "tenant", "lead_id", "name", "phone", "status", "tags",
                    "last_session_id", "updated_utc"
                ])

            # Count recent events for tenant
            since = _since(1440)
            ev_count = 0
            if "events" in tables and events_cols.get("tenant") and events_cols.get("ts_utc"):
                row = con.execute(
                    "SELECT COUNT(*) AS n FROM events WHERE tenant=? AND ts_utc >= ?;",
                    (tenant, _iso(since)),
                ).fetchone()
                ev_count = int(row["n"] or 0)

        return jsonify({
            "ok": True,
            "tenant": tenant,
            "tables": tables,
            "events_columns": events_cols,
            "leads_columns": leads_cols,
            "events_last_24h": ev_count,
        })
    except Exception as e:
        return _json_error("health", e)


# -----------------------------
# 2) KPIs (improved)
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
            # We guard for missing columns by relying on event_type/session_id/lead_id.
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

        # Derived rates (safe)
        total_msgs = inbound + outbound
        fallback_rate = (fallbacks / inbound) if inbound else 0.0
        error_rate = (errors / max(1, total_msgs))

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
            "fallback_rate": round(fallback_rate, 4),
            "error_rate": round(error_rate, 4),
        })
    except Exception as e:
        return _json_error("kpis", e)


# -----------------------------
# 3) Timeseries (real bucketing; integer counts)
# -----------------------------
@bp.get("/timeseries")
def timeseries():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    bucket = _clamp_int(request.args.get("bucket", "60"), 60, 1, 24 * 60)  # minutes
    since = _since(minutes)

    try:
        # Pull events in range, then bucket in Python to avoid SQLite time math pain
        with _conn() as con:
            rows = con.execute("""
                SELECT ts_utc, event_type, session_id
                FROM events
                WHERE tenant=? AND ts_utc >= ?
                ORDER BY ts_utc ASC;
            """, (tenant, _iso(since))).fetchall()

        bucket_sec = _bucket_seconds(bucket)

        buckets: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            ts_epoch = _parse_iso_to_epoch(r["ts_utc"])
            if ts_epoch is None:
                continue
            b = _bucket_start_epoch(ts_epoch, bucket_sec)
            if b not in buckets:
                buckets[b] = {"inbound": 0, "outbound": 0, "sessions_set": set()}
            et = (r["event_type"] or "")
            if et == "msg_in":
                buckets[b]["inbound"] += 1
            elif et == "msg_out":
                buckets[b]["outbound"] += 1
            sid = r["session_id"]
            if sid:
                buckets[b]["sessions_set"].add(sid)

        points = []
        for b in sorted(buckets.keys()):
            dt = datetime.fromtimestamp(b, tz=timezone.utc)
            points.append({
                "t": dt.replace(microsecond=0).isoformat(),
                "inbound": int(buckets[b]["inbound"]),
                "outbound": int(buckets[b]["outbound"]),
                "sessions": int(len(buckets[b]["sessions_set"])),
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
# 4) Leads + CSV
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
            w.writerow([
                r["updated_utc"], r["name"], r["phone"], r["status"],
                r["tags"], r["last_session_id"], r["lead_id"]
            ])

        return (out.getvalue(), 200, {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="leads.csv"',
        })
    except Exception as e:
        return _json_error("leads_csv", e)


# -----------------------------
# 5) Insights (common questions, fallbacks, errors, intents, channels)
# -----------------------------
@bp.get("/insights")
def insights():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    since = _since(minutes)
    topn = _clamp_int(request.args.get("top", "20"), 20, 5, 100)

    try:
        with _conn() as con:
            cols = _has_cols(con, "events", ["text", "intent", "channel", "error_type", "error_code", "redirect_to"])
            # Common inbound questions (requires text)
            common_questions: List[Dict[str, Any]] = []
            if cols.get("text"):
                q = con.execute(f"""
                    SELECT COALESCE(text,'') AS text, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND event_type='msg_in' AND ts_utc >= ?
                    GROUP BY COALESCE(text,'')
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, _iso(since), topn)).fetchall()

                merged: Dict[str, int] = {}
                for r in q:
                    t = _norm_text(r["text"])
                    if not t:
                        continue
                    merged[t] = merged.get(t, 0) + int(r["n"] or 0)
                common_questions = [{"text": k, "count": v} for k, v in sorted(merged.items(), key=lambda x: x[1], reverse=True)]

            # Fallbacks (event_type based; plus optional intent)
            fb = con.execute(f"""
                SELECT COALESCE(intent,'system_fallback') AS intent, COUNT(*) AS n
                FROM events
                WHERE tenant=? AND ts_utc >= ?
                  AND (event_type IN ('fallback','pipeline_failure') OR COALESCE(intent,'')='system_fallback')
                GROUP BY COALESCE(intent,'system_fallback')
                ORDER BY n DESC
                LIMIT ?;
            """, (tenant, _iso(since), topn)).fetchall()
            fallback_hits = [{"intent": r["intent"], "count": int(r["n"] or 0)} for r in fb]

            # Errors
            err_key = "COALESCE(error_code, error_type, intent, 'unknown')" if (cols.get("error_code") or cols.get("error_type") or cols.get("intent")) else "'error'"
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

            # Top intents (if intent column exists)
            intents = []
            if cols.get("intent"):
                ir = con.execute(f"""
                    SELECT intent, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND COALESCE(intent,'') != ''
                    GROUP BY intent
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, _iso(since), topn)).fetchall()
                intents = [{"intent": r["intent"], "count": int(r["n"] or 0)} for r in ir]

            # Top channels (if channel exists)
            channels = []
            if cols.get("channel"):
                cr = con.execute(f"""
                    SELECT channel, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND COALESCE(channel,'') != ''
                    GROUP BY channel
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, _iso(since), topn)).fetchall()
                channels = [{"channel": r["channel"], "count": int(r["n"] or 0)} for r in cr]

            # Redirects (only if you log event_type='redirect' OR redirect_to exists)
            redirects = []
            if cols.get("redirect_to") or cols.get("intent"):
                rr = con.execute(f"""
                    SELECT COALESCE(redirect_to, intent, 'unknown') AS to_key, COUNT(*) AS n
                    FROM events
                    WHERE tenant=? AND ts_utc >= ?
                      AND event_type='redirect'
                    GROUP BY to_key
                    ORDER BY n DESC
                    LIMIT ?;
                """, (tenant, _iso(since), topn)).fetchall()
                redirects = [{"to": r["to_key"], "count": int(r["n"] or 0)} for r in rr]

        return jsonify({
            "tenant": tenant,
            "minutes": minutes,
            "top": topn,
            "common_questions": common_questions,
            "fallback_hits": fallback_hits,
            "errors": errors,
            "intents": intents,
            "channels": channels,
            "redirects": redirects,
        })
    except Exception as e:
        return _json_error("insights", e)


# -----------------------------
# 6) Session drilldown (timeline)
# -----------------------------
@bp.get("/session")
def session_timeline():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    session_id = (request.args.get("session_id") or "").strip()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    since = _since(minutes)
    limit = _clamp_int(request.args.get("limit", "80"), 80, 1, 500)

    if not session_id:
        return jsonify({"error": "missing_session_id"}), 400

    try:
        with _conn() as con:
            cols = _has_cols(con, "events", ["text", "intent", "channel", "meta_json"])
            select_text = "COALESCE(text,'') AS text," if cols.get("text") else "'' AS text,"
            select_intent = "COALESCE(intent,'') AS intent," if cols.get("intent") else "'' AS intent,"
            select_channel = "COALESCE(channel,'') AS channel," if cols.get("channel") else "'' AS channel,"
            select_meta = "COALESCE(meta_json,'') AS meta_json" if cols.get("meta_json") else "'' AS meta_json"

            rows = con.execute(f"""
                SELECT ts_utc, event_type, {select_text} {select_intent} {select_channel} {select_meta}
                FROM events
                WHERE tenant=? AND session_id=? AND ts_utc >= ?
                ORDER BY ts_utc DESC
                LIMIT ?;
            """, (tenant, session_id, _iso(since), limit)).fetchall()

        items = []
        for r in rows[::-1]:
            items.append({
                "ts_utc": r["ts_utc"],
                "event_type": r["event_type"],
                "text": r["text"],
                "intent": r["intent"],
                "channel": r["channel"],
                "meta_json": r["meta_json"],
            })

        return jsonify({
            "tenant": tenant,
            "session_id": session_id,
            "minutes": minutes,
            "limit": limit,
            "items": items,
        })
    except Exception as e:
        return _json_error("session", e)


# -----------------------------
# 7) Quick “top sessions” list
# -----------------------------
@bp.get("/sessions")
def sessions_top():
    gate = _require_login()
    if gate:
        return gate

    tenant = _tenant()
    minutes = _clamp_int(request.args.get("minutes", "1440"), 1440, 1, 60 * 24 * 30)
    since = _since(minutes)
    limit = _clamp_int(request.args.get("limit", "25"), 25, 1, 200)

    try:
        with _conn() as con:
            rows = con.execute("""
                SELECT session_id,
                       COUNT(*) AS events,
                       SUM(CASE WHEN event_type='msg_in' THEN 1 ELSE 0 END) AS inbound,
                       SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
                       MAX(ts_utc) AS last_ts
                FROM events
                WHERE tenant=? AND ts_utc >= ?
                GROUP BY session_id
                ORDER BY events DESC
                LIMIT ?;
            """, (tenant, _iso(since), limit)).fetchall()

        return jsonify({
            "tenant": tenant,
            "minutes": minutes,
            "items": [
                {
                    "session_id": r["session_id"],
                    "events": int(r["events"] or 0),
                    "inbound": int(r["inbound"] or 0),
                    "outbound": int(r["outbound"] or 0),
                    "last_ts": r["last_ts"],
                }
                for r in rows
            ]
        })
    except Exception as e:
        return _json_error("sessions", e)
