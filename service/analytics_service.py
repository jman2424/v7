# service/analytics_service.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from service.analytics_db import init_db, log_event, upsert_lead, set_lead_session

# If you already have read/query functions in analytics_db, import them here.
# If you don't, you can add them into analytics_db OR expand this class later.


class AnalyticsService:
    """
    Thin wrapper so Container can import AnalyticsService.
    Uses the existing analytics_db.py functions.
    """

    def ensure_ready(self) -> None:
        init_db()

    def log_event(
        self,
        tenant: str,
        channel: str,
        session_id: str,
        event_type: str,
        lead_id: Optional[str] = None,
        meta_json: Optional[str] = None,
    ) -> None:
        log_event(
            tenant=tenant,
            channel=channel,
            session_id=session_id,
            event_type=event_type,
            lead_id=lead_id,
            meta_json=meta_json,
        )

    def upsert_lead(self, tenant: str, lead_id: str, phone: str | None = None, name: str | None = None) -> None:
        upsert_lead(tenant=tenant, lead_id=lead_id, phone=phone, name=name)

    def set_lead_session(self, lead_id: str, session_id: str) -> None:
        set_lead_session(lead_id=lead_id, session_id=session_id)
