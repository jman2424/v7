# service/analytics_db.py
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

DB_PATH = os.environ.get("ANALYTICS_DB_PATH") or os.path.join("logs", "analytics.db")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


# ✅ REQUIRED BY app_factory
def init_db() -> None:
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id        INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc    TEXT NOT NULL,
              tenant    TEXT NOT NULL,
              channel   TEXT NOT NULL,
              session_id TEXT NOT NULL,
              lead_id   TEXT,
              event_type TEXT NOT NULL,
              text      TEXT,
              intent    TEXT,
              error_type TEXT,
              error_code TEXT,
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
              last_session_id TEXT,
              updated_utc TEXT NOT NULL,
              UNIQUE(tenant, lead_id)
            );
            """
        )


def upsert_lead(*, tenant: str, lead_id: str) -> None:
    with _conn() as con:
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, last_session_id, updated_utc)
            VALUES (?, ?, '', ?)
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              updated_utc=excluded.updated_utc;
            """,
            ((tenant or "default"), (lead_id or "unknown"), _utc_now_iso()),
        )


def set_lead_session(*, lead_id: str, session_id: str, tenant: Optional[str] = None) -> None:
    with _conn() as con:
        if tenant:
            con.execute(
                "UPDATE leads SET last_session_id=?, updated_utc=? WHERE tenant=? AND lead_id=?",
                (session_id, _utc_now_iso(), tenant, lead_id),
            )
        else:
            con.execute(
                "UPDATE leads SET last_session_id=?, updated_utc=? WHERE lead_id=?",
                (session_id, _utc_now_iso(), lead_id),
            )


# ✅ accepts meta= so your webchat_routes.py won’t crash
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
    payload = meta if meta is not None else metadata
    meta_json = ""
    if payload is not None:
        try:
            meta_json = json.dumps(payload, ensure_ascii=False)
        except Exception:
            meta_json = json.dumps({"_meta_error": "serialize_failed"})

    with _conn() as con:
        con.execute(
            """
            INSERT INTO events (ts_utc, tenant, channel, session_id, lead_id, event_type,
                                text, intent, error_type, error_code, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                (tenant or "default"),
                (channel or "unknown"),
                (session_id or "unknown"),
                (lead_id or ""),
                (event_type or "unknown"),
                (text or ""),
                (intent or ""),
                (error_type or ""),
                (error_code or ""),
                meta_json,
            ),
        )
