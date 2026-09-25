"""
CRM service: leads + conversations.

Storage:
- In-proc dict with optional JSON snapshot file.
- Dedupe leads by (tenant, phone) if present, else (tenant, session_id).
- Append conversation entries with minimal shape.

Connects:
- services/analytics_service.py for counters (external)
- routes/admin_routes.py for admin views
- services/audit.py for change logs (admin mutations)
"""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from service import session_store


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _default_snapshot_path() -> str:
    configured = (os.getenv("CRM_SNAPSHOT_PATH") or "").strip()
    if configured:
        return configured
    data_root = (os.getenv("V7_DATA_DIR") or "").strip()
    return os.path.join(data_root, "logs", "crm_snapshot.json") if data_root else "logs/crm_snapshot.json"


def _using_postgres() -> bool:
    return os.getenv("V7_STORAGE_BACKEND", "sqlite").strip().lower() == "postgres"


def _pg_tenant(tenant: str) -> str:
    from retrieval.storage import Storage
    return Storage.validate_tenant_key(tenant)


def _pg_payload(row: tuple[Any, Any] | None, tenant: str) -> Dict[str, Any] | None:
    if row is None:
        return None
    identifier, payload = row
    if not isinstance(payload, dict) or payload.get("id") != identifier:
        raise RuntimeError("CRM database record is invalid")
    if _pg_tenant(payload.get("tenant")) != tenant:
        raise RuntimeError("CRM database record has mismatched tenant")
    return payload


def _pg_save(con: Any, tenant: str, payload: Dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    con.execute(
        "INSERT INTO v7_private.crm_records (tenant, id, payload) VALUES (%s, %s, %s::jsonb) "
        "ON CONFLICT (tenant, id) DO UPDATE SET payload=excluded.payload",
        (tenant, payload["id"], encoded),
    )


@dataclass
class Lead:
    id: str
    tenant: str
    name: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    status: str
    tags: List[str]
    created_at: str
    updated_at: str
    conversations: List[Dict[str, Any]] = field(default_factory=list)
    session_id: Optional[str] = None


@dataclass
class CRMService:
    """
    In-memory CRM with optional JSON snapshot.

    Fields:
        snapshot_path: where leads snapshot is stored.
    """

    snapshot_path: Optional[str] = field(default_factory=_default_snapshot_path)

    # id -> Lead
    _leads: Dict[str, Lead] = field(default_factory=dict)

    # (tenant:phone) -> lead_id
    _phone_index: Dict[str, str] = field(default_factory=dict)

    # (tenant:session_id) -> lead_id
    _session_index: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _using_postgres():
            # PostgreSQL is the only CRM copy in this mode.
            return
        if not self.snapshot_path or not os.path.exists(self.snapshot_path):
            return
        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("invalid_crm_snapshot")
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError("invalid_crm_snapshot")
                lead = Lead(
                    id=item["id"],
                    tenant=item.get("tenant", "DEFAULT"),
                    name=item.get("name"),
                    phone=item.get("phone"),
                    email=item.get("email"),
                    status=item.get("status", "open"),
                    tags=item.get("tags", []) or [],
                    created_at=item.get("created_at", _now_iso()),
                    updated_at=item.get("updated_at", _now_iso()),
                    conversations=item.get("conversations", []) or [],
                    session_id=item.get("session_id"),
                )
                self._leads[lead.id] = lead
                if lead.phone:
                    self._phone_index[self._phone_key(lead.tenant, lead.phone)] = lead.id
                if lead.session_id:
                    self._session_index[self._session_key(lead.tenant, lead.session_id)] = lead.id
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError):
            raise RuntimeError("CRM snapshot is unreadable") from None

    # -------- public API --------

    def upsert_lead(
        self,
        tenant: str,
        *,
        name: Optional[str],
        phone: Optional[str],
        channel: str,  # kept for future use / analytics, even if unused here
        session_id: str,
        tags: Optional[List[str]] = None,
        email: Optional[str] = None,
        status: str = "open",
    ) -> Dict[str, Any]:
        """
        Find or create a lead. Prefer (tenant, phone); else (tenant, session_id).
        """
        if _using_postgres():
            return self._pg_upsert_lead(
                tenant, name=name, phone=phone, session_id=session_id,
                tags=tags, email=email, status=status,
            )
        index_phone = self._phone_key(tenant, phone) if phone else None
        index_session = self._session_key(tenant, session_id)

        key_id: Optional[str] = None

        if index_phone and index_phone in self._phone_index:
            key_id = self._phone_index[index_phone]
        elif index_session in self._session_index:
            key_id = self._session_index[index_session]

        if key_id and key_id in self._leads:
            lead = self._leads[key_id]
            # update mutable fields
            if name and not lead.name:
                lead.name = name
            if phone and not lead.phone:
                lead.phone = phone
                self._phone_index[self._phone_key(tenant, phone)] = lead.id
            if tags:
                lead.tags = sorted(set(lead.tags + tags))
            if email and not lead.email:
                lead.email = email
            lead.updated_at = _now_iso()
        else:
            lead_id = str(uuid.uuid4())
            lead = Lead(
                id=lead_id,
                tenant=tenant,
                name=name,
                phone=phone,
                email=email,
                status=status,
                tags=sorted(set(tags or [])),
                created_at=_now_iso(),
                updated_at=_now_iso(),
                session_id=session_id,
            )
            self._leads[lead_id] = lead

            if phone:
                self._phone_index[index_phone] = lead_id
            self._session_index[index_session] = lead_id

        # snapshot occasionally (cheap write-through)
        self._maybe_snapshot()
        return self._to_dict(lead)

    def append_conversation(self, tenant: str, lead_id: str, message: Dict[str, Any]) -> None:
        if _using_postgres():
            tenant_key = _pg_tenant(tenant)
            with session_store.postgres_connection(tenant_key) as con:
                row = con.execute(
                    "SELECT id, payload FROM v7_private.crm_records "
                    "WHERE tenant=%s AND id=%s FOR UPDATE", (tenant_key, lead_id),
                ).fetchone()
                lead = _pg_payload(row, tenant_key)
                if lead is None:
                    return
                entry = {
                    "ts": _now_iso(), "from": message.get("from") or "user",
                    "text": message.get("text") or "",
                    "meta": {k: v for k, v in message.items() if k not in {"from", "text"}},
                }
                lead["conversations"] = [*(lead.get("conversations") or []), entry]
                lead["updated_at"] = _now_iso()
                _pg_save(con, tenant_key, lead)
            return
        lead = self._leads.get(lead_id)
        if not lead or lead.tenant != tenant:
            return

        msg = {
            "ts": _now_iso(),
            "from": message.get("from") or "user",
            "text": message.get("text") or "",
            "meta": {k: v for k, v in message.items() if k not in {"from", "text"}},
        }
        lead.conversations.append(msg)
        lead.updated_at = _now_iso()
        self._maybe_snapshot()

    def list_leads(
        self,
        *,
        tenant: str,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        if _using_postgres():
            tenant_key = _pg_tenant(tenant)
            bounded_limit = max(1, min(int(limit), 500))
            with session_store.postgres_connection(tenant_key) as con:
                if status:
                    rows = con.execute(
                        "SELECT id, payload FROM v7_private.crm_records "
                        "WHERE tenant=%s AND payload->>'status'=%s "
                        "ORDER BY payload->>'updated_at' DESC LIMIT %s",
                        (tenant_key, status, bounded_limit),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT id, payload FROM v7_private.crm_records "
                        "WHERE tenant=%s ORDER BY payload->>'updated_at' DESC LIMIT %s",
                        (tenant_key, bounded_limit),
                    ).fetchall()
            return [_pg_payload(row, tenant_key) for row in rows]
        leads = [l for l in self._leads.values() if l.tenant == tenant]
        if status:
            leads = [l for l in leads if l.status == status]
        leads.sort(key=lambda l: l.updated_at, reverse=True)
        return [self._to_dict(l) for l in leads[:limit]]

    def get_lead(self, tenant: str, lead_id: str) -> Optional[Dict[str, Any]]:
        if _using_postgres():
            tenant_key = _pg_tenant(tenant)
            with session_store.postgres_connection(tenant_key) as con:
                row = con.execute(
                    "SELECT id, payload FROM v7_private.crm_records WHERE tenant=%s AND id=%s",
                    (tenant_key, lead_id),
                ).fetchone()
            return _pg_payload(row, tenant_key)
        l = self._leads.get(lead_id)
        if not l or l.tenant != tenant:
            return None
        return self._to_dict(l)

    def update_status(self, tenant: str, lead_id: str, status: str) -> bool:
        if _using_postgres():
            tenant_key = _pg_tenant(tenant)
            with session_store.postgres_connection(tenant_key) as con:
                row = con.execute(
                    "SELECT id, payload FROM v7_private.crm_records "
                    "WHERE tenant=%s AND id=%s FOR UPDATE", (tenant_key, lead_id),
                ).fetchone()
                lead = _pg_payload(row, tenant_key)
                if lead is None:
                    return False
                lead["status"] = status
                lead["updated_at"] = _now_iso()
                _pg_save(con, tenant_key, lead)
            return True
        l = self._leads.get(lead_id)
        if not l or l.tenant != tenant:
            return False
        l.status = status
        l.updated_at = _now_iso()
        self._maybe_snapshot()
        return True

    # -------- internal helpers --------

    @staticmethod
    def _phone_key(tenant: str, phone: str) -> str:
        return f"{tenant}:{phone}"

    @staticmethod
    def _session_key(tenant: str, session_id: str) -> str:
        return f"{tenant}:{session_id}"

    def _to_dict(self, l: Lead) -> Dict[str, Any]:
        return {
            "id": l.id,
            "tenant": l.tenant,
            "name": l.name,
            "phone": l.phone,
            "email": l.email,
            "status": l.status,
            "tags": list(l.tags),
            "created_at": l.created_at,
            "updated_at": l.updated_at,
            "session_id": l.session_id,
            "conversations": list(l.conversations),
        }

    def _pg_upsert_lead(self, tenant, *, name, phone, session_id, tags, email, status):
        tenant_key = _pg_tenant(tenant)
        # Serialize lead matching for a tenant across workers. Without this,
        # simultaneous first messages could create duplicate CRM records.
        lock_key = int.from_bytes(hashlib.sha256(tenant_key.encode()).digest()[:8], "big", signed=True)
        with session_store.postgres_connection(tenant_key) as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
            row = None
            if phone:
                row = con.execute(
                    "SELECT id, payload FROM v7_private.crm_records "
                    "WHERE tenant=%s AND payload->>'phone'=%s LIMIT 1 FOR UPDATE",
                    (tenant_key, phone),
                ).fetchone()
            if row is None:
                row = con.execute(
                    "SELECT id, payload FROM v7_private.crm_records "
                    "WHERE tenant=%s AND payload->>'session_id'=%s LIMIT 1 FOR UPDATE",
                    (tenant_key, session_id),
                ).fetchone()
            lead = _pg_payload(row, tenant_key)
            if lead is None:
                now = _now_iso()
                lead = {
                    "id": str(uuid.uuid4()), "tenant": tenant_key, "name": name,
                    "phone": phone, "email": email, "status": status,
                    "tags": sorted(set(tags or [])), "created_at": now,
                    "updated_at": now, "conversations": [], "session_id": session_id,
                }
            else:
                if name and not lead.get("name"):
                    lead["name"] = name
                if phone and not lead.get("phone"):
                    lead["phone"] = phone
                if email and not lead.get("email"):
                    lead["email"] = email
                if tags:
                    lead["tags"] = sorted(set([*(lead.get("tags") or []), *tags]))
                lead["updated_at"] = _now_iso()
            _pg_save(con, tenant_key, lead)
        return lead

    def _maybe_snapshot(self) -> None:
        if _using_postgres():
            raise RuntimeError("CRM filesystem snapshots are disabled in PostgreSQL mode")
        if not self.snapshot_path:
            return
        payload = [self._to_dict(l) for l in self._leads.values()]
        directory = os.path.dirname(self.snapshot_path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".crm-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.snapshot_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
