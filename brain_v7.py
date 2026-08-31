from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI


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
You are StoreBrainV7 — the PLANNING BRAIN for a halal meat shop assistant.

You NEVER talk to the user directly.
You ONLY output a JSON PLAN that tells the assistant WHAT TO DO NEXT.

You must:
- classify user intent correctly
- choose the right ACTION
- fill slots: category, product_name, postcode, sku, handoff_channel
- only ask clarification when truly necessary

INTENTS:
"greeting"
"search_product"
"browse_category"
"price_check"
"check_delivery"
"store_info"
"faq"
"human_handoff"
"smalltalk"
"unknown"

ACTIONS:
"GREET"
"ASK_SLOT"
"SEARCH_PRODUCTS"
"CHECK_DELIVERY"
"PRICE_CHECK"
"STORE_INFO"
"FAQ_LOOKUP"
"HUMAN_HANDOFF"
"SMALLTALK_REPLY"
"DO_NOTHING"

OUTPUT MUST BE STRICT JSON OBJECT with the required fields as previously defined.
"""


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

    # High-signal product cuts
    CUT_KEYWORDS = {
        "wings", "wing",
        "thigh", "thighs",
        "breast", "breasts",
        "drumstick", "drumsticks",
        "mince", "burger", "burgers",
        "steak", "steaks",
        "chop", "chops",
        "rib", "ribs",
        "brain", "brains",
        "liver",
        "kidney", "kidneys",
        "feet", "paya",
        "nugget", "nuggets",
        "kebab", "kebabs",
        "fillet", "fillets",
    }

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
            "hints": hints,
        }

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.config.system_prompt},
            *history,
            {"role": "user", "content": json.dumps(payload)},
        ]

        if self.client is None:
            plan = self._blank_plan(session)
            plan["needs_clarification"] = True
            plan["clarification_question"] = "Tell me what product, delivery area, or store info you need."
            return plan

        completion = self.client.chat.completions.create(
            model=self.config.model,
            temperature=self.config.temperature,
            timeout=self.config.timeout,
            response_format={"type": "json_object"},
            messages=messages,
        )
        raw = completion.choices[0].message.content or ""
        return self._post_process(raw, user_text, session, hints)

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

        # "full chicken list" / "all lamb catalog" (category-based full list)
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

        intent = (data.get("intent") or "unknown").strip()
        action = (data.get("action") or "DO_NOTHING").strip()

        raw_cat = data.get("category")
        product_name = data.get("product_name")
        postcode = data.get("postcode") or session.get("postcode") or self._extract_postcode(user_text)
        sku = data.get("sku") or session.get("last_sku")
        handoff_channel = data.get("handoff_channel")

        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = data.get("clarification_question") or ""

        meta_in = data.get("meta") or {}
        if not isinstance(meta_in, dict):
            meta_in = {}

        meta = {
            "is_greeting": bool(meta_in.get("is_greeting", False)),
            "is_goodbye": bool(meta_in.get("is_goodbye", False)),
            "search_scope": meta_in.get("search_scope") or "top_picks",
            "item_level": bool(meta_in.get("item_level", False)),
            "search_tags": meta_in.get("search_tags") if isinstance(meta_in.get("search_tags"), list) else [],
            "max_items": int(meta_in.get("max_items", 8) or 8),
            "wants_chunking": bool(meta_in.get("wants_chunking", False)),
            "primary_cut": meta_in.get("primary_cut"),
        }

        # Category resolution using hints
        cat = None
        if isinstance(raw_cat, str) and raw_cat.strip():
            cat = self._resolve_category_from_hints(raw_cat, hints) or self._simple_norm_cat(raw_cat)

        # Item-level cut enforcement (wings/breast/mince etc.)
        low = user_text.lower()
        detected_cut = None
        for w in self.CUT_KEYWORDS:
            if re.search(rf"\b{re.escape(w)}\b", low):
                detected_cut = w
                break
        if detected_cut:
            intent = "search_product"
            action = "SEARCH_PRODUCTS"
            meta["item_level"] = True
            meta["search_scope"] = "item_list" if meta["search_scope"] == "top_picks" else meta["search_scope"]
            meta["primary_cut"] = detected_cut
            if detected_cut not in meta["search_tags"]:
                meta["search_tags"].append(detected_cut)
            if not product_name:
                product_name = user_text

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
