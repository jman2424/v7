# service/analytics_db.py
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/app/logs/analytics.db")

# Desired schema (we will auto-migrate existing DBs)
EVENTS_COLS: Dict[str, str] = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "ts_utc": "TEXT NOT NULL",
    "tenant": "TEXT NOT NULL",
    "channel": "TEXT NOT NULL",          # whatsapp | web | etc
    "session_id": "TEXT NOT NULL",
    "lead_id": "TEXT",
    "event_type": "TEXT NOT NULL",       # msg_in | msg_out | fallback | error | redirect | ...
    "meta_json": "TEXT",

    # Optional fields for dashboard
    "intent": "TEXT",
    "text": "TEXT",
    "error_type": "TEXT",
    "error_code": "TEXT",
    "redirect_to": "TEXT",
}

LEADS_COLS: Dict[str, str] = {
    "lead_id": "TEXT PRIMARY KEY",
    "tenant": "TEXT NOT NULL",
    "name": "TEXT",
    "phone": "TEXT",
    "status": "TEXT DEFAULT 'Open'",
    "tags": "TEXT DEFAULT ''",
    "last_session_id": "TEXT",
    "updated_utc": "TEXT NOT NULL",
}


def _ensure_db_dir() -> None:
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)


def _conn() -> sqlite3.Connection:
    _ensure_db_dir()
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    r = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (table,),
    ).fetchone()
    return bool(r)


def _table_cols(con: sqlite3.Connection, table: str) -> Dict[str, str]:
    """
    Returns {col_name: col_type} for a table.
    """
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    out: Dict[str, str] = {}
    for r in rows:
        out[str(r["name"])] = str(r["type"] or "")
    return out


def _add_column(con: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    # SQLite only supports ALTER TABLE ADD COLUMN (no IF NOT EXISTS)
    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl};")


def _create_events_table(con: sqlite3.Connection) -> None:
    # Create with the minimal base columns first (safe)
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


def _create_leads_table(con: sqlite3.Connection) -> None:
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


def _migrate_table(con: sqlite3.Connection, table: str, desired: Dict[str, str]) -> None:
    existing = _table_cols(con, table)
    for col, ddl in desired.items():
        if col in existing:
            continue
        if col == "id" and table == "events":
            continue
        if col == "lead_id" and table == "leads":
            continue
        try:
            _add_column(con, table, col, ddl)
        except Exception:
            # If DB is weird/locked/partial, don't crash boot.
            pass


def init_db() -> None:
    """
    Create tables and auto-migrate missing columns so old DBs don't break new code.
    """
    with _conn() as con:
        _create_events_table(con)
        _create_leads_table(con)

        # Auto-migrate missing columns
        _migrate_table(con, "events", EVENTS_COLS)
        _migrate_table(con, "leads", LEADS_COLS)

        # Indexes
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def log_event(
    tenant: str,
    channel: str,
    session_id: str,
    event_type: str,
    lead_id: Optional[str] = None,
    meta_json: Optional[str] = None,
    intent: Optional[str] = None,
    text: Optional[str] = None,
    error_type: Optional[str] = None,
    error_code: Optional[str] = None,
    redirect_to: Optional[str] = None,
) -> None:
    """
    Safe logging that works even if some columns didn't exist before (init_db migrates).
    """
    with _conn() as con:
        con.execute("""
        INSERT INTO events(
            ts_utc, tenant, channel, session_id, lead_id, event_type, meta_json,
            intent, text, error_type, error_code, redirect_to
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            utc_now_iso(),
            tenant,
            channel,
            session_id,
            lead_id,
            event_type,
            meta_json,
            intent,
            text,
            error_type,
            error_code,
            redirect_to,
        ))


def upsert_lead(
    tenant: str,
    lead_id: str,
    phone: Optional[str] = None,
    name: Optional[str] = None,
) -> None:
    now = utc_now_iso()
    with _conn() as con:
        con.execute("""
        INSERT INTO leads (lead_id, tenant, phone, name, updated_utc)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(lead_id) DO UPDATE SET
            tenant=excluded.tenant,
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


def has_table(table: str) -> bool:
    with _conn() as con:
        return _table_exists(con, table)


def get_columns(table: str) -> Dict[str, str]:
    with _conn() as con:
        if not _table_exists(con, table):
            return {}
        return _table_cols(con, table)
