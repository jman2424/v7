# service/analytics_db.py
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/app/logs/analytics.db")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _has_column(con: sqlite3.Connection, table: str, col: str) -> bool:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    return any(r["name"] == col for r in rows)


def _ensure_events_columns(con: sqlite3.Connection) -> None:
    """
    Auto-migrate existing DBs so your dashboard never breaks
    when you add fields later.
    """
    # If events table doesn't exist yet, init_db() will create it fresh.
    # If it exists, add missing columns.
    add_cols = [
        ("text", "TEXT"),
        ("intent", "TEXT"),
        ("error_type", "TEXT"),
        ("error_code", "TEXT"),
        ("redirect_to", "TEXT"),
    ]
    for name, ddl in add_cols:
        if not _has_column(con, "events", name):
            con.execute(f"ALTER TABLE events ADD COLUMN {name} {ddl};")


def init_db() -> None:
    with _conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            tenant TEXT NOT NULL,
            channel TEXT NOT NULL,          -- 'whatsapp' | 'web' | etc
            session_id TEXT NOT NULL,
            lead_id TEXT,                   -- optional stable ID (phone/email hash)
            event_type TEXT NOT NULL,       -- 'msg_in'|'msg_out'|'fallback'|'error'|'redirect' etc
            meta_json TEXT,                 -- optional JSON string

            -- ✅ structured columns used by dashboard insights
            text TEXT,
            intent TEXT,
            error_type TEXT,
            error_code TEXT,
            redirect_to TEXT
        );
        """)

        # ✅ migrate older DBs
        _ensure_events_columns(con)

        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")

        con.execute("""
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
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);")


def upsert_lead(tenant: str, lead_id: str, phone: str | None = None, name: str | None = None) -> None:
    now = utc_now_iso()
    with _conn() as con:
        con.execute("""
        INSERT INTO leads (lead_id, tenant, phone, name, updated_utc)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(lead_id) DO UPDATE SET
            phone=COALESCE(excluded.phone, leads.phone),
            name=COALESCE(excluded.name, leads.name),
            updated_utc=excluded.updated_utc;
        """, (lead_id, tenant, phone, name, now))


def set_lead_session(lead_id: str, session_id: str) -> None:
    now = utc_now_iso()
    with _conn() as con:
        con.execute("""
        UPDATE leads SET last_session_id=?, updated_utc=?
        WHERE lead_id=?;
        """, (session_id, now, lead_id))


def log_event(
    tenant: str,
    channel: str,
    session_id: str,
    event_type: str,
    lead_id: str | None = None,
    meta_json: str | None = None,
    *,
    text: str | None = None,
    intent: str | None = None,
    error_type: str | None = None,
    error_code: str | None = None,
    redirect_to: str | None = None,
) -> None:
    with _conn() as con:
        con.execute("""
        INSERT INTO events(
          ts_utc, tenant, channel, session_id, lead_id, event_type, meta_json,
          text, intent, error_type, error_code, redirect_to
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            utc_now_iso(), tenant, channel, session_id, lead_id, event_type, meta_json,
            text, intent, error_type, error_code, redirect_to
        ))
