"""
MASTER MESSAGE HANDLER (v5 / v6 / v7 dispatcher)

This file:
- Accepts user input
- Loads session
- Chooses which mode handler to use (V5 / V6 / V7)
- Passes the request to that handler
- Saves session + logs analytics + CRM
- Returns unified response payload
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .handler_v5 import MessageHandlerV5
from .handler_v6 import MessageHandlerV6
from .handler_v7 import MessageHandlerV7

from . import HandlerDeps, DEFAULT_SESSION_TTL


@dataclass
class MessageContext:
    tenant: str
    session_id: str
    channel: str
    metadata: Dict[str, Any]


class MessageHandler:

    def __init__(self, deps: HandlerDeps):
        self.deps = deps

        # Instantiate mode-specific handlers
        self.h_v5 = MessageHandlerV5(deps)
        self.h_v6 = MessageHandlerV6(deps)
        self.h_v7 = MessageHandlerV7(deps)

        # Shared utilities
        self.analytics = deps.analytics
        self.crm = deps.crm
        self.memory = deps.memory
        self.overrides = deps.overrides

    # ---------------------------
    # MAIN ENTRYPOINT
    # ---------------------------

    def handle(
        self,
        user_text: str,
        *,
        tenant: str,
        session_id: str,
        channel: str = "web",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        ctx = MessageContext(
            tenant=tenant,
            session_id=session_id,
            channel=channel,
            metadata=metadata or {}
        )

        # Load session before routing
        sess = self._load_session(ctx)
        user_text = (user_text or "").strip()

        # Determine mode (override or default)
        mode = self._decide_mode(ctx)

        if mode == "v5":
            reply_payload = self.h_v5.handle(user_text, ctx, sess)
        elif mode == "v6":
            reply_payload = self.h_v6.handle(user_text, ctx, sess)
        else:
            reply_payload = self.h_v7.handle(user_text, ctx, sess)

        # Save session deltas
        self._save_session(ctx, sess, reply_payload)

        # Log CRM + analytics
        self._log_crm(ctx, user_text, reply_payload)
        self._post_analytics(ctx, user_text, reply_payload, mode)

        return reply_payload

    # ---------------------------
    # MODE SELECTOR
    # ---------------------------

    def _decide_mode(self, ctx: MessageContext) -> str:
        # Allow runtime override (e.g. tenant config or environment flag)
        mode = self.overrides.get("ai.mode") or "v7"
        return mode.lower()

    # ---------------------------
    # SESSION HANDLING
    # ---------------------------

    def _load_session(self, ctx: MessageContext) -> Dict[str, Any]:
        return {
            "postcode": self.memory.get(ctx.session_id, "postcode"),
            "nearest_branch_id": self.memory.get(ctx.session_id, "nearest_branch_id"),
            "last_category": self.memory.get(ctx.session_id, "last_category"),
            "last_sku": self.memory.get(ctx.session_id, "last_sku"),
        }

    def _save_session(self, ctx: MessageContext, sess: Dict[str, Any], reply: Dict[str, Any]) -> None:
        ttl = DEFAULT_SESSION_TTL
        entities = reply.get("entities") or {}
        facts = reply.get("facts") or {}

        if entities.get("postcode"):
            self.memory.set(ctx.session_id, "postcode", entities["postcode"], ttl=ttl)

        if facts.get("branch", {}).get("nearest", {}).get("id"):
            self.memory.set(
                ctx.session_id,
                "nearest_branch_id",
                facts["branch"]["nearest"]["id"],
                ttl=ttl
            )

        if entities.get("category"):
            self.memory.set(ctx.session_id, "last_category", entities["category"], ttl=ttl)

        if entities.get("sku"):
            self.memory.set(ctx.session_id, "last_sku", entities["sku"], ttl=ttl)

    # ---------------------------
    # CRM / ANALYTICS
    # ---------------------------

    def _log_crm(self, ctx: MessageContext, user_text: str, reply: Dict[str, Any]):
        lead = self.crm.upsert_lead(
            ctx.tenant,
            name=None,
            phone=reply.get("entities", {}).get("phone"),
            channel=ctx.channel,
            session_id=ctx.session_id,
            tags=[reply.get("intent")] if reply.get("intent") else None,
        )

        lead_id = lead.get("id") or lead.get("_id") or "unknown"

        self.crm.append_conversation(
            ctx.tenant,
            lead_id=lead_id,
            message={"from": "user", "text": user_text},
        )

        self.crm.append_conversation(
            ctx.tenant,
            lead_id=lead_id,
            message={"from": "assistant", "text": reply.get("reply")},
        )

    def _post_analytics(self, ctx: MessageContext, user_text: str, reply: Dict[str, Any], mode: str):
        self.analytics.log_event(
            ctx.tenant,
            {
                "type": "chat_turn",
                "mode": mode,
                "intent": reply.get("intent"),
                "ok": True,
                "channel": ctx.channel,
                "session_id": ctx.session_id,
            },
        )
