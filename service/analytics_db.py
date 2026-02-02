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
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _since(minutes: int) -> str:
    m = max(int(minutes or 1440), 1)
    return (datetime.now(timezone.utc) - timedelta(minutes=m)).replace(
        microsecond=0
    ).isoformat()


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
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_columns(con: sqlite3.Connection, table: str, wanted: dict[str, str]) -> None:
    existing = _table_columns(con, table)
    for col, ddl in wanted.items():
        if col not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


# ---------------------------------------------------------------------
# Init / migrations
# ---------------------------------------------------------------------
def init_db() -> None:
    with _conn() as con:
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

        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead_id ON events(lead_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_updated ON leads(tenant, updated_utc)")


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
def upsert_lead(*, tenant: str, lead_id: str, name: str | None = None, phone: str | None = None) -> None:
    _ensure_ready()
    now = _utc_now()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, name, phone, updated_utc)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              name=COALESCE(excluded.name, leads.name),
              phone=COALESCE(excluded.phone, leads.phone),
              updated_utc=excluded.updated_utc;
            """,
            (tenant, lead_id, name, phone, now),
        )


def set_lead_session(*, tenant: str, lead_id: str, session_id: str) -> None:
    _ensure_ready()
    now = _utc_now()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, updated_utc)
            VALUES (?, ?, ?)
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              updated_utc=excluded.updated_utc;
            """,
            (tenant, lead_id, now),
        )

        if "last_session_id" in _table_columns(con, "leads"):
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
    direction: str,
    session_id: str,
    intent: str = "unknown",
    text: str = "",
    lead_id: str | None = None,
    store: str | None = None,
    fallback: bool = False,
    error: bool = False,
    error_code: str = "",
    error_type: str = "",
) -> None:
    _ensure_ready()
    event_type = "msg_in" if direction == "inbound" else "msg_out"

    meta = {
        "store": store,
        "fallback": bool(fallback),
        "error": bool(error),
    }

    with _conn() as con:
        con.execute(
            """
            INSERT INTO events
            (ts_utc, tenant, channel, session_id, event_type, intent, meta_json, text, lead_id, error_code, error_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                _utc_now(),
                tenant,
                channel,
                session_id,
                event_type,
                intent,
                json.dumps(meta),
                text,
                lead_id,
                error_code,
                error_type,
            ),
        )


# backwards compatibility
def log_event(*args, **kwargs):
    return log_message(*args, **kwargs)


# ---------------------------------------------------------------------
# Reads – Admin dashboard
# ---------------------------------------------------------------------
def get_kpis(*, tenant: str, minutes: int = 1440) -> dict[str, int]:
    _ensure_ready()
    since = _since(minutes)
    with _conn() as con:
        r = con.execute(
            """
            SELECT
              SUM(event_type='msg_in')  AS inbound,
              SUM(event_type='msg_out') AS outbound,
              COUNT(DISTINCT session_id) AS sessions,
              SUM(json_extract(meta_json,'$.fallback')=1) AS fallbacks,
              SUM(json_extract(meta_json,'$.error')=1) AS errors
            FROM events
            WHERE tenant=? AND ts_utc>=?;
            """,
            (tenant, since),
        ).fetchone()

        leads = con.execute(
            "SELECT COUNT(*) FROM leads WHERE tenant=? AND updated_utc>=?;",
            (tenant, since),
        ).fetchone()[0]

    return {
        "inbound": int(r["inbound"] or 0),
        "outbound": int(r["outbound"] or 0),
        "total": int((r["inbound"] or 0) + (r["outbound"] or 0)),
        "sessions": int(r["sessions"] or 0),
        "leads": int(leads or 0),
        "fallbacks": int(r["fallbacks"] or 0),
        "errors": int(r["errors"] or 0),
    }


def get_timeseries(*, tenant: str, minutes: int = 1440, bucket_minutes: int = 60):
    _ensure_ready()
    since = _since(minutes)
    with _conn() as con:
        rows = con.execute(
            """
            SELECT substr(ts_utc,1,13) AS t,
                   SUM(event_type='msg_in') AS inbound,
                   SUM(event_type='msg_out') AS outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
            GROUP BY t
            ORDER BY t;
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["t"], "inbound": int(r["inbound"]), "outbound": int(r["outbound"])} for r in rows]


def get_leads(*, tenant: str, limit: int = 50):
    _ensure_ready()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT lead_id, name, phone, status, tags, updated_utc, last_session_id
            FROM leads
            WHERE tenant=?
            ORDER BY updated_utc DESC
            LIMIT ?;
            """,
            (tenant, limit),
        ).fetchall()

    out = []
    for r in rows:
        out.append(
            {
                "lead_id": r["lead_id"],
                "name": r["name"],
                "phone": r["phone"],
                "status": r["status"],
                "tags": json.loads(r["tags"] or "[]"),
                "updated_utc": r["updated_utc"],
                "last_session_id": r["last_session_id"],
            }
        )
    return out


def get_channel_breakdown(*, tenant: str, minutes: int = 1440):
    _ensure_ready()
    since = _since(minutes)
    base = {"web": {"inbound": 0, "outbound": 0, "fallbacks": 0},
            "whatsapp": {"inbound": 0, "outbound": 0, "fallbacks": 0}}

    with _conn() as con:
        rows = con.execute(
            """
            SELECT channel,
                   SUM(event_type='msg_in') AS inbound,
                   SUM(event_type='msg_out') AS outbound,
                   SUM(json_extract(meta_json,'$.fallback')=1) AS fallbacks
            FROM events
            WHERE tenant=? AND ts_utc>=?
            GROUP BY channel;
            """,
            (tenant, since),
        ).fetchall()

    for r in rows:
        base[r["channel"]] = {
            "inbound": int(r["inbound"]),
            "outbound": int(r["outbound"]),
            "fallbacks": int(r["fallbacks"]),
        }

    return base


def get_whatsapp_store_share(*, tenant: str, minutes: int = 1440, limit: int = 12):
    _ensure_ready()
    since = _since(minutes)
    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(json_extract(meta_json,'$.store'),'unknown') AS store,
                   COUNT(*) AS n
            FROM events
            WHERE tenant=? AND channel='whatsapp' AND ts_utc>=?
            GROUP BY store
            ORDER BY n DESC
            LIMIT ?;
            """,
            (tenant, since, limit),
        ).fetchall()

    return [{"store": r["store"], "count": int(r["n"])} for r in rows]


# ---------------------------------------------------------------------
# REQUIRED ALIASES (admin_api_routes imports THESE)
# ---------------------------------------------------------------------
def whatsapp_store_share(*, tenant: str, minutes: int = 1440, limit: int = 12):
    return get_whatsapp_store_share(tenant=tenant, minutes=minutes, limit=limit)


def channel_breakdown(*, tenant: str, minutes: int = 1440):
    return get_channel_breakdown(tenant=tenant, minutes=minutes)
