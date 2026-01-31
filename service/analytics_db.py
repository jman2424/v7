# service/analytics_db.py
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

DB_PATH = os.environ.get("ANALYTICS_DB_PATH", "/app/logs/analytics.db")

_INIT_LOCK = threading.Lock()
_INIT_DONE = False


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _utc_now() -> str:
    # ISO like 2026-01-31T18:42:48+00:00
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _since(minutes: int) -> str:
    m = int(minutes or 1440)
    if m < 1:
        m = 1
    return (datetime.now(timezone.utc) - timedelta(minutes=m)).replace(microsecond=0).isoformat()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA busy_timeout=30000;")
        con.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    return con


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(con: sqlite3.Connection, table: str, wanted: dict[str, str]) -> None:
    """
    wanted: {"col_name": "col_name TYPE ..."}
    """
    existing = _table_columns(con, table)
    for col, ddl in wanted.items():
        if col not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    """
    Safe to call repeatedly.
    Creates tables and performs light migrations if older schema exists.
    IMPORTANT: add columns BEFORE indexes that reference them.
    """
    with _conn() as con:
        # --- Base tables
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                tenant TEXT NOT NULL,
                channel TEXT NOT NULL,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                intent TEXT,
                meta_json TEXT
            );
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant TEXT NOT NULL,
                lead_id TEXT NOT NULL,
                name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'Open',
                tags TEXT DEFAULT '[]',
                updated_utc TEXT NOT NULL,
                UNIQUE(tenant, lead_id)
            );
            """
        )

        # --- Migrations (older DBs may be missing these)
        _ensure_columns(
            con,
            "events",
            {
                "text": "text TEXT",
                "lead_id": "lead_id TEXT",
                "error_code": "error_code TEXT",
                "error_type": "error_type TEXT",
            },
        )
        _ensure_columns(
            con,
            "leads",
            {
                "last_session_id": "last_session_id TEXT",
            },
        )

        # --- Indexes (safe after migrations)
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
        # now safe because we ensured lead_id exists
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead_id ON events(lead_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc)")


def _ensure_ready() -> None:
    global _INIT_DONE
    if _INIT_DONE:
        return
    with _INIT_LOCK:
        if not _INIT_DONE:
            init_db()
            _INIT_DONE = True


# ---------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------
def upsert_lead(*, tenant: str, lead_id: str, name: Optional[str] = None, phone: Optional[str] = None) -> None:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    lead_id = (lead_id or "unknown").strip() or "unknown"
    now = _utc_now()

    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, name, phone, status, tags, updated_utc)
            VALUES (?, ?, ?, ?, COALESCE(NULLIF(?,''),'Open'), COALESCE(NULLIF(?,''),'[]'), ?)
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              name = COALESCE(excluded.name, leads.name),
              phone = COALESCE(excluded.phone, leads.phone),
              updated_utc = excluded.updated_utc;
            """,
            (tenant, lead_id, name, phone, "Open", "[]", now),
        )


def set_lead_session(*, tenant: str, lead_id: str, session_id: str) -> None:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    lead_id = (lead_id or "unknown").strip() or "unknown"
    session_id = (session_id or "unknown").strip() or "unknown"
    now = _utc_now()

    with _conn() as con:
        # Ensure lead exists
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, updated_utc)
            VALUES (?, ?, ?)
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              updated_utc = excluded.updated_utc;
            """,
            (tenant, lead_id, now),
        )

        cols = _table_columns(con, "leads")
        if "last_session_id" in cols:
            con.execute(
                """
                UPDATE leads
                SET last_session_id=?, updated_utc=?
                WHERE tenant=? AND lead_id=?;
                """,
                (session_id, now, tenant, lead_id),
            )


def log_message(
    *,
    tenant: str,
    channel: str,
    direction: str,   # inbound | outbound
    session_id: str,
    intent: str = "unknown",
    text: str = "",
    lead_id: Optional[str] = None,
    store: Optional[str] = None,
    fallback: bool = False,
    error: bool = False,
    error_code: str = "",
    error_type: str = "",
) -> None:
    """
    Main logging entrypoint used by chat routes.
    Stores flags in meta_json so dashboard can query them.
    """
    _ensure_ready()

    tenant = (tenant or "default").strip() or "default"
    ch = (channel or "web").strip().lower() or "web"
    if ch not in ("web", "whatsapp"):
        ch = "web"

    sid = (session_id or "unknown").strip() or "unknown"
    direction = (direction or "inbound").strip().lower()
    event_type = "msg_in" if direction == "inbound" else "msg_out"

    meta = {
        "store": store,
        "fallback": bool(fallback),
        "error": bool(error),
    }

    with _conn() as con:
        cols = _table_columns(con, "events")

        fields = ["ts_utc", "tenant", "channel", "session_id", "event_type", "intent", "meta_json"]
        vals: list[Any] = [_utc_now(), tenant, ch, sid, event_type, intent, json.dumps(meta, ensure_ascii=False)]

        if "text" in cols:
            fields.append("text")
            vals.append(text or "")

        if "lead_id" in cols:
            fields.append("lead_id")
            vals.append((lead_id or "").strip())

        if "error_code" in cols:
            fields.append("error_code")
            vals.append(error_code or "")

        if "error_type" in cols:
            fields.append("error_type")
            vals.append(error_type or "")

        placeholders = ",".join(["?"] * len(fields))
        sql = f"INSERT INTO events ({','.join(fields)}) VALUES ({placeholders})"
        con.execute(sql, tuple(vals))


# ✅ Backwards-compatible: routes import log_event()
def log_event(*args, **kwargs):
    """
    Compatibility wrapper for older routes that still call log_event().
    Internally routes will land in log_message().
    """
    return log_message(*args, **kwargs)


# ---------------------------------------------------------------------
# Reads (Dashboard API)
# ---------------------------------------------------------------------
def get_kpis(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)

    with _conn() as con:
        row = con.execute(
            """
            SELECT
              SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
              SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
              COUNT(DISTINCT CASE WHEN event_type IN ('msg_in','msg_out') THEN session_id END) AS sessions,
              SUM(CASE WHEN json_extract(meta_json,'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks,
              SUM(CASE WHEN json_extract(meta_json,'$.error')    = 1 THEN 1 ELSE 0 END) AS errors
            FROM events
            WHERE tenant=? AND ts_utc>=?;
            """,
            (tenant, since),
        ).fetchone()

        leads = con.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE tenant=? AND updated_utc>=?;",
            (tenant, since),
        ).fetchone()["n"]

    inbound = int(row["inbound"] or 0)
    outbound = int(row["outbound"] or 0)
    sessions = int(row["sessions"] or 0)
    fallbacks = int(row["fallbacks"] or 0)
    errors = int(row["errors"] or 0)

    return {
        "inbound": inbound,
        "outbound": outbound,
        "total": inbound + outbound,
        "sessions": sessions,
        "leads": int(leads or 0),
        "fallbacks": fallbacks,
        "errors": errors,
    }


def get_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT substr(ts_utc,1,13) AS t,
                   SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                   SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY t
            ORDER BY t;
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["t"], "inbound": int(r["inbound"] or 0), "outbound": int(r["outbound"] or 0)} for r in rows]


def get_sessions_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT substr(ts_utc,1,13) AS t,
                   COUNT(DISTINCT session_id) AS sessions
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY t
            ORDER BY t;
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["t"], "sessions": int(r["sessions"] or 0)} for r in rows]


def get_channels_split(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT channel,
                   SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                   SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY channel;
            """,
            (tenant, since),
        ).fetchall()

    out: dict[str, Any] = {}
    for r in rows:
        ch = (r["channel"] or "unknown").strip().lower() or "unknown"
        inbound = int(r["inbound"] or 0)
        outbound = int(r["outbound"] or 0)
        out[ch] = {"inbound": inbound, "outbound": outbound, "total": inbound + outbound}
    return out


def get_top_intents(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(intent,''),'unknown') AS intent,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type='msg_out'
            GROUP BY intent
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]


def get_fallbacks(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(NULLIF(intent,''),'fallback') AS intent,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type='msg_out'
              AND json_extract(meta_json,'$.fallback') = 1
            GROUP BY intent
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["intent"], "count": int(r["n"] or 0)} for r in rows]


def get_errors(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        cols = _table_columns(con, "events")
        code_expr = "COALESCE(NULLIF(error_code,''),'error')" if "error_code" in cols else "'error'"

        rows = con.execute(
            f"""
            SELECT {code_expr} AS code,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND json_extract(meta_json,'$.error') = 1
            GROUP BY code
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"label": r["code"], "count": int(r["n"] or 0)} for r in rows]


def get_common_questions(*, tenant: str, minutes: int = 1440, top: int = 10) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)
    top = max(1, min(_safe_int(top, 10), 50))

    with _conn() as con:
        cols = _table_columns(con, "events")
        if "text" not in cols:
            return []

        rows = con.execute(
            """
            SELECT LOWER(TRIM(COALESCE(text,''))) AS q,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type='msg_in'
              AND TRIM(COALESCE(text,'')) != ''
            GROUP BY q
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, top),
        ).fetchall()

    return [{"question": r["q"], "count": int(r["n"] or 0)} for r in rows]


def get_leads(*, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    limit = max(1, min(_safe_int(limit, 50), 500))

    with _conn() as con:
        cols = _table_columns(con, "leads")
        has_last_session = "last_session_id" in cols

        if has_last_session:
            q = """
            SELECT lead_id, name, phone, status, tags, updated_utc, last_session_id
            FROM leads
            WHERE tenant=?
            ORDER BY updated_utc DESC
            LIMIT ?;
            """
        else:
            q = """
            SELECT lead_id, name, phone, status, tags, updated_utc
            FROM leads
            WHERE tenant=?
            ORDER BY updated_utc DESC
            LIMIT ?;
            """

        rows = con.execute(q, (tenant, limit)).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        raw_tags = r["tags"] or "[]"
        try:
            tags = json.loads(raw_tags)
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []

        item = {
            "lead_id": r["lead_id"],
            "name": r["name"],
            "phone": r["phone"],
            "status": r["status"] or "Open",
            "tags": tags,
            "updated_utc": r["updated_utc"],
        }
        if "last_session_id" in r.keys():
            item["last_session_id"] = r["last_session_id"]
        out.append(item)

    return out


# ---------------------------------------------------------------------
# What admin_api_routes.py imports as "NEW"
# ---------------------------------------------------------------------
def get_channel_breakdown(*, tenant: str, minutes: int = 1440) -> dict[str, dict[str, int]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)

    base: dict[str, dict[str, int]] = {
        "web": {"inbound": 0, "outbound": 0, "fallbacks": 0},
        "whatsapp": {"inbound": 0, "outbound": 0, "fallbacks": 0},
    }

    with _conn() as con:
        rows = con.execute(
            """
            SELECT
              channel,
              SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
              SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
              SUM(CASE WHEN json_extract(meta_json,'$.fallback') = 1 THEN 1 ELSE 0 END) AS fallbacks
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND event_type IN ('msg_in','msg_out')
            GROUP BY channel;
            """,
            (tenant, since),
        ).fetchall()

    for r in rows:
        ch = (r["channel"] or "web").strip().lower() or "web"
        if ch not in base:
            base[ch] = {"inbound": 0, "outbound": 0, "fallbacks": 0}
        base[ch]["inbound"] = int(r["inbound"] or 0)
        base[ch]["outbound"] = int(r["outbound"] or 0)
        base[ch]["fallbacks"] = int(r["fallbacks"] or 0)

    return base


def get_whatsapp_store_share(*, tenant: str, minutes: int = 1440, limit: int = 12) -> list[dict[str, Any]]:
    _ensure_ready()
    tenant = (tenant or "default").strip() or "default"
    since = _since(minutes)
    limit = max(1, min(_safe_int(limit, 12), 50))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT
              COALESCE(NULLIF(json_extract(meta_json,'$.store'),''), 'international') AS store,
              COUNT(*) AS n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND channel='whatsapp'
              AND event_type='msg_in'
            GROUP BY store
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, limit),
        ).fetchall()

    return [{"store": r["store"], "count": int(r["n"] or 0)} for r in rows]
