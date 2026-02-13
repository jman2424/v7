# service/message_handler.py
"""
MASTER MESSAGE HANDLER (V7-first, safe-dispatch)

RULES:
- NEVER writes msg_in/msg_out/error analytics here.
  Those belong ONLY to transport boundaries:
    - routes/webchat_routes.py
    - routes/whatsapp_routes.py

- This handler may write TELEMETRY only:
    pipeline_in / pipeline_out / pipeline_turn
  Telemetry must never crash the bot.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from handlers.handler_v5 import MessageHandlerV5
from handlers.handler_v6 import MessageHandlerV6
from handlers.handler_v7 import MessageHandlerV7

from . import HandlerDeps, DEFAULT_SESSION_TTL

logger = logging.getLogger("MessageHandler")

# These must NEVER be written from here.
_KPI_EVENT_TYPES = {"msg_in", "msg_out", "error"}


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

        rid = (
            (metadata or {}).get("rid")
            or (metadata or {}).get("request_id")
            or ctx.metadata.get("rid")
            or ctx.metadata.get("request_id")
            or "no_rid"
        )

        logger.info(
            "DISPATCH tenant=%s session=%s channel=%s mode=%s rid=%s text=%r",
            ctx.tenant,
            ctx.session_id,
            ctx.channel,
            mode,
            rid,
            user_text[:120],
        )

        # TELEMETRY ONLY (safe, never KPI)
        self._telemetry(ctx, event_type="pipeline_in", meta={"mode": mode, "rid": rid, "text_len": len(user_text)})

        # ---------------- DISPATCH ----------------
        if mode == "v5":
            reply = self.h_v5.handle(user_text, ctx, sess)
        elif mode == "v6":
            reply = self.h_v6.handle(user_text, ctx, sess)
        else:
            reply = self.h_v7.handle(user_text, ctx, sess)

        logger.info(
            "DISPATCH_RESULT tenant=%s session=%s mode=%s rid=%s intent=%s keys=%s",
            ctx.tenant,
            ctx.session_id,
            mode,
            rid,
            reply.get("intent"),
            sorted(list(reply.keys())),
        )

        # ---------------- VALIDATION ----------------
        reply = self._validate_reply(reply, user_text, ctx)

        # ---------------- PERSIST ----------------
        self._save_session(ctx, sess, reply)
        self._log_crm(ctx, user_text, reply)

        # TELEMETRY ONLY (safe, never KPI)
        self._telemetry(
            ctx,
            event_type="pipeline_out",
            meta={
                "mode": mode,
                "rid": rid,
                "intent": reply.get("intent"),
                "reply_len": len((reply.get("reply") or "")),
            },
        )
        self._telemetry(
            ctx,
            event_type="pipeline_turn",
            meta={
                "mode": mode,
                "rid": rid,
                "intent": reply.get("intent"),
                "ok": True,
                "channel": ctx.channel,
            },
        )

        return reply

    # ---------------------------------------------------------
    # MODE
    # ---------------------------------------------------------
    def _decide_mode(self, ctx: MessageContext) -> str:
        return (self.overrides.get("ai.mode") or "v7").lower()

    # ---------------------------------------------------------
    # VALIDATION / SAFETY
    # ---------------------------------------------------------
    def _validate_reply(self, reply: Dict[str, Any], user_text: str, ctx: MessageContext) -> Dict[str, Any]:
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

        requires_items = intent in {"browse_category", "search_product", "related_products", "price_check"}
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

        nearest_id = (facts.get("branch") or {}).get("nearest", {}).get("id")
        if nearest_id:
            self.memory.set(ctx.session_id, "nearest_branch_id", nearest_id, ttl)

        if entities.get("category"):
            self.memory.set(ctx.session_id, "last_category", entities["category"], ttl)

        if entities.get("sku"):
            self.memory.set(ctx.session_id, "last_sku", entities["sku"], ttl)

        if reply.get("intent"):
            self.memory.set(ctx.session_id, "last_intent", reply["intent"], ttl)

    # ---------------------------------------------------------
    # CRM
    # ---------------------------------------------------------
    def _log_crm(self, ctx: MessageContext, user_text: str, reply: Dict[str, Any]) -> None:
        lead = self.crm.upsert_lead(
            ctx.tenant,
            name=None,
            phone=(reply.get("entities") or {}).get("phone"),
            channel=ctx.channel,
            session_id=ctx.session_id,
            tags=[reply.get("intent")] if reply.get("intent") else None,
        )
        lead_id = lead.get("id") or lead.get("_id") or "unknown"

        self.crm.append_conversation(ctx.tenant, lead_id, {"from": "user", "text": user_text})
        self.crm.append_conversation(ctx.tenant, lead_id, {"from": "assistant", "text": reply.get("reply")})

        # Optional: if analytics has lead helpers, try them (never crash)
        try:
            if hasattr(self.analytics, "upsert_lead"):
                self.analytics.upsert_lead(
                    tenant=ctx.tenant,
                    lead_id=str(lead_id),
                    phone=(reply.get("entities") or {}).get("phone"),
                    name=None,
                )
            if hasattr(self.analytics, "set_lead_session"):
                self.analytics.set_lead_session(tenant=ctx.tenant, lead_id=str(lead_id), session_id=ctx.session_id)
        except Exception:
            logger.exception("analytics lead upsert failed")

    # ---------------------------------------------------------
    # TELEMETRY (safe)
    # ---------------------------------------------------------
    def _telemetry(self, ctx: MessageContext, *, event_type: str, meta: Dict[str, Any]) -> None:
        """
        Telemetry is allowed here, but must NEVER write KPI event types.
        We only emit pipeline_*.
        """
        if not event_type:
            return

        # Hard-block KPI types even if someone passes them by mistake.
        if event_type in _KPI_EVENT_TYPES:
            event_type = f"telemetry_{event_type}"

        # Only allow pipeline telemetry (plus telemetry_* fallback above).
        if not (event_type.startswith("pipeline_") or event_type.startswith("telemetry_")):
            event_type = f"pipeline_{event_type}"

        try:
            meta_json = json.dumps(meta, separators=(",", ":"), ensure_ascii=False)

            fn = getattr(self.analytics, "log_event", None)
            if not callable(fn):
                return

            # Single canonical signature. No weird second signature.
            fn(
                tenant=ctx.tenant,
                channel=ctx.channel,
                session_id=ctx.session_id,
                event_type=event_type,
                lead_id="",  # keep it string; avoids None issues in sqlite inserts
                meta_json=meta_json,
            )
        except Exception:
            # telemetry must never break the app
            logger.exception("telemetry failed event_type=%s", event_type)
