# service/analytics_db.py
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

# -----------------------------
# Config
# -----------------------------
DB_PATH = os.environ.get("ANALYTICS_DB_PATH") or os.path.join("logs", "analytics.db")

# One-time per-process init (safe with gunicorn multi-workers; each worker runs its own init)
_INIT_LOCK = threading.Lock()
_INIT_DONE = False


# -----------------------------
# Helpers
# -----------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(con: sqlite3.Connection, table: str, wanted: dict[str, str]) -> None:
    """
    wanted: {"col": "col TYPE [DEFAULT ...]"}
    """
    existing = _table_columns(con, table)
    for col, ddl in wanted.items():
        if col not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _ensure_ready() -> None:
    global _INIT_DONE
    if _INIT_DONE:
        return
    with _INIT_LOCK:
        if _INIT_DONE:
            return
        init_db()
        _INIT_DONE = True


# -----------------------------
# DB init + migrations
# -----------------------------
def init_db() -> None:
    """
    REQUIRED by app_factory: init_db()
    Also safe to call repeatedly.
    """
    with _conn() as con:
        # Core tables
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

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant          TEXT NOT NULL,
              lead_id         TEXT NOT NULL,
              last_session_id TEXT,
              updated_utc     TEXT NOT NULL,
              UNIQUE(tenant, lead_id)
            );
            """
        )

        # ---- Migrations (backwards/forwards compatible) ----
        # Your dashboard expects these columns sometimes:
        _ensure_columns(
            con,
            "leads",
            {
                "name": "name TEXT",
                "phone": "phone TEXT",
                "status": "status TEXT",
                # IMPORTANT: support both. Some code selects `tags`,
                # newer code can use `tags_json`
                "tags": "tags TEXT",
                "tags_json": "tags_json TEXT",
            },
        )

        # Useful indexes
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(tenant, lead_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_updated ON leads(tenant, updated_utc)")


# -----------------------------
# Writes
# -----------------------------
def upsert_lead(*, tenant: str, lead_id: str) -> None:
    _ensure_ready()
    tenant = tenant or "default"
    lead_id = lead_id or "unknown"
    now = _utc_now_iso()

    with _conn() as con:
        # write both tags + tags_json with safe defaults
        con.execute(
            """
            INSERT INTO leads (tenant, lead_id, last_session_id, updated_utc, status, tags, tags_json)
            VALUES (?, ?, '', ?, 'Open', '[]', '[]')
            ON CONFLICT(tenant, lead_id) DO UPDATE SET
              updated_utc = excluded.updated_utc;
            """,
            (tenant, lead_id, now),
        )


def set_lead_session(*, lead_id: str, session_id: str, tenant: Optional[str] = None) -> None:
    _ensure_ready()
    now = _utc_now_iso()

    with _conn() as con:
        cols = _table_columns(con, "leads")
        if tenant:
            if "last_session_id" in cols:
                con.execute(
                    "UPDATE leads SET last_session_id=?, updated_utc=? WHERE tenant=? AND lead_id=?",
                    (session_id, now, tenant, lead_id),
                )
        else:
            # fallback (should normally include tenant)
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
    Accepts BOTH meta= and metadata= to avoid crashes.
    """
    _ensure_ready()

    payload = meta if meta is not None else metadata
    meta_json = ""
    if payload is not None:
        try:
            meta_json = json.dumps(payload, ensure_ascii=False)
        except Exception:
            meta_json = json.dumps({"_meta_error": "serialize_failed"}, ensure_ascii=False)

    with _conn() as con:
        con.execute(
            """
            INSERT INTO events (
              ts_utc, tenant, channel, session_id, lead_id,
              event_type, text, intent, error_type, error_code, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                tenant or "default",
                channel or "unknown",
                session_id or "unknown",
                lead_id or "",
                event_type or "unknown",
                text or "",
                intent or "",
                error_type or "",
                error_code or "",
                meta_json,
            ),
        )


# -----------------------------
# Reads used by admin routes
# -----------------------------
def get_leads(*, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
    """
    Returns leads with a safe `tags` list regardless of schema.
    """
    _ensure_ready()
    tenant = tenant or "default"
    limit = max(1, min(int(limit or 50), 500))

    with _conn() as con:
        cols = _table_columns(con, "leads")

        # Build a schema-safe select:
        select_cols = [
            "lead_id",
            "updated_utc",
            ("name" if "name" in cols else "'' AS name"),
            ("phone" if "phone" in cols else "'' AS phone"),
            ("status" if "status" in cols else "'Open' AS status"),
        ]

        # tags can be in tags_json or tags or neither
        if "tags_json" in cols and "tags" in cols:
            select_cols.append("COALESCE(NULLIF(tags_json,''), NULLIF(tags,''), '[]') AS tags_any")
        elif "tags_json" in cols:
            select_cols.append("COALESCE(NULLIF(tags_json,''), '[]') AS tags_any")
        elif "tags" in cols:
            select_cols.append("COALESCE(NULLIF(tags,''), '[]') AS tags_any")
        else:
            select_cols.append("'[]' AS tags_any")

        q = f"""
        SELECT {", ".join(select_cols)}
        FROM leads
        WHERE tenant = ?
        ORDER BY updated_utc DESC
        LIMIT ?
        """

        rows = con.execute(q, (tenant, limit)).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        raw = r["tags_any"] or "[]"
        try:
            tags = json.loads(raw)
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []

        out.append(
            {
                "lead_id": r["lead_id"],
                "updated_utc": r["updated_utc"],
                "name": r["name"],
                "phone": r["phone"],
                "status": r["status"],
                "tags": tags,
            }
        )
    return out
