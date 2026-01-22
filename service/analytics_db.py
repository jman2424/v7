# service/analytics_db.py
from __future__ import annotations

import os, sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/app/logs/analytics.db")

# Columns we want on events for the dashboard
EVENT_COLS = {
    "ts_utc": "TEXT NOT NULL",
    "tenant": "TEXT NOT NULL",
    "channel": "TEXT NOT NULL",
    "session_id": "TEXT NOT NULL",
    "lead_id": "TEXT",
    "event_type": "TEXT NOT NULL",
    "meta_json": "TEXT",

    # dashboard extras (safe if you don't use them yet)
    "intent": "TEXT",
    "text": "TEXT",
    "error_type": "TEXT",
    "error_code": "TEXT",
    "redirect_to": "TEXT",
}

LEADS_COLS = {
    "lead_id": "TEXT PRIMARY KEY",
    "tenant": "TEXT NOT NULL",
    "name": "TEXT",
    "phone": "TEXT",
    "status": "TEXT DEFAULT 'Open'",
    "tags": "TEXT DEFAULT ''",
    "last_session_id": "TEXT",
    "updated_utc": "TEXT NOT NULL",
}

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (name,),
    ).fetchone()
    return bool(row)

def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    return {r["name"] for r in rows}

def _add_col_if_missing(con: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    existing = _cols(con, table)
    if col in existing:
        return
    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl};")

def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with _conn() as con:
        # Create base tables if missing
        con.execute("""
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
        """)

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

        # 🔧 MIGRATE: add missing columns (your DB is old → no intent column)
        for col, ddl in EVENT_COLS.items():
            if col == "id":
                continue
            # base columns already exist in create; but this is safe
            if col not in {"id"}:
                try:
                    _add_col_if_missing(con, "events", col, ddl)
                except Exception:
                    # if a column exists with slight differences, ignore
                    pass

        for col, ddl in LEADS_COLS.items():
            if col == "lead_id":
                continue
            try:
                _add_col_if_missing(con, "leads", col, ddl)
            except Exception:
                pass

        # Indexes
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);")

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def upsert_lead(tenant: str, lead_id: str, phone: Optional[str] = None, name: Optional[str] = None) -> None:
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
    lead_id: Optional[str] = None,
    meta_json: Optional[str] = None,

    # optional dashboard fields
    intent: Optional[str] = None,
    text: Optional[str] = None,
    error_type: Optional[str] = None,
    error_code: Optional[str] = None,
    redirect_to: Optional[str] = None,
) -> None:
    with _conn() as con:
        con.execute("""
        INSERT INTO events(
            ts_utc, tenant, channel, session_id, lead_id, event_type, meta_json,
            intent, text, error_type, error_code, redirect_to
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            utc_now_iso(), tenant, channel, session_id, lead_id, event_type, meta_json,
            intent, text, error_type, error_code, redirect_to
        ))
