# service/message_handler.py
"""
MASTER MESSAGE HANDLER (V7-first, safe-dispatch)

RULES (critical):
- NEVER writes msg_in/msg_out/error analytics here.
  Those belong ONLY to transport boundaries:
    - routes/webchat_routes.py
    - routes/whatsapp_routes.py

- This handler may write TELEMETRY only:
    pipeline_in / pipeline_out / pipeline_turn
  Telemetry must never crash the bot.

Key upgrades in this remake:
- Postcodes are AUTO-NORMALIZED:
    * full:  "E79QS" -> "E7 9QS"
    * spaced:"E7 9QS"-> "E7 9QS"
    * full:  "SW1A1AA"->"SW1A 1AA"
    * outward-only: "SW1A" stays "SW1A"
    * embedded: "delivery to E79QS" extracts and stores session postcode downstream
- Guards will NOT block postcode-ish inputs.
- “nearest branch” is treated as a valid intent-like input (never fails as nonsense).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from handlers.handler_v5 import MessageHandlerV5
from handlers.handler_v6 import MessageHandlerV6
from handlers.handler_v7 import MessageHandlerV7

from service.validators import normalize_postcode

from . import DEFAULT_SESSION_TTL, HandlerDeps

logger = logging.getLogger("MessageHandler")

# KPI event types that must never be emitted from here
_KPI_EVENT_TYPES = {"msg_in", "msg_out", "error"}

# --- pre-dispatch guards ---
_RE_ONLY_SYMBOLS = re.compile(r"^[^A-Za-z0-9]+$")
_RE_HAS_ALPHA = re.compile(r"[A-Za-z]")
_RE_WORD3 = re.compile(r"[A-Za-z]{3,}")
_RE_MULTI_SPACE = re.compile(r"\s+")

# Common “catalog dump” phrases users try
_CATALOG_PHRASES = {
    "full catalog",
    "full catalogue",
    "catalog",
    "catalogue",
    "everything",
    "all products",
    "all items",
    "show me everything",
    "show everything",
}

# Recognize “nearest branch/store” requests (typos included)
_NEAREST_BRANCH_PAT = re.compile(
    r"\b(nearest|closest|nearby)\s+(branch|store|shop)\b"
    r"|\bmy\s+nearest\s+(branch|store|shop)\b"
    r"|\bnearst\s+(branch|store|shop)\b",
    re.I,
)

# Detect full postcode anywhere, spaced or not (normalize later)
# This is intentionally pragmatic, not perfect UK spec.
_POSTCODE_FULL_IN_TEXT = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)

# Outward-only standalone: E7 / SW1A / N4 etc.
_POSTCODE_OUTWARD_STANDALONE = re.compile(r"^\s*([A-Z]{1,2}\d{1,2}[A-Z]?)\s*$", re.I)


def _collapse_spaces(s: str) -> str:
    return _RE_MULTI_SPACE.sub(" ", (s or "")).strip()


def _extract_postcode_anywhere(text: str) -> Optional[str]:
    """
    Extract a postcode from inside a longer message, then normalize spacing.
    Examples:
      "delivery to E79QS" -> "E7 9QS"
      "postcode is sw1a1aa" -> "SW1A 1AA"
    """
    if not text:
        return None
    s = text.strip().upper()

    m = _POSTCODE_FULL_IN_TEXT.search(s)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    # outward-only only if the whole message is basically outward-only
    m2 = _POSTCODE_OUTWARD_STANDALONE.match(s)
    if m2:
        return m2.group(1)

    # last resort: compact and try normalize_postcode (your validators may accept more)
    compact = re.sub(r"[^A-Z0-9]", "", s)
    pc = normalize_postcode(compact)
    return pc


def _maybe_normalize_postcode_for_dispatch(user_text: str) -> str:
    """
    Always attempt to normalize if a postcode is present.
    - If message is just postcode, replace the whole message with normalized postcode.
    - If postcode appears inside text, keep original text (V7 will extract too),
      but we can optionally normalize *standalone* only to avoid messing intent text.
    """
    t = (user_text or "").strip()
    if not t:
        return t

    # Standalone normalize (most important for "E79QS")
    pc = normalize_postcode(t)
    if pc:
        return pc

    # If user typed something like E79QS without space, try insert space before last 3 and validate
    # (Works for common cases; validators does the final accept.)
    compact = re.sub(r"\s+", "", t).upper()
    if " " not in compact and 5 <= len(compact) <= 8:
        suggestion = f"{compact[:-3]} {compact[-3:]}"
        pc2 = normalize_postcode(suggestion)
        if pc2:
            return pc2

    return t


def _is_postcode_like(text: str) -> bool:
    """
    A safe check to prevent guards from blocking postcodes.
    Uses validators first, then a light heuristic.
    """
    if not text:
        return False

    if normalize_postcode(text):
        return True

    # If a postcode exists anywhere inside text, treat as postcode-like.
    if _POSTCODE_FULL_IN_TEXT.search(text.upper()):
        return True

    s = re.sub(r"\s+", "", text.strip().upper())
    if len(s) < 4 or len(s) > 8:
        return False
    letters = sum(ch.isalpha() for ch in s)
    digits = sum(ch.isdigit() for ch in s)
    return letters >= 2 and digits >= 1


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

        # ✅ Normalize standalone postcode inputs BEFORE guard/dispatch.
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

        # ---------------- PRE-DISPATCH GUARD ----------------
        guarded = self._guard_input(user_text, sess=sess)
        if guarded is not None:
            logger.info(
                "DISPATCH_GUARDED tenant=%s session=%s channel=%s mode=%s rid=%s intent=%s text=%r",
                ctx.tenant,
                ctx.session_id,
                ctx.channel,
                mode,
                rid,
                guarded.get("intent"),
                user_text[:120],
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
            ctx.tenant,
            ctx.session_id,
            ctx.channel,
            mode,
            rid,
            user_text[:120],
        )

        # TELEMETRY ONLY (never KPI)
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

        # TELEMETRY ONLY (never KPI)
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
    # PRE-DISPATCH INPUT GUARD
    # ---------------------------------------------------------
    def _guard_input(self, user_text: str, *, sess: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        t = (user_text or "").strip()
        if not t:
            return {
                "reply": "Send what you want (e.g. chicken wings, lamb chops, delivery to E1 6AN).",
                "intent": "system_empty",
                "resolved": False,
                "facts": {},
                "entities": {},
            }

        # ✅ Never guard-block postcodes or postcode-containing messages.
        # Let V7 do the right thing.
        if _is_postcode_like(t):
            return None

        # ✅ Never block “nearest branch/store” requests (even without postcode),
        # because V7 will ask for postcode if needed.
        if _NEAREST_BRANCH_PAT.search(t):
            return None

        tl = _collapse_spaces(t).lower()

        # Hard noise like "!!!" or "&*("
        if _RE_ONLY_SYMBOLS.match(t):
            return {
                "reply": "Type what you’re after (e.g. chicken wings / lamb chops) or a postcode for delivery.",
                "intent": "system_clarify",
                "resolved": False,
                "facts": {"reason": "symbols_only"},
                "entities": {},
            }

        # “full catalog” requests -> don’t pretend it’s a product search
        if tl in _CATALOG_PHRASES:
            return {
                "reply": (
                    "I can’t dump the full catalogue in one go.\n\n"
                    "Pick a section and I’ll show it:\n"
                    "• chicken\n"
                    "• lamb\n"
                    "• beef\n"
                    "• groceries\n"
                    "• frozen meats\n"
                    "• marinated meats\n\n"
                    "Or tell me what you’re cooking (BBQ / curry / burgers)."
                ),
                "intent": "system_catalog_hint",
                "resolved": True,
                "facts": {"reason": "catalog_request"},
                "entities": {},
            }

        # Random short codes / gibberish (but we already exempted postcodes above)
        letters = sum(ch.isalpha() for ch in t)
        digits = sum(ch.isdigit() for ch in t)

        looks_like_short_code = (len(t) <= 8 and letters >= 2 and digits >= 2 and " " not in t)
        looks_like_gibberish = (
            len(t) <= 5
            and _RE_HAS_ALPHA.search(t)
            and digits == 0
            and " " not in t
            and not _RE_WORD3.search(t)
        )

        if looks_like_short_code or looks_like_gibberish:
            return {
                "reply": (
                    "I didn’t catch that.\n\n"
                    "Send either:\n"
                    "• a product (e.g. **chicken wings**, **lamb chops**)\n"
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

        # Optional: analytics lead helpers (NOT KPIs)
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
        Allowed: pipeline_in / pipeline_out / pipeline_turn (only).
        Must never crash the bot.
        """
        if not event_type:
            return

        # Hard block KPI types
        if event_type in _KPI_EVENT_TYPES:
            return

        # Only allow pipeline_* events from this layer
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
