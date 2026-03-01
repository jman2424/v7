# service/message_handler.py
"""
MASTER MESSAGE HANDLER (V7-first, safe-dispatch)

Key points:
- This file is NOT the AI brain. It is the dispatcher + safety/UX guard + validation.
- It should never pretend the system is broken when user simply typed nonsense.
- It should not block postcodes or "nearest branch" requests.
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

# Recognize “nearest branch/store” requests (typos included)
_NEAREST_BRANCH_PAT = re.compile(
    r"\b(nearest|closest|nearby)\s+(branch|store|shop)\b"
    r"|\bmy\s+nearest\s+(branch|store|shop)\b"
    r"|\bnearst\s+(branch|store|shop)\b",
    re.I,
)

# Detect full postcode anywhere, spaced or not
_POSTCODE_FULL_IN_TEXT = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)

# Outward-only standalone: E7 / SW1A / N4 etc.
_POSTCODE_OUTWARD_STANDALONE = re.compile(r"^\s*([A-Z]{1,2}\d{1,2}[A-Z]?)\s*$", re.I)

# Users asking for a full category list
_FULL_LIST_PAT = re.compile(
    r"\b(full|all|everything|entire|whole)\b.*\b(chicken|lamb|beef|grocer(?:y|ies)|frozen|marinated)\b",
    re.I,
)

# Some common “test” words that should not trigger a “system broken” message
_TEST_NOISE = {
    "test", "tester", "testing", "demo", "dmo", "tst",
    "test1", "test2", "test3",
    "hello", "hi", "hey", "yo", "there", "sup",
}


def _collapse_spaces(s: str) -> str:
    return _RE_MULTI_SPACE.sub(" ", (s or "")).strip()


def _extract_postcode_anywhere(text: str) -> Optional[str]:
    """
    Extract a postcode from inside a longer message, then normalize spacing.
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

    compact = re.sub(r"[^A-Z0-9]", "", s)
    pc = normalize_postcode(compact)
    return pc


def _maybe_normalize_postcode_for_dispatch(user_text: str) -> str:
    """
    Normalize standalone postcode inputs BEFORE guard/dispatch.
    """
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
    """
    Detect low-signal messages that should not trigger a “system broken” fallback.
    """
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in _TEST_NOISE:
        return True

    # single short word with no digits and no strong keyword
    if len(t) <= 7 and t.isalpha():
        # if it's not a known category or common product keyword, treat as noise-ish
        known = {"chicken", "lamb", "beef", "groceries", "grocery", "frozen", "marinated", "delivery", "postcode"}
        if t not in known:
            return True

    return False


def _category_from_full_list(text: str) -> Optional[str]:
    """
    If user says "full chicken list" / "all lamb" etc, extract the category word.
    """
    if not text:
        return None
    m = _FULL_LIST_PAT.search(text)
    if not m:
        return None
    s = m.group(0).lower()
    if "chicken" in s:
        return "chicken"
    if "lamb" in s:
        return "lamb"
    if "beef" in s:
        return "beef"
    if "grocer" in s:
        return "groceries"
    if "frozen" in s:
        return "frozen_meats"
    if "marinated" in s:
        return "marinated_meats"
    return None


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
                ctx.tenant, ctx.session_id, ctx.channel, mode, rid, guarded.get("intent"), user_text[:120],
            )
            self._telemetry(
                ctx,
                event_type="pipeline_turn",
                meta={"mode": mode, "rid": rid, "intent": guarded.get("intent"), "ok": True, "guarded": True, "channel": ctx.channel},
            )
            return guarded

        logger.info(
            "DISPATCH tenant=%s session=%s channel=%s mode=%s rid=%s text=%r",
            ctx.tenant, ctx.session_id, ctx.channel, mode, rid, user_text[:120],
        )

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
            ctx.tenant, ctx.session_id, mode, rid, reply.get("intent"), sorted(list(reply.keys())),
        )

        # ---------------- VALIDATION ----------------
        reply = self._validate_reply(reply, user_text, ctx, sess)

        # ---------------- PERSIST ----------------
        self._save_session(ctx, sess, reply)
        self._log_crm(ctx, user_text, reply)

        self._telemetry(ctx, event_type="pipeline_out", meta={"mode": mode, "rid": rid, "intent": reply.get("intent"), "reply_len": len((reply.get("reply") or ""))})
        self._telemetry(ctx, event_type="pipeline_turn", meta={"mode": mode, "rid": rid, "intent": reply.get("intent"), "ok": True, "channel": ctx.channel})

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

        # Never guard-block postcodes or postcode-containing messages.
        if _is_postcode_like(t) or _POSTCODE_FULL_IN_TEXT.search(t.upper()):
            return None

        # Never block “nearest branch/store”
        if _NEAREST_BRANCH_PAT.search(t):
            return None

        # If user asked "full chicken list" etc, do NOT guard it.
        if _FULL_LIST_PAT.search(t):
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

        # Random short gibberish
        letters = sum(ch.isalpha() for ch in t)
        digits = sum(ch.isdigit() for ch in t)
        looks_like_short_code = (len(t) <= 8 and letters >= 2 and digits >= 2 and " " not in t)
        looks_like_gibberish = (len(t) <= 5 and _RE_HAS_ALPHA.search(t) and digits == 0 and " " not in t and not _RE_WORD3.search(t))

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
    def _validate_reply(self, reply: Dict[str, Any], user_text: str, ctx: MessageContext, sess: Dict[str, Any]) -> Dict[str, Any]:
        """
        IMPORTANT change:
        - Don't say "having trouble pulling products" just because search returned 0 items.
        - Use a clarifier when the user's message is low-signal or "test/demo".
        - If user requested "full chicken list", nudge to a category browse question instead of failure.
        """
        intent = (reply.get("intent") or "").strip()
        facts = reply.get("facts") or {}
        items = facts.get("items") or []
        text = (user_text or "").strip()

        # If user typed "full chicken list" etc and V7 didn't return items, guide them cleanly.
        cat = _category_from_full_list(text)
        if cat and not items:
            pretty = cat.replace("_", " ")
            return {
                "reply": (
                    f"Got it — **full {pretty} list**.\n\n"
                    "Before I list everything, tell me what you want to see:\n"
                    "• wings\n"
                    "• breast\n"
                    "• thighs\n"
                    "• drumsticks\n"
                    "• whole chicken\n\n"
                    "Or say: **cheap chicken** / **BBQ chicken**."
                ),
                "intent": "system_force_browse",
                "resolved": False,
                "facts": {"force_category": cat},
                "entities": {"category": cat},
            }

        # Bare-category handling (existing behaviour but kept)
        lower = text.lower()
        known_category_words = {
            "chicken", "lamb", "beef",
            "groceries", "grocery",
            "frozen", "frozen meats", "frozen_meats",
            "marinated", "marinated meats", "marinated_meats",
        }
        looks_like_bare_category = (len(lower.split()) <= 2) and (lower in known_category_words)

        if looks_like_bare_category and not items:
            logger.warning(
                "PIPELINE WARNING: bare-category but no items | text=%r intent=%s tenant=%s session=%s",
                user_text, intent, ctx.tenant, ctx.session_id,
            )
            return {
                "reply": (
                    f"Got it — **{lower}**.\n\n"
                    "Tell me what you want and I’ll pull options:\n"
                    "• wings / thighs / breast\n"
                    "• mince / chops / ribs\n"
                    "• or ask: **cheapest**, **best for BBQ**, **family pack**"
                ),
                "intent": "system_force_browse",
                "resolved": False,
                "facts": {"force_category": lower},
                "entities": {"category": lower},
            }

        # If intent *expects* items but none returned, DO NOT claim system is broken.
        requires_items = intent in {"browse_category", "search_product", "related_products", "price_check"}
        if requires_items and not items:
            # If user typed low-signal / test words, treat as clarifier not failure.
            if _looks_like_noise(text):
                return {
                    "reply": (
                        "Tell me what you want to do:\n"
                        "• search products (e.g. **chicken wings**)\n"
                        "• check delivery (e.g. **E7 9QS**)\n"
                        "• nearest branch (type **nearest branch**)\n"
                        "• or ask for a category (e.g. **chicken**)"
                    ),
                    "intent": "system_clarify",
                    "resolved": False,
                    "facts": {"reason": "low_signal_input"},
                    "entities": {},
                }

            # Otherwise it's a normal “no results” case.
            q = (reply.get("entities") or {}).get("query") or text
            return {
                "reply": (
                    f"I couldn’t find matches for **{q}**.\n\n"
                    "Try one of these:\n"
                    "• **chicken wings**\n"
                    "• **lamb chops**\n"
                    "• **beef mince**\n"
                    "• **cheapest chicken**"
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
