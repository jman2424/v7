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
    return (datetime.now(timezone.utc) - timedelta(minutes=int(minutes))).replace(microsecond=0).isoformat()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
    return con


def init_db() -> None:
    with _conn() as con:
        con.execute("""
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
        """)

        con.execute("""
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
        """)

        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel)")


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
def log_message(
    *,
    tenant: str,
    channel: str,
    direction: str,
    session_id: str,
    intent: str = "unknown",
    store: Optional[str] = None,
    fallback: bool = False,
    error: bool = False,
) -> None:
    _ensure_ready()

    event_type = "msg_in" if direction == "inbound" else "msg_out"

    meta = {
        "store": store,
        "fallback": fallback,
        "error": error,
    }

    with _conn() as con:
        con.execute(
            """
            INSERT INTO events (ts_utc, tenant, channel, session_id, event_type, intent, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                tenant,
                channel.lower(),
                session_id,
                event_type,
                intent,
                json.dumps(meta),
            ),
        )


# ---------------------------------------------------------------------
# Reads (Dashboard)
# ---------------------------------------------------------------------
def get_kpis(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    _ensure_ready()
    since = _since(minutes)

    with _conn() as con:
        inbound = con.execute(
            "SELECT COUNT(*) n FROM events WHERE tenant=? AND ts_utc>=? AND event_type='msg_in'",
            (tenant, since),
        ).fetchone()["n"]

        outbound = con.execute(
            "SELECT COUNT(*) n FROM events WHERE tenant=? AND ts_utc>=? AND event_type='msg_out'",
            (tenant, since),
        ).fetchone()["n"]

        sessions = con.execute(
            """
            SELECT COUNT(DISTINCT session_id) n
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type IN ('msg_in','msg_out')
            """,
            (tenant, since),
        ).fetchone()["n"]

    return {
        "inbound": inbound,
        "outbound": outbound,
        "total": inbound + outbound,
        "sessions": sessions,
    }


def get_timeseries(*, tenant: str, minutes: int = 1440, bucket: int = 60) -> list[dict[str, Any]]:
    _ensure_ready()
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT substr(ts_utc,1,13) t,
                   SUM(event_type='msg_in') inbound,
                   SUM(event_type='msg_out') outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
            GROUP BY t
            ORDER BY t
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["t"], "inbound": r["inbound"], "outbound": r["outbound"]} for r in rows]


def get_sessions_timeseries(*, tenant: str, minutes: int = 1440) -> list[dict[str, Any]]:
    _ensure_ready()
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT substr(ts_utc,1,13) t,
                   COUNT(DISTINCT session_id) sessions
            FROM events
            WHERE tenant=? AND ts_utc>=? AND event_type IN ('msg_in','msg_out')
            GROUP BY t
            ORDER BY t
            """,
            (tenant, since),
        ).fetchall()

    return [{"t": r["t"], "sessions": r["sessions"]} for r in rows]


def get_channels_split(*, tenant: str, minutes: int = 1440) -> dict[str, Any]:
    _ensure_ready()
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT channel,
                   SUM(event_type='msg_in') inbound,
                   SUM(event_type='msg_out') outbound
            FROM events
            WHERE tenant=? AND ts_utc>=?
            GROUP BY channel
            """,
            (tenant, since),
        ).fetchall()

    out: dict[str, Any] = {}
    for r in rows:
        out[r["channel"]] = {
            "inbound": r["inbound"],
            "outbound": r["outbound"],
            "total": r["inbound"] + r["outbound"],
        }
    return out


def whatsapp_store_share(*, tenant: str, minutes: int = 1440) -> list[dict[str, Any]]:
    _ensure_ready()
    since = _since(minutes)

    with _conn() as con:
        rows = con.execute(
            """
            SELECT
              COALESCE(json_extract(meta_json,'$.store'),'international') store,
              COUNT(*) n
            FROM events
            WHERE tenant=? AND ts_utc>=?
              AND channel='whatsapp'
              AND event_type='msg_in'
            GROUP BY store
            ORDER BY n DESC
            """,
            (tenant, since),
        ).fetchall()

    return [{"store": r["store"], "count": r["n"]} for r in rows]
