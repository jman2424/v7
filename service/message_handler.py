"""
MASTER MESSAGE HANDLER (V7-first, safe-dispatch)

- Dispatches to V5 / V6 / V7
- VALIDATES product responses
- Forces safe fallback if catalog resolution fails
- Guarantees products are returned when intent requires it
- Adds DISPATCH logging so we can find issues fast
- POSTS analytics in the format AnalyticsService expects
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional
import json
import logging

from handlers.handler_v5 import MessageHandlerV5
from handlers.handler_v6 import MessageHandlerV6
from handlers.handler_v7 import MessageHandlerV7

from . import HandlerDeps, DEFAULT_SESSION_TTL

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
    def handle.compiler_flag(self):  # noqa: E999
        pass
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

        rid = (
            (metadata or {}).get("rid")
            or (metadata or {}).get("request_id")
            or ctx.metadata.get("rid")
            or ctx.metadata.get("request_id")
            or "no_rid"
        )

        logger.info(
            "DISPATCH tenant=%s session=%s channel=%s mode=%s rid=%s text=%r",
            tenant,
            session_id,
            channel,
            mode,
            rid,
            user_text[:120],
        )

        # ---- analytics: inbound message ----
        self._post_analytics_in(ctx, user_text, mode, rid)

        if mode == "v5":
            reply = self.h_v5.handle(user_text, ctx, sess)
        elif mode == "v6":
            reply = self.h_v6.handle(user_text, ctx, sess)
        else:
            reply = self.h_v7.handle(user_text, ctx, sess)

        logger.info(
            "DISPATCH_RESULT tenant=%s session=%s mode=%s rid=%s intent=%s keys=%s",
            tenant,
            session_id,
            mode,
            rid,
            reply.get("intent"),
            sorted(list(reply.keys())),
        )

        reply = self._validate_reply(reply, user_text, ctx)

        self._save_session(ctx, sess, reply)
        self._log_crm(ctx, user_text, reply)

        # ---- analytics: outbound message + chat_turn meta ----
        self._post_analytics_out(ctx, user_text, reply, mode, rid)

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

        intent = (reply.get("intent") or "").strip()
        facts = reply.get("facts") or {}
        items = facts.get("items") or []

        text = (user_text or "").strip().lower()
        known_category_words = {
            "chicken",
            "lamb",
            "beef",
            "groceries",
            "grocery",
            "frozen",
            "frozen meats",
            "frozen_meats",
            "marinated",
            "marinated meats",
            "marinated_meats",
        }
        looks_like_bare_category = (len(text.split()) <= 2) and (text in known_category_words)

        if looks_like_bare_category and not items:
            logger.warning(
                "PIPELINE FAILURE: bare-category but no items | text=%r intent=%s tenant=%s session=%s",
                user_text,
                intent,
                ctx.tenant,
                ctx.session_id,
            )
            return {
                "reply": (
                    f"Got it — **{text}**.\n\n"
                    "Tell me what you want and I’ll pull options:\n"
                    "• wings / thighs / breast\n"
                    "• mince / chops / ribs\n"
                    "• or ask: **cheapest**, **best for BBQ**, **family pack**"
                ),
                "intent": "system_force_browse",
                "resolved": False,
                "facts": {"force_category": text},
                "entities": {"category": text},
            }

        requires_items = intent in {
            "browse_category",
            "search_product",
            "related_products",
            "price_check",
        }

        if requires_items and not items:
            logger.warning(
                "PIPELINE FAILURE: intent=%s but no items returned | text=%r tenant=%s session=%s",
                intent,
                user_text,
                ctx.tenant,
                ctx.session_id,
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

        self.crm.append_conversation(ctx.tenant, lead_id, {"from": "user", "text": user_text})
        self.crm.append_conversation(ctx.tenant, lead_id, {"from": "assistant", "text": reply.get("reply")})

        # ALSO upsert into analytics DB so /admin/api/leads isn't empty
        try:
            self.analytics.upsert_lead(
                tenant=ctx.tenant,
                lead_id=str(lead_id),
                phone=reply.get("entities", {}).get("phone"),
                name=None,
            )
            self.analytics.set_lead_session(str(lead_id), ctx.session_id)
        except Exception:
            logger.exception("analytics lead upsert failed")

    # ---------------------------------------------------------
    # ANALYTICS (correct format)
    # ---------------------------------------------------------
    def _post_analytics_in(self, ctx: MessageContext, user_text: str, mode: str, rid: str) -> None:
        try:
            meta = {
                "type": "chat_turn",
                "dir": "in",
                "mode": mode,
                "rid": rid,
                "text_len": len(user_text or ""),
            }
            self.analytics.log_event(
                tenant=ctx.tenant,
                channel=ctx.channel,
                session_id=ctx.session_id,
                event_type="msg_in",
                lead_id=None,
                meta_json=json.dumps(meta),
            )
        except Exception:
            logger.exception("analytics msg_in failed")

    def _post_analytics_out(self, ctx: MessageContext, user_text: str, reply: Dict[str, Any], mode: str, rid: str) -> None:
        try:
            # outbound
            meta_out = {
                "type": "chat_turn",
                "dir": "out",
                "mode": mode,
                "rid": rid,
                "intent": reply.get("intent"),
                "reply_len": len((reply.get("reply") or "")),
            }
            self.analytics.log_event(
                tenant=ctx.tenant,
                channel=ctx.channel,
                session_id=ctx.session_id,
                event_type="msg_out",
                lead_id=None,
                meta_json=json.dumps(meta_out),
            )

            # extra: store the intent as another event (optional)
            meta_turn = {
                "type": "chat_turn",
                "mode": mode,
                "rid": rid,
                "intent": reply.get("intent"),
                "ok": True,
            }
            self.analytics.log_event(
                tenant=ctx.tenant,
                channel=ctx.channel,
                session_id=ctx.session_id,
                event_type="chat_turn",
                lead_id=None,
                meta_json=json.dumps(meta_turn),
            )
        except Exception:
            logger.exception("analytics msg_out failed")
