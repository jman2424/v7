from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI
from service.api_usage import tracked_completion


# -------------------------------------------------------------------
# ENV CONFIG (respects your Render env vars)
# -------------------------------------------------------------------

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default

DEFAULT_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
DEFAULT_TEMPERATURE = _env_float("OPENAI_TEMPERATURE", 0.3)
DEFAULT_TIMEOUT = _env_int("OPENAI_TIMEOUT", 30)


SYSTEM_PROMPT = """
You are StoreBrainV7, the private planning brain for one business's sales agent.
You never speak to the customer. Return one strict JSON plan only.

Tenant-specific profile, catalogue, and policy data remain in the application and
are resolved after your plan. Never assume a fact that is not in the customer
message or session.

The runtime, not you, retrieves products, prices, stock, offers, delivery rules,
branches, FAQs, and contact details. Never invent any of those facts. For a named
or described offering, use SEARCH_PRODUCTS and put the useful customer wording in
product_name. For an open-ended need, prefer one focused discovery/search step over
a generic response. Ask one clarification only when no useful search or next step
can be selected.

Supported intents: greeting, search_product, browse_category, price_check,
check_delivery, store_info, faq, human_handoff, smalltalk, unknown.
Supported actions: GREET, ASK_SLOT, SEARCH_PRODUCTS, CHECK_DELIVERY, PRICE_CHECK,
STORE_INFO, FAQ_LOOKUP, HUMAN_HANDOFF, SMALLTALK_REPLY, DO_NOTHING.

Return JSON with intent, action, category, product_name, postcode, sku,
handoff_channel, needs_clarification, clarification_question, and meta. meta may
contain search_scope, item_level, search_tags, max_items, wants_chunking, and
primary_cut. Keep strings short. Do not include an answer, explanation, markdown,
or extra keys.
"""

_VALID_INTENTS = {
    "greeting",
    "search_product",
    "browse_category",
    "price_check",
    "check_delivery",
    "store_info",
    "faq",
    "human_handoff",
    "smalltalk",
    "unknown",
}
_VALID_ACTIONS = {
    "GREET",
    "ASK_SLOT",
    "SEARCH_PRODUCTS",
    "CHECK_DELIVERY",
    "PRICE_CHECK",
    "STORE_INFO",
    "FAQ_LOOKUP",
    "HUMAN_HANDOFF",
    "SMALLTALK_REPLY",
    "DO_NOTHING",
}


# -------------------------------------------------------------------
# CONFIG DATACLASS
# -------------------------------------------------------------------

@dataclass
class BrainConfig:
    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    timeout: int = DEFAULT_TIMEOUT
    system_prompt: str = SYSTEM_PROMPT


# -------------------------------------------------------------------
# BRAIN IMPLEMENTATION
# -------------------------------------------------------------------

class BrainV7:
    """
    Planning brain for V7.

    Key upgrades in this remake:
    - Uses env-driven model/temperature/timeout (matches your Render envs)
    - Fast-path for meta questions (e.g. "is this ai") -> smalltalk
    - Better "full <category> list" detection -> full_category + chunking
    """

    _RE_FULL_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)

    _RE_META_AI = re.compile(
        r"\b(are you ai|is this ai|are you a bot|are you real|human or bot|chatgpt)\b",
        re.I,
    )

    _FULL_LIST_PAT = re.compile(
        r"\b(full|all|entire|whole)\s+([a-z0-9 _-]{2,30})\s+(list|catalog|catalogue|range)\b",
        re.I,
    )

    def __init__(self, client: Optional[OpenAI] = None, config: Optional[BrainConfig] = None):
        self.config = config or BrainConfig()

        # Prefer injected client from deps.container
        self.client = client
        if self.client is None:
            # Fallback to env-based client if not provided
            api_key = os.getenv("OPENAI_API_KEY") or ""
            self.client = OpenAI(api_key=api_key) if api_key.strip() else None

    # --------------------------------------------------------------- #
    # PUBLIC: PLAN
    # --------------------------------------------------------------- #

    def plan(
        self,
        user_text: str,
        session: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        hints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        user_text = (user_text or "").strip()
        session = session or {}
        history = history or []
        hints = hints or {}

        if not user_text:
            return self._blank_plan(session)

        # 1) fast path
        fast = self._fast_path(user_text, session=session, hints=hints)
        if fast is not None:
            return fast

        # 2) LLM plan
        payload = {
            "message": user_text,
            "session": {
                "postcode": session.get("postcode"),
                "last_intent": session.get("last_intent"),
                "last_category": session.get("last_category"),
                "last_sku": session.get("last_sku"),
            },
        }

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.config.system_prompt},
            *history,
            {"role": "user", "content": json.dumps(payload)},
        ]

        if self.client is None:
            return self._fallback_plan(user_text, session, hints)

        try:
            completion = tracked_completion(self.client, purpose="planning",
                model=self.config.model,
                temperature=min(max(self.config.temperature, 0.0), 0.5),
                timeout=self.config.timeout,
                response_format={"type": "json_object"},
                messages=messages,
            )
            raw = completion.choices[0].message.content or ""
            return self._post_process(raw, user_text, session, hints)
        except Exception:
            return self._fallback_plan(user_text, session, hints)

    # --------------------------------------------------------------- #
    # FAST PATH
    # --------------------------------------------------------------- #

    def _fast_path(self, text: str, *, session: Dict[str, Any], hints: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        low = text.lower().strip()

        # Meta AI questions -> smalltalk (prevents catalog fallback)
        if self._RE_META_AI.search(low):
            return {
                "intent": "smalltalk",
                "action": "SMALLTALK_REPLY",
                "category": None,
                "product_name": None,
                "postcode": session.get("postcode"),
                "sku": session.get("last_sku"),
                "handoff_channel": None,
                "needs_clarification": False,
                "clarification_question": "",
                "meta": {
                    "is_greeting": False,
                    "is_goodbye": False,
                    "search_scope": "top_picks",
                    "item_level": False,
                    "search_tags": [],
                    "max_items": 0,
                    "wants_chunking": False,
                    "primary_cut": None,
                },
            }

        # Greetings
        if self._is_greeting(low):
            return {
                "intent": "greeting",
                "action": "GREET",
                "category": None,
                "product_name": None,
                "postcode": session.get("postcode"),
                "sku": session.get("last_sku"),
                "handoff_channel": None,
                "needs_clarification": False,
                "clarification_question": "",
                "meta": {
                    "is_greeting": True,
                    "is_goodbye": False,
                    "search_scope": "top_picks",
                    "item_level": False,
                    "search_tags": [],
                    "max_items": 8,
                    "wants_chunking": False,
                    "primary_cut": None,
                },
            }

        # Standalone delivery/postcode (quick extraction)
        pc = self._extract_postcode(text)
        if self._looks_like_delivery(low) and pc:
            return {
                "intent": "check_delivery",
                "action": "CHECK_DELIVERY",
                "category": None,
                "product_name": None,
                "postcode": pc,
                "sku": session.get("last_sku"),
                "handoff_channel": None,
                "needs_clarification": False,
                "clarification_question": "",
                "meta": {
                    "is_greeting": False,
                    "is_goodbye": False,
                    "search_scope": "top_picks",
                    "item_level": False,
                    "search_tags": [],
                    "max_items": 0,
                    "wants_chunking": False,
                    "primary_cut": None,
                },
            }

        # Category-based full-list requests.
        m = self._FULL_LIST_PAT.search(low)
        if m:
            maybe_cat = (m.group(2) or "").strip()
            cat = self._resolve_category_from_hints(maybe_cat, hints) or self._simple_norm_cat(maybe_cat)
            if cat:
                return {
                    "intent": "search_product",
                    "action": "SEARCH_PRODUCTS",
                    "category": cat,
                    "product_name": f"full {cat.replace('_', ' ')} list",
                    "postcode": session.get("postcode"),
                    "sku": session.get("last_sku"),
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": {
                        "is_greeting": False,
                        "is_goodbye": False,
                        "search_scope": "full_category",
                        "item_level": False,
                        "search_tags": [cat.replace("_", " ")],
                        "max_items": 40,
                        "wants_chunking": True,
                        "primary_cut": None,
                    },
                }

        return None

    # --------------------------------------------------------------- #
    # POST PROCESS (LLM JSON -> normalized plan)
    # --------------------------------------------------------------- #

    def _post_process(self, raw: str, user_text: str, session: Dict[str, Any], hints: Dict[str, Any]) -> Dict[str, Any]:
        try:
            data = json.loads(raw)
        except Exception:
            return self._blank_plan(session)

        intent = str(data.get("intent") or "unknown").strip().lower()
        action = str(data.get("action") or "DO_NOTHING").strip().upper()
        if intent not in _VALID_INTENTS or action not in _VALID_ACTIONS:
            return self._fallback_plan(user_text, session, hints)

        raw_cat = data.get("category")
        product_name = data.get("product_name")
        if not isinstance(product_name, str):
            product_name = None
        elif len(product_name) > 240:
            product_name = product_name[:240].strip()
        postcode = data.get("postcode") or session.get("postcode") or self._extract_postcode(user_text)
        sku = data.get("sku") or session.get("last_sku")
        handoff_channel = data.get("handoff_channel")
        if not isinstance(handoff_channel, str):
            handoff_channel = None
        elif len(handoff_channel) > 80:
            handoff_channel = handoff_channel[:80].strip()

        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = str(data.get("clarification_question") or "").strip()[:240]

        meta_in = data.get("meta") or {}
        if not isinstance(meta_in, dict):
            meta_in = {}
        try:
            max_items = int(meta_in.get("max_items", 8) or 8)
        except (TypeError, ValueError):
            max_items = 8

        meta = {
            "is_greeting": bool(meta_in.get("is_greeting", False)),
            "is_goodbye": bool(meta_in.get("is_goodbye", False)),
            "search_scope": meta_in.get("search_scope") or "top_picks",
            "item_level": bool(meta_in.get("item_level", False)),
            "search_tags": meta_in.get("search_tags") if isinstance(meta_in.get("search_tags"), list) else [],
            "max_items": min(max(max_items, 1), 20),
            "wants_chunking": bool(meta_in.get("wants_chunking", False)),
            "primary_cut": meta_in.get("primary_cut"),
        }

        # Category resolution using hints
        cat = None
        if isinstance(raw_cat, str) and raw_cat.strip():
            cat = self._resolve_category_from_hints(raw_cat, hints) or self._simple_norm_cat(raw_cat)

        # Delivery intent must have postcode
        if intent == "check_delivery" and not postcode:
            action = "ASK_SLOT"
            needs_clarification = True
            clarification_question = "What’s your postcode (for example: E1 6AN)?"

        return {
            "intent": intent,
            "action": action,
            "category": cat,
            "product_name": product_name,
            "postcode": postcode,
            "sku": sku,
            "handoff_channel": handoff_channel,
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question,
            "meta": meta,
        }

    def _fallback_plan(self, user_text: str, session: Dict[str, Any], hints: Dict[str, Any]) -> Dict[str, Any]:
        """A useful local plan when no model is configured or a call fails."""
        text = (user_text or "").strip()
        low = text.casefold()
        context = hints.get("business") if isinstance(hints.get("business"), dict) else {}
        categories = hints.get("categories") if isinstance(hints.get("categories"), list) else []
        category = self._matching_category(low, categories)

        if any(term in low for term in ("quote", "consultation", "appointment", "call back", "speak to")):
            plan = self._blank_plan(session)
            plan.update({"intent": "human_handoff", "action": "HUMAN_HANDOFF"})
            return plan
        if any(term in low for term in ("delivery", "deliver", "shipping", "postcode")):
            plan = self._blank_plan(session)
            plan.update({"intent": "check_delivery", "action": "CHECK_DELIVERY"})
            if not plan.get("postcode"):
                plan["needs_clarification"] = True
                plan["clarification_question"] = "What is your postcode so I can check the available options?"
            return plan
        if any(term in low for term in ("price", "cost", "how much")):
            plan = self._blank_plan(session)
            plan.update({"intent": "price_check", "action": "PRICE_CHECK", "product_name": text[:240]})
            return plan
        if category or any(term in low for term in ("need", "looking", "want", "recommend", "help me", "interested", "options", "browse", "show")):
            plan = self._blank_plan(session)
            plan.update(
                {
                    "intent": "browse_category" if category else "search_product",
                    "action": "SEARCH_PRODUCTS",
                    "category": category,
                    "product_name": text[:240],
                    "meta": {
                        **plan["meta"],
                        "search_scope": "top_picks",
                        "max_items": 8,
                    },
                }
            )
            return plan

        plan = self._blank_plan(session)
        plan["needs_clarification"] = True
        plan["clarification_question"] = self._discovery_question(context)
        return plan

    @staticmethod
    def _matching_category(text: str, categories: List[Any]) -> Optional[str]:
        for raw in categories:
            if isinstance(raw, str):
                name = raw.strip()
                if name and name.casefold() in text:
                    return BrainV7._simple_norm_cat(name)
                continue
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            category_id = str(raw.get("id") or "").strip()
            if name and name.casefold() in text:
                return category_id or BrainV7._simple_norm_cat(name)
        return None

    @staticmethod
    def _discovery_question(context: Dict[str, Any]) -> str:
        categories = context.get("categories") if isinstance(context.get("categories"), list) else []
        names = [
            str(item.get("name") or "").strip()
            if isinstance(item, dict)
            else str(item).strip()
            for item in categories
        ]
        names = [name for name in names if name][:3]
        if names:
            return f"What are you looking for - {', '.join(names)}, or something else?"
        return "What would you like help with today?"


    # --------------------------------------------------------------- #
    # BASELINE PLAN
    # --------------------------------------------------------------- #

    def _blank_plan(self, session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "intent": "unknown",
            "action": "DO_NOTHING",
            "category": None,
            "product_name": None,
            "postcode": session.get("postcode"),
            "sku": session.get("last_sku"),
            "handoff_channel": None,
            "needs_clarification": False,
            "clarification_question": "",
            "meta": {
                "is_greeting": False,
                "is_goodbye": False,
                "search_scope": "top_picks",
                "item_level": False,
                "search_tags": [],
                "max_items": 8,
                "wants_chunking": False,
                "primary_cut": None,
            },
        }

    # --------------------------------------------------------------- #
    # HELPERS
    # --------------------------------------------------------------- #

    @staticmethod
    def _is_greeting(low: str) -> bool:
        return bool(re.search(r"\b(hi|hello|hey|salam|salaam|assalamu alaikum|assalamualaikum)\b", low))

    @staticmethod
    def _looks_like_delivery(low: str) -> bool:
        return any(w in low for w in ["deliver", "delivery", "postcode", "post code", "shipping", "ship", "min order", "minimum order"])

    @classmethod
    def _extract_postcode(cls, text: str) -> Optional[str]:
        m = cls._RE_FULL_POSTCODE.search((text or "").upper())
        if not m:
            return None
        return f"{m.group(1)} {m.group(2)}"

    @staticmethod
    def _simple_norm_cat(raw: str) -> Optional[str]:
        s = (raw or "").strip().lower()
        if not s:
            return None
        s = re.sub(r"[^a-z0-9\s_-]+", " ", s)
        s = re.sub(r"\s+", "_", s).strip("_")
        return s or None

    @staticmethod
    def _resolve_category_from_hints(raw_cat: str, hints: Dict[str, Any]) -> Optional[str]:
        # Use catalog categories if present
        cats = hints.get("categories") or []
        wanted = (raw_cat or "").strip().lower()
        if not wanted:
            return None

        for c in cats:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id") or "").strip()
            nm = str(c.get("name") or "").strip().lower()
            if nm and wanted in nm:
                return cid or BrainV7._simple_norm_cat(nm)
            if cid and wanted == cid.strip().lower():
                return cid
        return None
