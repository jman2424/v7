# service/analytics_db.py
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/app/logs/analytics.db")


# -------------------------
# Core DB helpers
# -------------------------
def _ensure_parent_dir(path: str) -> None:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)


def _conn() -> sqlite3.Connection:
    _ensure_parent_dir(DB_PATH)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (table,),
    ).fetchone()
    return bool(row)


def _table_cols(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(con: sqlite3.Connection, table: str, cols: Dict[str, str]) -> None:
    existing = _table_cols(con, table)
    for name, coltype in cols.items():
        if name in existing:
            continue
        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype};")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db() -> None:
    """
    Idempotent schema init + migrations.
    Call on startup and it's also safe to call inside log_event().
    """
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                tenant TEXT NOT NULL,
                channel TEXT NOT NULL,
                session_id TEXT NOT NULL,
                lead_id TEXT,
                event_type TEXT NOT NULL,
                meta_json TEXT
            );
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                lead_id TEXT PRIMARY KEY,
                tenant TEXT NOT NULL,
                name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'Open',
                tags TEXT DEFAULT '',
                last_session_id TEXT,
                updated_utc TEXT NOT NULL
            );
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);")

        # ✅ MIGRATIONS (what your dashboard relies on)
        _ensure_columns(
            con,
            "events",
            {
                "text": "TEXT",
                "intent": "TEXT",
                "error_type": "TEXT",
                "error_code": "TEXT",
                "redirect_to": "TEXT",
            },
        )


# -------------------------
# Leads
# -------------------------
def upsert_lead(
    *,
    tenant: str,
    lead_id: str,
    phone: str | None = None,
    name: str | None = None,
) -> None:
    init_db()
    now = utc_now_iso()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (lead_id, tenant, phone, name, updated_utc)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lead_id) DO UPDATE SET
                phone=COALESCE(excluded.phone, leads.phone),
                name=COALESCE(excluded.name, leads.name),
                updated_utc=excluded.updated_utc;
            """,
            (lead_id, tenant, phone, name, now),
        )


def set_lead_session(*, lead_id: str, session_id: str) -> None:
    init_db()
    now = utc_now_iso()
    with _conn() as con:
        con.execute(
            """
            UPDATE leads
            SET last_session_id=?, updated_utc=?
            WHERE lead_id=?;
            """,
            (session_id, now, lead_id),
        )


# -------------------------
# Events
# -------------------------
def _dump_meta(meta: Any | None) -> str | None:
    if meta is None:
        return None
    if isinstance(meta, str):
        return meta
    try:
        return json.dumps(meta, ensure_ascii=False)
    except Exception:
        return str(meta)


def log_event(
    *,
    tenant: str,
    channel: str,
    session_id: str,
    event_type: str,
    lead_id: str | None = None,
    text: str | None = None,
    intent: str | None = None,
    error_type: str | None = None,
    error_code: str | None = None,
    redirect_to: str | None = None,
    meta: Any | None = None,
) -> None:
    """
    Universal log function. Dashboard pulls from these fields.
    """
    init_db()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO events(
                ts_utc, tenant, channel, session_id, lead_id,
                event_type, text, intent,
                error_type, error_code, redirect_to,
                meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                utc_now_iso(),
                tenant,
                channel,
                session_id,
                lead_id,
                event_type,
                text,
                intent,
                error_type,
                error_code,
                redirect_to,
                _dump_meta(meta),
            ),
        )
