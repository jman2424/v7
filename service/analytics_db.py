# service/analytics_db.py
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

# Default DB location (Render-friendly). Override with ANALYTICS_DB_PATH env var.
DB_PATH = os.environ.get("ANALYTICS_DB_PATH") or os.path.join("logs", "analytics.db")


# -----------------------------
# Helpers
# -----------------------------
def _utc_now_iso() -> str:
    # 2026-01-24T12:34:56Z (no microseconds)
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _conn() -> sqlite3.Connection:
    _ensure_dir(DB_PATH)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    # Safer concurrency + better durability on Render
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _add_column_if_missing(con: sqlite3.Connection, table: str, col: str, ddl_type: str) -> None:
    cols = _table_columns(con, table)
    if col not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl_type}")


def _json_dumps_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"_meta_error": "serialize_failed"}, ensure_ascii=False)


# -----------------------------
# Public API (used by app_factory + routes)
# -----------------------------
def init_db() -> None:
    """
    Creates tables if missing and performs lightweight, safe schema migrations
    (ADD COLUMN only). This keeps the dashboard/API stable across deploys.
    """
    with _conn() as con:
        # Events table (append-only)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc      TEXT NOT NULL,
              tenant      TEXT NOT NULL,
              channel     TEXT NOT NULL,
              session_id  TEXT NOT NULL,
              lead_id     TEXT,
              event_type  TEXT NOT NULL,
              text        TEXT,
              intent      TEXT,
              error_type  TEXT,
              error_code  TEXT,
              meta_json   TEXT
            );
            """
        )

        # Leads table (dashboard expects name/phone/status/tags)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant          TEXT NOT NULL,
              lead_id         TEXT NOT NULL,
              name            TEXT,
              phone           TEXT,
              status          TEXT DEFAULT 'open',
              tags            TEXT,
              last_session_id TEXT,
              updated_utc     TEXT NOT NULL,
              UNIQUE(tenant, lead_id)
            );
            """
        )

        # Lightweight migration path (if an older leads table exists without new columns)
        # Works even when the CREATE TABLE above didn’t run because the table already existed.
        for col, ddl in (
            ("name", "TEXT"),
            ("phone", "TEXT"),
            ("status", "TEXT DEFAULT 'open'"),
            ("tags", "TEXT"),
            ("last_session_id", "TEXT"),
        ):
            _add_column_if_missing(con, "leads", col, ddl)

        # Helpful indices for dashboard queries
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_type ON events(tenant, event_type);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_session ON events(tenant, session_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_tenant_updated ON leads(tenant, updated_utc);")


def upsert_lead(
    *,
    tenant: str,
    lead_id: str,
    name: str | None = None,
    phone: str | None = None,
    status: str | None = None,
    tags: str | None = None,
) -> None:
    """
    Ensures a lead exists. Safe to call frequently.
    Does not overwrite non-null fields unless you pass new values.
    """
    tenant = (tenant or "default").strip()
    lead_id = (lead_id or "unknown").strip()
    now = _utc_now_iso()

    with _conn() as con:
        # Insert if missing
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, name, phone, status, tags, last_session_id, updated_utc)
            VALUES (?, ?, ?, ?, COALESCE(?, 'open'), ?, '', ?)
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              updated_utc=excluded.updated_utc,
              name=COALESCE(excluded.name, leads.name),
              phone=COALESCE(excluded.phone, leads.phone),
              status=COALESCE(excluded.status, leads.status),
              tags=COALESCE(excluded.tags, leads.tags);
            """,
            (tenant, lead_id, name, phone, status, tags, now),
        )


def set_lead_session(*, lead_id: str, session_id: str, tenant: Optional[str] = None) -> None:
    """
    Updates last_session_id for a lead. Prefer passing tenant for correctness.
    """
    lead_id = (lead_id or "unknown").strip()
    session_id = (session_id or "unknown").strip()
    now = _utc_now_iso()

    with _conn() as con:
        if tenant:
            tenant = (tenant or "default").strip()
            con.execute(
                "UPDATE leads SET last_session_id=?, updated_utc=? WHERE tenant=? AND lead_id=?",
                (session_id, now, tenant, lead_id),
            )
        else:
            # Fallback (not ideal if you share lead_id across tenants)
            con.execute(
                "UPDATE leads SET last_session_id=?, updated_utc=? WHERE lead_id=?",
                (session_id, now, lead_id),
            )


def log_event(
    *,
    tenant: str,
    channel: str,
    session_id: str,
    event_type: str,
    text: str = "",
    lead_id: str = "",
    intent: str = "",
    error_type: str = "",
    error_code: str = "",
    meta: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """
    Stores an analytics event. Accepts either meta= or metadata= (compat).
    """
    tenant = (tenant or "default").strip()
    channel = (channel or "unknown").strip()
    session_id = (session_id or "unknown").strip()
    event_type = (event_type or "unknown").strip()
    lead_id = (lead_id or "").strip()
    text = text or ""
    intent = intent or ""
    error_type = error_type or ""
    error_code = error_code or ""

    payload = meta if meta is not None else metadata
    meta_json = _json_dumps_safe(payload) if payload is not None else ""

    with _conn() as con:
        con.execute(
            """
            INSERT INTO events (ts_utc, tenant, channel, session_id, lead_id, event_type,
                                text, intent, error_type, error_code, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                tenant,
                channel,
                session_id,
                lead_id,
                event_type,
                text,
                intent,
                error_type,
                error_code,
                meta_json,
            ),
        )


# -----------------------------
# Optional helper queries (safe for admin APIs)
# -----------------------------
def fetch_leads(*, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
    """
    Returns leads for admin dashboard.
    """
    tenant = (tenant or "default").strip()
    limit = max(1, min(int(limit or 50), 500))

    with _conn() as con:
        rows = con.execute(
            """
            SELECT updated_utc, name, phone, status, tags, last_session_id, lead_id
            FROM leads
            WHERE tenant=?
            ORDER BY updated_utc DESC
            LIMIT ?
            """,
            (tenant, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def fetch_events_recent(*, tenant: str, minutes: int = 1440) -> list[sqlite3.Row]:
    """
    Convenience read for KPIs/graphs (if you need it elsewhere).
    """
    tenant = (tenant or "default").strip()
    minutes = max(1, min(int(minutes or 1440), 60 * 24 * 30))

    # events.ts_utc is ISO Z. SQLite datetime() parses it fine with replace.
    with _conn() as con:
        return con.execute(
            """
            SELECT *
            FROM events
            WHERE tenant=?
              AND datetime(replace(ts_utc,'Z','')) >= datetime('now', ?)
            ORDER BY ts_utc ASC
            """,
            (tenant, f"-{minutes} minutes"),
        ).fetchall()
