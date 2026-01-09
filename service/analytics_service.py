# service/analytics_service.py
from __future__ import annotations

import os
import csv
import io
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# NOTE: Container passes Settings into this service.
# We keep it typed loosely so you don't fight circular imports.
SettingsLike = Any


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _utc_now_iso() -> str:
    return _utc_iso(datetime.now(timezone.utc))


@dataclass
class AnalyticsService:
    settings: SettingsLike

    def __post_init__(self) -> None:
        # Prefer env override; otherwise store inside /app/logs for Render disk
        self.db_path = os.getenv("ANALYTICS_DB_PATH", "/app/logs/analytics.db")
        self.ensure_ready()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    # -----------------------
    # Boot / schema
    # -----------------------
    def ensure_ready(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._conn() as con:
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
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant, ts_utc);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);")

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

    # -----------------------
    # Write APIs (called by chat routes)
    # -----------------------
    def upsert_lead(
        self,
        tenant: str,
        lead_id: str,
        phone: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        now = _utc_now_iso()
        with self._conn() as con:
            con.execute("""
            INSERT INTO leads (lead_id, tenant, phone, name, updated_utc)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lead_id) DO UPDATE SET
              tenant=excluded.tenant,
              phone=COALESCE(excluded.phone, leads.phone),
              name=COALESCE(excluded.name, leads.name),
              updated_utc=excluded.updated_utc;
            """, (lead_id, tenant, phone, name, now))

    def set_lead_session(self, lead_id: str, session_id: str) -> None:
        now = _utc_now_iso()
        with self._conn() as con:
            con.execute("""
            UPDATE leads
            SET last_session_id=?, updated_utc=?
            WHERE lead_id=?;
            """, (session_id, now, lead_id))

    def log_event(
        self,
        tenant: str,
        channel: str,
        session_id: str,
        event_type: str,
        lead_id: Optional[str] = None,
        meta_json: Optional[str] = None,
    ) -> None:
        with self._conn() as con:
            con.execute("""
            INSERT INTO events(ts_utc, tenant, channel, session_id, lead_id, event_type, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (_utc_now_iso(), tenant, channel, session_id, lead_id, event_type, meta_json))

    # -----------------------
    # Read APIs (dashboard)
    # -----------------------
    def get_kpis(self, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        with self._conn() as con:
            row = con.execute("""
              SELECT
                SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound,
                COUNT(DISTINCT session_id) AS sessions,
                COUNT(DISTINCT lead_id) AS leads
              FROM events
              WHERE tenant=? AND ts_utc >= ?;
            """, (tenant, since)).fetchone()

        return {
            "tenant": tenant,
            "minutes": int(minutes),
            "inbound": int(row["inbound"] or 0),
            "outbound": int(row["outbound"] or 0),
            "sessions": int(row["sessions"] or 0),
            "leads": int(row["leads"] or 0),
        }

    def get_timeseries(self, tenant: str, minutes: int = 1440) -> Dict[str, Any]:
        since = _utc_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))

        # group by hour: YYYY-MM-DDTHH
        with self._conn() as con:
            rows = con.execute("""
              SELECT
                substr(ts_utc, 1, 13) AS t,
                SUM(CASE WHEN event_type='msg_in'  THEN 1 ELSE 0 END) AS inbound,
                SUM(CASE WHEN event_type='msg_out' THEN 1 ELSE 0 END) AS outbound
              FROM events
              WHERE tenant=? AND ts_utc >= ?
              GROUP BY t
              ORDER BY t ASC;
            """, (tenant, since)).fetchall()

        return {
            "tenant": tenant,
            "minutes": int(minutes),
            "bucket_minutes": 60,
            "points": [
                {"t": r["t"], "inbound": int(r["inbound"] or 0), "outbound": int(r["outbound"] or 0)}
                for r in rows
            ],
        }

    def list_leads(self, tenant: str, limit: int = 50) -> List[Dict[str, Any]]:
        limit = min(max(int(limit), 1), 200)
        with self._conn() as con:
            rows = con.execute("""
              SELECT lead_id, name, phone, status, tags, last_session_id, updated_utc
              FROM leads
              WHERE tenant=?
              ORDER BY updated_utc DESC
              LIMIT ?;
            """, (tenant, limit)).fetchall()

        return [dict(r) for r in rows]

    def leads_csv(self, tenant: str) -> str:
        with self._conn() as con:
            rows = con.execute("""
              SELECT updated_utc, name, phone, status, tags, last_session_id, lead_id
              FROM leads
              WHERE tenant=?
              ORDER BY updated_utc DESC;
            """, (tenant,)).fetchall()

        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["updated_utc", "name", "phone", "status", "tags", "session_id", "lead_id"])
        for r in rows:
            w.writerow([
                r["updated_utc"], r["name"], r["phone"], r["status"],
                r["tags"], r["last_session_id"], r["lead_id"]
            ])
        return out.getvalue()
