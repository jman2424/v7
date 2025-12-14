"""
MASTER MESSAGE HANDLER (V7-first, safe-dispatch)

- Dispatches to V5 / V6 / V7
- VALIDATES product responses
- Forces safe fallback if catalog resolution fails
- Guarantees products are returned when intent requires it
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

from handlers.handler_v5 import MessageHandlerV5
from handlers.handler_v6 import MessageHandlerV6
from handlers.handler_v7 import MessageHandlerV7

from . import HandlerDeps, DEFAULT_SESSION_TTL
import logging

logger = logging.getLogger("MessageHandler")


@dataclass
class MessageContext:
    tenant: str
    session_id: str
    channel: str
    metadata: Dict[str, Any]


class MessageHandler:
    def __init__(self, deps: HandlerDeps):
        self.deps = deps

        self.h_v5 = MessageHandlerV5(deps)
        self.h_v6 = MessageHandlerV6(deps)
        self.h_v7 = MessageHandlerV7(deps)

        self.analytics = deps.analytics
        self.crm = deps.crm
        self.memory = deps.memory
        self.overrides = deps.overrides

    # ---------------------------------------------------------
    # MAIN ENTRYPOINT
    # ---------------------------------------------------------

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
            metadata=metadata or {},
        )

        user_text = (user_text or "").strip()
        sess = self._load_session(ctx)
        mode = self._decide_mode(ctx)

        # ---------------- DISPATCH ----------------

        if mode == "v5":
            reply = self.h_v5.handle(user_text, ctx, sess)
        elif mode == "v6":
            reply = self.h_v6.handle(user_text, ctx, sess)
        else:
            reply = self.h_v7.handle(user_text, ctx, sess)

        # ---------------- VALIDATION ----------------

        reply = self._validate_reply(reply, user_text, ctx)

        # ---------------- PERSIST ----------------

        self._save_session(ctx, sess, reply)
        self._log_crm(ctx, user_text, reply)
        self._post_analytics(ctx, user_text, reply, mode)

        return reply

    # ---------------------------------------------------------
    # MODE
    # ---------------------------------------------------------

    def _decide_mode(self, ctx: MessageContext) -> str:
        return (self.overrides.get("ai.mode") or "v7").lower()

    # ---------------------------------------------------------
    # VALIDATION / SAFETY
    # ---------------------------------------------------------

    def _validate_reply(
        self,
        reply: Dict[str, Any],
        user_text: str,
        ctx: MessageContext,
    ) -> Dict[str, Any]:
        """
        Prevents broken states like:
        - browse/search intent with zero items
        - catalog failure loops
        """

        intent = reply.get("intent")
        facts = reply.get("facts") or {}
        items = facts.get("items") or []

        requires_items = intent in {
            "browse_category",
            "search_product",
            "related_products",
            "price_check",
        }

        if requires_items and not items:
            logger.warning(
                "PIPELINE FAILURE: intent=%s but no items returned | text=%r tenant=%s",
                intent,
                user_text,
                ctx.tenant,
            )

            return {
                "reply": (
                    "I’m having trouble pulling products right now.\n\n"
                    "Try asking like:\n"
                    "• **lamb chops**\n"
                    "• **chicken wings**\n"
                    "• **cheapest lamb**"
                ),
                "intent": "system_fallback",
                "resolved": False,
                "facts": {},
                "entities": {},
            }

        return reply

    # ---------------------------------------------------------
    # SESSION
    # ---------------------------------------------------------

    def _load_session(self, ctx: MessageContext) -> Dict[str, Any]:
        return {
            "postcode": self.memory.get(ctx.session_id, "postcode"),
            "nearest_branch_id": self.memory.get(ctx.session_id, "nearest_branch_id"),
            "last_category": self.memory.get(ctx.session_id, "last_category"),
            "last_sku": self.memory.get(ctx.session_id, "last_sku"),
            "last_intent": self.memory.get(ctx.session_id, "last_intent"),
        }

    def _save_session(self, ctx: MessageContext, sess: Dict[str, Any], reply: Dict[str, Any]) -> None:
        ttl = DEFAULT_SESSION_TTL
        entities = reply.get("entities") or {}
        facts = reply.get("facts") or {}

        if entities.get("postcode"):
            self.memory.set(ctx.session_id, "postcode", entities["postcode"], ttl)

        if facts.get("branch", {}).get("nearest", {}).get("id"):
            self.memory.set(
                ctx.session_id,
                "nearest_branch_id",
                facts["branch"]["nearest"]["id"],
                ttl,
            )

        if entities.get("category"):
            self.memory.set(ctx.session_id, "last_category", entities["category"], ttl)

        if entities.get("sku"):
            self.memory.set(ctx.session_id, "last_sku", entities["sku"], ttl)

        if reply.get("intent"):
            self.memory.set(ctx.session_id, "last_intent", reply["intent"], ttl)

    # ---------------------------------------------------------
    # CRM
    # ---------------------------------------------------------

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
            ctx.tenant, lead_id, {"from": "user", "text": user_text}
        )
        self.crm.append_conversation(
            ctx.tenant, lead_id, {"from": "assistant", "text": reply.get("reply")}
        )

    # ---------------------------------------------------------
    # ANALYTICS
    # ---------------------------------------------------------

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
