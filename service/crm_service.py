"""
CRM service: leads + conversations.

Storage:
- In-proc dict with optional JSON snapshot file.
- Dedupe leads by phone (if present) or session_id.
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
    snapshot_path: Optional[str] = "logs/crm_snapshot.json"
    _leads: Dict[str, Lead] = field(default_factory=dict)         # id -> Lead
    _phone_index: Dict[str, str] = field(default_factory=dict)    # phone -> lead_id
    _session_index: Dict[str, str] = field(default_factory=dict)  # session -> lead_id

    # -------- public API --------

    def upsert_lead(
        self,
        tenant: str,
        *,
        name: Optional[str],
        phone: Optional[str],
        channel: str,
        session_id: str,
        tags: Optional[List[str]] = None,
        email: Optional[str] = None,
        status: str = "open",
    ) -> Dict[str, Any]:
        """
        Find or create a lead. Prefer phone; else use session.
        """
        key_id = None
        if phone and phone in self._phone_index:
            key_id = self._phone_index[phone]
        elif session_id in self._session_index:
            key_id = self._session_index[session_id]

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
                self._phone_index[phone] = lead_id
            self._session_index[session_id] = lead_id

        # snapshot occasionally (cheap write-through)
        self._maybe_snapshot()
        return self._to_dict(lead)

    def append_conversation(self, tenant: str, lead_id: str, message: Dict[str, Any]) -> None:
        lead = self._leads.get(lead_id)
        if not lead:
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

    def list_leads(self, *, status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        leads = list(self._leads.values())
        if status:
            leads = [l for l in leads if l.status == status]
        leads.sort(key=lambda l: l.updated_at, reverse=True)
        return [self._to_dict(l) for l in leads[:limit]]

    def get_lead(self, lead_id: str) -> Optional[Dict[str, Any]]:
        l = self._leads.get(lead_id)
        return self._to_dict(l) if l else None

    def update_status(self, lead_id: str, status: str) -> bool:
        l = self._leads.get(lead_id)
        if not l:
            return False
        l.status = status
        l.updated_at = _now_iso()
        self._maybe_snapshot()
        return True

    # -------- internal --------

    def _to_dict(self, l: Lead) -> Dict[str, Any]:
        return {
            "id": l.id,
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
            d = [self._to_dict(l) for l in self._leads.values()]
            os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
            with open(self.snapshot_path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            # best-effort; do not crash chat flow
            pass
