# service/message_handler.py
"""
MASTER MESSAGE HANDLER (V7-first, safe-dispatch)

Key upgrades in this remake:
- Keeps postcode + nearest-branch safe routing
- Does NOT pretend the system is broken for weak/noisy inputs
- Adds real session follow-up memory:
    * last_product_query
    * last_items
    * last_product_names
- Preserves existing category / sku / postcode memory
- Makes follow-up questions like "are they halal" more likely to work downstream
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from handlers.handler_v5 import MessageHandlerV5
from handlers.handler_v6 import MessageHandlerV6
from handlers.handler_v7 import MessageHandlerV7
from service.sales_agent import SalesAgentPolicy
from service.validators import normalize_postcode
from . import DEFAULT_SESSION_TTL, HandlerDeps

logger = logging.getLogger("MessageHandler")

_KPI_EVENT_TYPES = {"msg_in", "msg_out", "error"}

_RE_ONLY_SYMBOLS = re.compile(r"^[^A-Za-z0-9]+$")
_RE_HAS_ALPHA = re.compile(r"[A-Za-z]")
_RE_WORD3 = re.compile(r"[A-Za-z]{3,}")
_RE_MULTI_SPACE = re.compile(r"\s+")

_NEAREST_BRANCH_PAT = re.compile(
    r"\b(nearest|closest|nearby)\s+(branch|store|shop)\b"
    r"|\bmy\s+nearest\s+(branch|store|shop)\b"
    r"|\bnearst\s+(branch|store|shop)\b",
    re.I,
)

_POSTCODE_FULL_IN_TEXT = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)
_POSTCODE_OUTWARD_STANDALONE = re.compile(r"^\s*([A-Z]{1,2}\d{1,2}[A-Z]?)\s*$", re.I)

_FULL_LIST_PAT = re.compile(
    r"\b(full|all|everything|entire|whole)\b.*\b(products?|items?|list|catalog|catalogue|range)\b",
    re.I,
)

_TEST_NOISE = {
    "test", "tester", "testing", "demo", "dmo", "tst",
    "test1", "test2", "test3",
    "hello", "hi", "hey", "yo", "there", "sup",
}

_GREETINGS = {
    "hello", "hi", "hey", "hiya", "yo", "sup", "salam", "salaam",
    "asalam", "assalam", "good morning", "good afternoon", "good evening",
}


def _collapse_spaces(s: str) -> str:
    return _RE_MULTI_SPACE.sub(" ", (s or "")).strip()


def _extract_postcode_anywhere(text: str) -> Optional[str]:
    if not text:
        return None
    s = text.strip().upper()

    m = _POSTCODE_FULL_IN_TEXT.search(s)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    m2 = _POSTCODE_OUTWARD_STANDALONE.match(s)
    if m2:
        return m2.group(1)

    compact = re.sub(r"[^A-Z0-9]", "", s)
    return normalize_postcode(compact)


def _maybe_normalize_postcode_for_dispatch(user_text: str) -> str:
    t = (user_text or "").strip()
    if not t:
        return t

    pc = normalize_postcode(t)
    if pc:
        return pc

    compact = re.sub(r"\s+", "", t).upper()
    if " " not in compact and 5 <= len(compact) <= 8:
        suggestion = f"{compact[:-3]} {compact[-3:]}"
        pc2 = normalize_postcode(suggestion)
        if pc2:
            return pc2

    return t


def _is_postcode_like(text: str) -> bool:
    if not text:
        return False
    if normalize_postcode(text):
        return True
    if _POSTCODE_FULL_IN_TEXT.search(text.upper()):
        return True

    s = re.sub(r"\s+", "", text.strip().upper())
    if len(s) < 4 or len(s) > 8:
        return False
    letters = sum(ch.isalpha() for ch in s)
    digits = sum(ch.isdigit() for ch in s)
    return letters >= 2 and digits >= 1


def _looks_like_noise(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in _TEST_NOISE:
        return True

    if len(t) <= 2 and t.isalpha():
        return True

    return False


def _safe_list_strings(values: Any, limit: int = 12) -> List[str]:
    out: List[str] = []
    if not isinstance(values, list):
        return out
    for v in values[:limit]:
        s = str(v).strip()
        if s:
            out.append(s)
    return out


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
        self.sales_agent = SalesAgentPolicy()

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
        user_text = _maybe_normalize_postcode_for_dispatch(user_text)

        sess = self._load_session(ctx)
        mode = self._decide_mode(ctx)

        rid = (
            (metadata or {}).get("rid")
            or (metadata or {}).get("request_id")
            or ctx.metadata.get("rid")
            or ctx.metadata.get("request_id")
            or "no_rid"
        )

        guarded = self._guard_input(user_text, sess=sess)
        if guarded is not None:
            guarded = self.sales_agent.guide(guarded, user_text=user_text, session=sess)
            self._save_session(ctx, sess, guarded)
            logger.info(
                "DISPATCH_GUARDED tenant=%s session=%s channel=%s mode=%s rid=%s intent=%s text=%r",
                ctx.tenant, ctx.session_id, ctx.channel, mode, rid, guarded.get("intent"), user_text[:120],
            )
            self._telemetry(
                ctx,
                event_type="pipeline_turn",
                meta={
                    "mode": mode,
                    "rid": rid,
                    "intent": guarded.get("intent"),
                    "ok": True,
                    "guarded": True,
                    "channel": ctx.channel,
                },
            )
            return guarded

        logger.info(
            "DISPATCH tenant=%s session=%s channel=%s mode=%s rid=%s text=%r",
            ctx.tenant, ctx.session_id, ctx.channel, mode, rid, user_text[:120],
        )

        self._telemetry(
            ctx,
            event_type="pipeline_in",
            meta={"mode": mode, "rid": rid, "text_len": len(user_text)},
        )

        if mode == "v5":
            reply = self.h_v5.handle(user_text, ctx, sess)
        elif mode == "v6":
            reply = self.h_v6.handle(user_text, ctx, sess)
        else:
            reply = self.h_v7.handle(user_text, ctx, sess)

        logger.info(
            "DISPATCH_RESULT tenant=%s session=%s mode=%s rid=%s intent=%s keys=%s",
            ctx.tenant, ctx.session_id, mode, rid, reply.get("intent"), sorted(list(reply.keys())),
        )

        reply = self._validate_reply(reply, user_text, ctx, sess)
        reply = self.sales_agent.guide(reply, user_text=user_text, session=sess)
        self._save_session(ctx, sess, reply)
        self._log_crm(ctx, user_text, reply)

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
            meta={"mode": mode, "rid": rid, "intent": reply.get("intent"), "ok": True, "channel": ctx.channel},
        )

        return reply

    # ---------------------------------------------------------
    # PRE-DISPATCH INPUT GUARD
    # ---------------------------------------------------------
    def _guard_input(self, user_text: str, *, sess: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        t = (user_text or "").strip()
        if not t:
            return {
                "reply": "Send a product, delivery area, or branch question.",
                "intent": "system_empty",
                "resolved": False,
                "facts": {},
                "entities": {},
            }

        if _is_postcode_like(t) or _POSTCODE_FULL_IN_TEXT.search(t.upper()):
            return None

        if _NEAREST_BRANCH_PAT.search(t):
            return None

        if _FULL_LIST_PAT.search(t):
            return None

        tl = _collapse_spaces(t).lower()

        if tl in _GREETINGS:
            return None

        if _RE_ONLY_SYMBOLS.match(t):
            return {
                "reply": "Type a product or a postcode for delivery.",
                "intent": "system_clarify",
                "resolved": False,
                "facts": {"reason": "symbols_only"},
                "entities": {},
            }

        letters = sum(ch.isalpha() for ch in t)
        digits = sum(ch.isdigit() for ch in t)
        looks_like_short_code = (len(t) <= 8 and letters >= 2 and digits >= 2 and " " not in t)
        looks_like_gibberish = (
            len(t) <= 5 and _RE_HAS_ALPHA.search(t) and digits == 0 and " " not in t and not _RE_WORD3.search(t)
        )

        if looks_like_short_code or looks_like_gibberish:
            return {
                "reply": (
                    "I didn’t catch that.\n\n"
                    "Send either:\n"
                    "• a product or category\n"
                    "• or a postcode for delivery (e.g. **E1 6AN**)"
                ),
                "intent": "system_clarify",
                "resolved": False,
                "facts": {"reason": "nonsense_input"},
                "entities": {},
            }

        return None

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
        sess: Dict[str, Any],
    ) -> Dict[str, Any]:
        intent = (reply.get("intent") or "").strip()
        facts = reply.get("facts") or {}
        items = facts.get("items") or []
        text = (user_text or "").strip()
        lower = text.lower()

        requires_items = intent in {"browse_category", "search_product", "related_products", "price_check"}
        if requires_items and not items:
            if _looks_like_noise(text):
                return {
                    "reply": (
                        "Tell me what you want to do:\n"
                        "• search products or browse a category\n"
                        "• check delivery (e.g. **E7 9QS**)\n"
                        "• nearest branch (type **nearest branch**)\n"
                        "• or ask for the product catalog"
                    ),
                    "intent": "system_clarify",
                    "resolved": False,
                    "facts": {"reason": "low_signal_input"},
                    "entities": {},
                }

            q = (
                (reply.get("entities") or {}).get("query")
                or (reply.get("entities") or {}).get("product_name")
                or text
            )
            return {
                "reply": (
                    f"I couldn’t find matches for **{q}**.\n\n"
                    "Try a different product name, category, feature, or ask for the catalog."
                ),
                "intent": "system_no_results",
                "resolved": False,
                "facts": {"reason": "no_items"},
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
            "last_product_query": self.memory.get(ctx.session_id, "last_product_query"),
            "last_items": self.memory.get(ctx.session_id, "last_items", []),
            "last_product_names": self.memory.get(ctx.session_id, "last_product_names", []),
            "sales_agent": self.memory.get(ctx.session_id, "sales_agent", {}),
        }

    def _save_session(self, ctx: MessageContext, sess: Dict[str, Any], reply: Dict[str, Any]) -> None:
        ttl = DEFAULT_SESSION_TTL
        entities = reply.get("entities") or {}
        facts = reply.get("facts") or {}
        items = facts.get("items") or []

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

        agent = reply.get("agent")
        if isinstance(agent, dict):
            self.memory.set(
                ctx.session_id,
                "sales_agent",
                {
                    "stage": agent.get("stage"),
                    "objective": agent.get("objective"),
                    "next_action": agent.get("next_action"),
                },
                ttl,
            )

        product_query = entities.get("product_name")
        if product_query:
            self.memory.set(ctx.session_id, "last_product_query", product_query, ttl)

        if items:
            item_skus = []
            item_names = []
            for it in items[:12]:
                if not isinstance(it, dict):
                    continue
                sku = str(it.get("sku") or it.get("id") or it.get("code") or "").strip()
                name = str(it.get("name") or it.get("title") or "").strip()
                if sku:
                    item_skus.append(sku)
                if name:
                    item_names.append(name)

            if item_skus:
                self.memory.set(ctx.session_id, "last_items", item_skus, ttl)
            if item_names:
                self.memory.set(ctx.session_id, "last_product_names", item_names, ttl)

            # fallback category from first returned item if plan didn’t set one
            if not entities.get("category"):
                first_cat = None
                first = items[0] if items else {}
                if isinstance(first, dict):
                    first_cat = first.get("category") or first.get("category_id") or first.get("_category_id")
                if first_cat:
                    self.memory.set(ctx.session_id, "last_category", str(first_cat), ttl)

    # ---------------------------------------------------------
    # CRM
    # ---------------------------------------------------------
    def _log_crm(self, ctx: MessageContext, user_text: str, reply: Dict[str, Any]) -> None:
        lead = self.crm.upsert_lead(
            ctx.tenant,
            name=None,
            phone=(reply.get("entities") or {}).get("phone"),
            email=(reply.get("entities") or {}).get("email"),
            channel=ctx.channel,
            session_id=ctx.session_id,
            tags=[reply.get("intent")] if reply.get("intent") else None,
        )
        lead_id = lead.get("id") or lead.get("_id") or "unknown"

        self.crm.append_conversation(ctx.tenant, lead_id, {"from": "user", "text": user_text})
        self.crm.append_conversation(ctx.tenant, lead_id, {"from": "assistant", "text": reply.get("reply")})

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
        if not event_type:
            return
        if event_type in _KPI_EVENT_TYPES:
            return
        if not event_type.startswith("pipeline_"):
            return

        try:
            fn = getattr(self.analytics, "log_event", None)
            if not callable(fn):
                return

            meta_json = json.dumps(meta or {}, separators=(",", ":"), ensure_ascii=False)
            fn(
                tenant=ctx.tenant,
                channel=ctx.channel,
                session_id=ctx.session_id,
                event_type=event_type,
                lead_id=None,
                meta_json=meta_json,
            )
        except Exception:
            logger.exception("telemetry failed event_type=%s", event_type)
