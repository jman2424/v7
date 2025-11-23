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

# ✅ Correct imports — from top-level handlers folder (NOT service.*)
from handlers.handler_v5 import MessageHandlerV5
from handlers.handler_v6 import MessageHandlerV6
from handlers.handler_v7 import MessageHandlerV7

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

        # Load session snapshot
        sess = self._load_session(ctx)

        # Clean input
        user_text = (user_text or "").strip()

        # Decide which mode to use
        mode = self._decide_mode(ctx)

        # Dispatch to the correct handler
        if mode == "v5":
            reply_payload = self.h_v5.handle(user_text, ctx, sess)
        elif mode == "v6":
            reply_payload = self.h_v6.handle(user_text, ctx, sess)
        else:  # default to v7
            reply_payload = self.h_v7.handle(user_text, ctx, sess)

        # Persist session updates (postcode, nearest branch, last sku/category, last intent)
        self._save_session(ctx, sess, reply_payload)

        # CRM + analytics
        self._log_crm(ctx, user_text, reply_payload)
        self._post_analytics(ctx, user_text, reply_payload, mode)

        return reply_payload

    # ---------------------------------------------------------
    # MODE SELECTION
    # ---------------------------------------------------------

    def _decide_mode(self, ctx: MessageContext) -> str:
        """
        Uses overrides to switch AI modes.
        Default is V7.
        """
        # Example: overrides.json can contain { "ai.mode": "v6" } per-tenant
        mode = self.overrides.get("ai.mode") or "v7"
        return mode.lower()

    # ---------------------------------------------------------
    # SESSION STORAGE
    # ---------------------------------------------------------

    def _load_session(self, ctx: MessageContext) -> Dict[str, Any]:
        """
        Pulls a lightweight session snapshot from the Memory store.
        Handed into V5/V6/V7 handlers so they can use postcode / last_sku etc.
        """
        return {
            "postcode": self.memory.get(ctx.session_id, "postcode"),
            "nearest_branch_id": self.memory.get(ctx.session_id, "nearest_branch_id"),
            "last_category": self.memory.get(ctx.session_id, "last_category"),
            "last_sku": self.memory.get(ctx.session_id, "last_sku"),
            "last_intent": self.memory.get(ctx.session_id, "last_intent"),
        }

    def _save_session(self, ctx: MessageContext, sess: Dict[str, Any], reply: Dict[str, Any]) -> None:
        """
        Writes back important session fields based on the handler's reply.
        This is what makes follow-ups like "price", "more like that", or
        "nearest store" actually work.
        """
        ttl = DEFAULT_SESSION_TTL
        entities = reply.get("entities") or {}
        facts = reply.get("facts") or {}

        # ----- Postcode -----
        postcode = (
            entities.get("postcode")
            or facts.get("delivery", {}).get("postcode")
            or sess.get("postcode")
        )
        if postcode:
            self.memory.set(ctx.session_id, "postcode", postcode, ttl=ttl)

        # ----- Nearest branch -----
        nearest = (facts.get("branch") or {}).get("nearest") or {}
        branch_id = nearest.get("id") or sess.get("nearest_branch_id")
        if branch_id:
            self.memory.set(ctx.session_id, "nearest_branch_id", branch_id, ttl=ttl)

        # ----- Last category -----
        category = entities.get("category")

        # fall back to first search result's category if not explicitly in entities
        if not category:
            items = facts.get("items") or []
            if items:
                first = items[0]
                category = (
                    first.get("category")
                    or first.get("category_key")
                    or first.get("tags", [None])[0]
                )

        if category:
            self.memory.set(ctx.session_id, "last_category", category, ttl=ttl)

        # ----- Last SKU (for "price" follow-ups) -----
        sku = entities.get("sku")

        # price tool result
        if not sku and facts.get("price"):
            sku = facts["price"].get("sku")

        # or first search result
        if not sku:
            items = facts.get("items") or []
            if items:
                sku = items[0].get("sku")

        if sku:
            self.memory.set(ctx.session_id, "last_sku", sku, ttl=ttl)

        # ----- Last intent (for V7 brain hinting / analytics) -----
        last_intent = reply.get("intent")
        if last_intent:
            self.memory.set(ctx.session_id, "last_intent", last_intent, ttl=ttl)

    # ---------------------------------------------------------
    # CRM LOGGING
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

        # User message
        self.crm.append_conversation(
            ctx.tenant,
            lead_id=lead_id,
            message={"from": "user", "text": user_text},
        )

        # Assistant message
        self.crm.append_conversation(
            ctx.tenant,
            lead_id=lead_id,
            message={"from": "assistant", "text": reply.get("reply")},
        )

    # ---------------------------------------------------------
    # ANALYTICS LOGGING
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
