# service/analytics_db.py
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/app/logs/analytics.db")


# -----------------------------
# Connection
# -----------------------------
def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# -----------------------------
# Schema / migrations
# -----------------------------
_EVENTS_COLS_REQUIRED = {
    # existing / core
    "ts_utc": "TEXT NOT NULL",
    "tenant": "TEXT NOT NULL",
    "channel": "TEXT NOT NULL",
    "session_id": "TEXT NOT NULL",
    "lead_id": "TEXT",
    "event_type": "TEXT NOT NULL",
    "meta_json": "TEXT",
    # needed by admin dashboard / insights
    "text": "TEXT",            # inbound/outbound message (sanitized)
    "intent": "TEXT",          # classifier output or router label
    "error_type": "TEXT",      # exception class / category
    "error_code": "TEXT",      # short code e.g. "openai_timeout"
    "redirect_to": "TEXT",     # where user was routed (if event_type='redirect')
}

_LEADS_COLS_REQUIRED = {
    "lead_id": "TEXT PRIMARY KEY",
    "tenant": "TEXT NOT NULL",
    "name": "TEXT",
    "phone": "TEXT",
    "status": "TEXT DEFAULT 'Open'",
    "tags": "TEXT DEFAULT ''",
    "last_session_id": "TEXT",
    "updated_utc": "TEXT NOT NULL",
}


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
        (name,),
    ).fetchone()
    return bool(row)


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    # row fields: cid, name, type, notnull, dflt_value, pk
    return {r["name"] for r in rows}


def _add_column_if_missing(con: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    cols = _table_columns(con, table)
    if col in cols:
        return
    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl};")


def _init_events_table(con: sqlite3.Connection) -> None:
    # Create with full schema if missing
    if not _table_exists(con, "events"):
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
                meta_json TEXT,
                text TEXT,
                intent TEXT,
                error_type TEXT,
                error_code TEXT,
                redirect_to TEXT
            );
            """
        )

    # Migrate: add any missing columns safely
    for col, ddl in _EVENTS_COLS_REQUIRED.items():
        # id exists already if table was created by us; if someone created custom table, still fine
        if col == "id":
            continue
        _add_column_if_missing(con, "events", col, ddl)

    # Indexes (safe)
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")
    # Helpful for insights drilldowns
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_intent ON events(intent);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel);")


def _init_leads_table(con: sqlite3.Connection) -> None:
    if not _table_exists(con, "leads"):
        # Create with full schema if missing
        cols_sql = ",\n".join([f"{k} {v}" for k, v in _LEADS_COLS_REQUIRED.items()])
        con.execute(f"CREATE TABLE IF NOT EXISTS leads (\n{cols_sql}\n);")

    # Migrate: add missing non-PK columns (SQLite cannot add PK constraints via ALTER)
    # So we only add columns that are not lead_id primary key.
    existing = _table_columns(con, "leads")
    for col, ddl in _LEADS_COLS_REQUIRED.items():
        if col == "lead_id":
            continue
        if col not in existing:
            _add_column_if_missing(con, "leads", col, ddl)

    con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_status ON leads(tenant, status);")


def init_db() -> None:
    """
    Idempotent create + migrate. Safe to run every boot.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as con:
        _init_events_table(con)
        _init_leads_table(con)


def ensure_ready() -> None:
    """
    Preferred startup hook.
    """
    init_db()


# -----------------------------
# Lead helpers
# -----------------------------
def upsert_lead(tenant: str, lead_id: str, phone: str | None = None, name: str | None = None) -> None:
    now = utc_now_iso()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (lead_id, tenant, phone, name, updated_utc)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lead_id) DO UPDATE SET
                phone=COALESCE(excluded.phone, leads.phone),
                name=COALESCE(excluded.name, leads.name),
                tenant=excluded.tenant,
                updated_utc=excluded.updated_utc;
            """,
            (lead_id, tenant, phone, name, now),
        )


def set_lead_session(lead_id: str, session_id: str) -> None:
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


# -----------------------------
# Event logging
# -----------------------------
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
    """
    Backwards compatible: old calls still work.
    New fields power the admin dashboard (insights, errors, channels, intents).
    """
    with _conn() as con:
        con.execute(
            """
            INSERT INTO events (
                ts_utc, tenant, channel, session_id, lead_id, event_type,
                meta_json, text, intent, error_type, error_code, redirect_to
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
                meta_json,
                text,
                intent,
                error_type,
                error_code,
                redirect_to,
            ),
        )
