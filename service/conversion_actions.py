"""Tenant-scoped, owner-configured sales requests and appointment slots."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from service import analytics_db, session_store


DEFAULT_ACTIONS = {
    "consultation": {"enabled": False, "slots": []},
    "quote": {"enabled": False},
    "callback": {"enabled": False},
}
_SLOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
_PHONE = re.compile(r"\+?[0-9 ()\-.]{7,32}\Z")
_ACTIONS = {"consultation", "quote", "callback"}


class ActionError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _start_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError("A slot needs a valid ISO start time") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("A slot start time needs a timezone")
    return parsed.astimezone(timezone.utc)


def validate_actions_config(data: Any) -> dict[str, Any]:
    """Validate owner settings, including unique IDs and timezone-aware slots."""
    if not isinstance(data, dict) or set(data) != _ACTIONS:
        raise ValueError("Expected consultation, quote and callback settings")
    consultation = data["consultation"]
    if not isinstance(consultation, dict) or set(consultation) != {"enabled", "slots"}:
        raise ValueError("Invalid consultation settings")
    if type(consultation["enabled"]) is not bool or not isinstance(consultation["slots"], list):
        raise ValueError("Invalid consultation settings")
    if len(consultation["slots"]) > 100:
        raise ValueError("Too many consultation slots")
    seen: set[str] = set()
    for slot in consultation["slots"]:
        if not isinstance(slot, dict) or set(slot) != {"id", "start_at", "label"}:
            raise ValueError("Invalid consultation slot")
        identifier, start, label = slot["id"], slot["start_at"], slot["label"]
        if not isinstance(identifier, str) or not _SLOT_ID.fullmatch(identifier) or identifier in seen:
            raise ValueError("Invalid or repeated slot ID")
        if not isinstance(start, str) or len(start) > 64:
            raise ValueError("Invalid consultation slot time")
        _start_time(start)
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 120:
            raise ValueError("Invalid consultation slot label")
        seen.add(identifier)
    for action in ("quote", "callback"):
        settings = data[action]
        if not isinstance(settings, dict) or set(settings) != {"enabled"} or type(settings["enabled"]) is not bool:
            raise ValueError(f"Invalid {action} settings")
    return data


def load_actions(storage: Any, tenant: str) -> dict[str, Any]:
    try:
        data = storage.read_json(tenant, "sales_actions.json")
    except FileNotFoundError:
        return json.loads(json.dumps(DEFAULT_ACTIONS))
    except (OSError, ValueError):
        raise ActionError("actions_unavailable", 503) from None
    try:
        return validate_actions_config(data)
    except ValueError:
        raise ActionError("actions_unavailable", 503) from None


def _database() -> sqlite3.Connection:
    if session_store._using_postgres():
        raise RuntimeError("Sales action caller requires PostgreSQL port")
    db = analytics_db._conn()
    try:
        db.execute(
            """CREATE TABLE IF NOT EXISTS sales_action_requests (
                reference TEXT PRIMARY KEY,
                tenant TEXT NOT NULL,
                action TEXT NOT NULL,
                slot_id TEXT,
                slot_start_at TEXT,
                slot_label TEXT,
                name TEXT NOT NULL,
                contact TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                idempotency_key TEXT,
                request_hash TEXT NOT NULL
            )"""
        )
        existing_columns = {row["name"] for row in db.execute("PRAGMA table_info(sales_action_requests)")}
        for column in ("slot_start_at", "slot_label"):
            if column not in existing_columns:
                db.execute(f"ALTER TABLE sales_action_requests ADD COLUMN {column} TEXT")
        db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS sales_action_slot_once
               ON sales_action_requests (tenant, slot_id)
               WHERE action = 'consultation' AND slot_id IS NOT NULL"""
        )
        db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS sales_action_idempotency
               ON sales_action_requests (tenant, idempotency_key)
               WHERE idempotency_key IS NOT NULL"""
        )
        db.execute(
            """CREATE INDEX IF NOT EXISTS sales_action_owner_list
               ON sales_action_requests (tenant, created_at DESC)"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS sales_action_attempts (
                ip_digest TEXT NOT NULL, attempted REAL NOT NULL
            )"""
        )
        db.execute(
            """CREATE INDEX IF NOT EXISTS sales_action_attempts_ip
               ON sales_action_attempts (ip_digest, attempted)"""
        )
        db.commit()
        return db
    except Exception:
        db.close()
        raise


def public_availability(storage: Any, tenant: str) -> dict[str, Any]:
    config = load_actions(storage, tenant)
    available: list[dict[str, str]] = []
    if config["consultation"]["enabled"]:
        if session_store._using_postgres():
            with session_store.postgres_connection(tenant) as db:
                reserved = {
                    row[0] for row in db.execute(
                        "SELECT slot_id FROM v7_private.sales_action_requests "
                        "WHERE tenant=%s AND action='consultation' AND slot_id IS NOT NULL",
                        (tenant,),
                    ).fetchall()
                }
        else:
            db = _database()
            try:
                reserved = {
                    row[0] for row in db.execute(
                        """SELECT slot_id FROM sales_action_requests
                           WHERE tenant=? AND action='consultation' AND slot_id IS NOT NULL""",
                        (tenant,),
                    )
                }
            finally:
                db.close()
        now = datetime.now(timezone.utc)
        available = [
            dict(slot) for slot in config["consultation"]["slots"]
            if slot["id"] not in reserved and _start_time(slot["start_at"]) > now
        ]
    return {
        "consultation": {"enabled": config["consultation"]["enabled"], "slots": available},
        "quote": {"enabled": config["quote"]["enabled"]},
        "callback": {"enabled": config["callback"]["enabled"]},
    }


def _field(value: Any, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ActionError("invalid_request")
    value = value.strip()
    if (required and not value) or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ActionError("invalid_request")
    return value


def _contact(value: Any, action: str) -> str:
    contact = _field(value, maximum=254)
    phone = _PHONE.fullmatch(contact) and 7 <= sum(char.isdigit() for char in contact) <= 15
    if phone or (action != "callback" and _EMAIL.fullmatch(contact)):
        return contact
    raise ActionError("invalid_contact")


def _consume_rate(db: sqlite3.Connection, ip_digest: str) -> None:
    now = time.time()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM sales_action_attempts WHERE attempted<?", (now - 600,))
        count = db.execute(
            "SELECT COUNT(*) FROM sales_action_attempts WHERE ip_digest=? AND attempted>?",
            (ip_digest, now - 600),
        ).fetchone()[0]
        if count >= 8:
            db.commit()
            raise ActionError("rate_limited", 429)
        db.execute(
            "INSERT INTO sales_action_attempts (ip_digest, attempted) VALUES (?,?)",
            (ip_digest, now),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def _consume_rate_postgres(ip_digest: str) -> None:
    lock_key = int.from_bytes(hashlib.sha256(ip_digest.encode()).digest()[:8], "big", signed=True)
    now = time.time()
    with session_store.postgres_connection() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
        db.execute("DELETE FROM v7_private.sales_action_attempts WHERE attempted < %s", (now - 600,))
        count = db.execute(
            "SELECT COUNT(*) FROM v7_private.sales_action_attempts "
            "WHERE ip_digest=%s AND attempted>%s", (ip_digest, now - 600),
        ).fetchone()[0]
        if count >= 8:
            raise ActionError("rate_limited", 429)
        db.execute(
            "INSERT INTO v7_private.sales_action_attempts (ip_digest, attempted) VALUES (%s, %s)",
            (ip_digest, now),
        )


def _submit_action_postgres(storage, tenant, *, action, name, contact, details,
                            slot_id, key, fingerprint, ip_digest):
    _consume_rate_postgres(ip_digest)
    with session_store.postgres_connection(tenant) as db:
        # This also serializes idempotency checks and bookings against the
        # same tenant while preserving the slot's unique database constraint.
        tenant_row = db.execute(
            "SELECT tenant FROM v7_private.tenants WHERE tenant=%s FOR UPDATE", (tenant,),
        ).fetchone()
        if tenant_row is None:
            raise ActionError("action_unavailable", 409)
        if key:
            existing = db.execute(
                "SELECT reference, status, request_hash FROM v7_private.sales_action_requests "
                "WHERE tenant=%s AND idempotency_key=%s", (tenant, key),
            ).fetchone()
            if existing:
                if existing[2] != fingerprint:
                    raise ActionError("idempotency_conflict", 409)
                return {"ok": True, "status": existing[1], "reference": existing[0]}
        config = load_actions(storage, tenant)
        if not config[action]["enabled"]:
            raise ActionError("action_unavailable", 409)
        status, slot_start_at, slot_label = "requested", None, None
        if slot_id:
            slot = next((entry for entry in config["consultation"]["slots"]
                         if entry["id"] == slot_id), None)
            if slot is None or _start_time(slot["start_at"]) <= datetime.now(timezone.utc):
                raise ActionError("slot_unavailable", 409)
            booked = db.execute(
                "SELECT 1 FROM v7_private.sales_action_requests "
                "WHERE tenant=%s AND action='consultation' AND slot_id=%s",
                (tenant, slot_id),
            ).fetchone()
            if booked:
                raise ActionError("slot_unavailable", 409)
            status, slot_start_at, slot_label = "confirmed", slot["start_at"], slot["label"]
        reference = secrets.token_urlsafe(12)
        db.execute(
            "INSERT INTO v7_private.sales_action_requests "
            "(reference, tenant, action, slot_id, slot_start_at, slot_label, "
            "name, contact, details, status, created_at, idempotency_key, request_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (reference, tenant, action, slot_id, slot_start_at, slot_label,
             name, contact, details, status, datetime.now(timezone.utc).isoformat(),
             key, fingerprint),
        )
    return {"ok": True, "status": status, "reference": reference}


def submit_action(storage: Any, tenant: str, payload: dict[str, Any], ip_digest: str) -> dict[str, Any]:
    action = payload.get("action")
    if not isinstance(action, str) or action not in _ACTIONS:
        raise ActionError("invalid_action")
    if payload.get("consent") is not True:
        raise ActionError("consent_required")
    name = _field(payload.get("name"), maximum=120)
    contact = _contact(payload.get("contact"), action)
    details = _field(payload.get("details", ""), maximum=2000, required=False)
    slot_id = payload.get("slot_id")
    if slot_id is not None and (
        action != "consultation" or not isinstance(slot_id, str) or not _SLOT_ID.fullmatch(slot_id)
    ):
        raise ActionError("invalid_slot")
    key = payload.get("idempotency_key")
    if key is not None and (not isinstance(key, str) or not _IDEMPOTENCY_KEY.fullmatch(key)):
        raise ActionError("invalid_idempotency_key")
    fingerprint = hashlib.sha256(
        json.dumps([action, slot_id, name, contact, details], ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    if session_store._using_postgres():
        return _submit_action_postgres(
            storage, tenant, action=action, name=name, contact=contact,
            details=details, slot_id=slot_id, key=key,
            fingerprint=fingerprint, ip_digest=ip_digest,
        )

    db = _database()
    try:
        _consume_rate(db, ip_digest)
        db.execute("BEGIN IMMEDIATE")
        if key:
            existing = db.execute(
                """SELECT reference, status, request_hash FROM sales_action_requests
                   WHERE tenant=? AND idempotency_key=?""",
                (tenant, key),
            ).fetchone()
            if existing:
                if existing["request_hash"] != fingerprint:
                    raise ActionError("idempotency_conflict", 409)
                db.commit()
                return {"ok": True, "status": existing["status"], "reference": existing["reference"]}
        config = load_actions(storage, tenant)
        if not config[action]["enabled"]:
            raise ActionError("action_unavailable", 409)
        status = "requested"
        slot_start_at = None
        slot_label = None
        if slot_id:
            slot = next(
                (entry for entry in config["consultation"]["slots"] if entry["id"] == slot_id),
                None,
            )
            if slot is None or _start_time(slot["start_at"]) <= datetime.now(timezone.utc):
                raise ActionError("slot_unavailable", 409)
            booked = db.execute(
                """SELECT 1 FROM sales_action_requests
                   WHERE tenant=? AND action='consultation' AND slot_id=?""",
                (tenant, slot_id),
            ).fetchone()
            if booked:
                raise ActionError("slot_unavailable", 409)
            status = "confirmed"
            slot_start_at = slot["start_at"]
            slot_label = slot["label"]
        reference = secrets.token_urlsafe(12)
        db.execute(
            """INSERT INTO sales_action_requests
               (reference, tenant, action, slot_id, slot_start_at, slot_label,
                name, contact, details, status, created_at, idempotency_key, request_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (reference, tenant, action, slot_id, slot_start_at, slot_label,
             name, contact, details, status, datetime.now(timezone.utc).isoformat(),
             key, fingerprint),
        )
        db.commit()
        return {"ok": True, "status": status, "reference": reference}
    except sqlite3.IntegrityError:
        db.rollback()
        raise ActionError("slot_unavailable", 409) from None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_action_requests(tenant: str, limit: int = 50) -> list[dict[str, Any]]:
    if session_store._using_postgres():
        from psycopg.rows import dict_row
        with session_store.postgres_connection(tenant) as db:
            with db.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    "SELECT reference, action, slot_id, slot_start_at, slot_label, "
                    "name, contact, details, status, created_at "
                    "FROM v7_private.sales_action_requests WHERE tenant=%s "
                    "ORDER BY created_at DESC, reference DESC LIMIT %s",
                    (tenant, limit),
                ).fetchall()
        return rows
    db = _database()
    try:
        rows = db.execute(
            """SELECT reference, action, slot_id, slot_start_at, slot_label,
                      name, contact, details, status, created_at
               FROM sales_action_requests WHERE tenant=?
               ORDER BY created_at DESC, rowid DESC LIMIT ?""",
            (tenant, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()
