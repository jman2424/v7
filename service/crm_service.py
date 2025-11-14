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
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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

    snapshot_path: Optional[str] = "logs/crm_snapshot.json"

    # id -> Lead
    _leads: Dict[str, Lead] = field(default_factory=dict)

    # (tenant:phone) -> lead_id
    _phone_index: Dict[str, str] = field(default_factory=dict)

    # (tenant:session_id) -> lead_id
    _session_index: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Try to load an existing snapshot on startup (best-effort).
        if not self.snapshot_path or not os.path.exists(self.snapshot_path):
            return
        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        if not isinstance(data, list):
            return

        for item in data:
            try:
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
            except Exception:
                continue

            self._leads[lead.id] = lead

            if lead.phone:
                self._phone_index[self._phone_key(lead.tenant, lead.phone)] = lead.id
            if lead.session_id:
                self._session_index[self._session_key(lead.tenant, lead.session_id)] = lead.id

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
        leads = [l for l in self._leads.values() if l.tenant == tenant]
        if status:
            leads = [l for l in leads if l.status == status]
        leads.sort(key=lambda l: l.updated_at, reverse=True)
        return [self._to_dict(l) for l in leads[:limit]]

    def get_lead(self, tenant: str, lead_id: str) -> Optional[Dict[str, Any]]:
        l = self._leads.get(lead_id)
        if not l or l.tenant != tenant:
            return None
        return self._to_dict(l)

    def update_status(self, tenant: str, lead_id: str, status: str) -> bool:
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

    def _maybe_snapshot(self) -> None:
        if not self.snapshot_path:
            return
        try:
            payload = [self._to_dict(l) for l in self._leads.values()]
            os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
            with open(self.snapshot_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            # best-effort; do not crash chat flow
            pass
