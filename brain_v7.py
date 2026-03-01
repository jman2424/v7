# brain_v7.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

DEFAULT_MODEL = "gpt-4.1-mini"

SYSTEM_PROMPT = """
You are StoreBrainV7 — the PLANNING BRAIN for a halal meat shop assistant.

You NEVER talk to the user directly.
You NEVER write long answers.
You ONLY output a JSON PLAN that tells the assistant WHAT TO DO NEXT.

The renderer will turn your plan into nice wording.
Your job is to think like a smart human sales assistant:
- understand what the customer really wants
- decide the right ACTION
- fill useful slots (category, product_name, postcode, sku, handoff_channel)
- only ask clarifying questions when genuinely needed.

Return ONLY valid JSON (no markdown).

Required shape:

{
  "intent": "...",
  "action": "...",
  "category": "... or null",
  "product_name": "... or null",
  "postcode": "... or null",
  "sku": "... or null",
  "handoff_channel": "... or null",
  "needs_clarification": boolean,
  "clarification_question": "string",
  "meta": {
    "is_greeting": boolean,
    "is_goodbye": boolean,
    "search_scope": "top_picks" | "item_list" | "full_category" | "full_store",
    "item_level": boolean,
    "search_tags": [string, ...],
    "max_items": integer,
    "wants_chunking": boolean,
    "primary_cut": "string or null"
  }
}
"""

# -------------------------------------------------------------------
# CONFIG DATACLASS
# -------------------------------------------------------------------


@dataclass
class BrainConfig:
    model: str = DEFAULT_MODEL
    system_prompt: str = SYSTEM_PROMPT


# -------------------------------------------------------------------
# BRAIN IMPLEMENTATION
# -------------------------------------------------------------------


class BrainV7:
    """
    StoreBrainV7 — planning-only brain for V7.

    Key upgrades in this remake:
    - Standalone postcode (e.g. "E79QS" / "SW1A 1AA") ALWAYS triggers check_delivery.
      (Even if user didn't type "delivery")
    - Better "full <category> list" behavior:
      - If category is detectable => search_scope=full_category, wants_chunking=True
      - If no category => search_scope=full_store, wants_chunking=True
    - Cut keywords produce item_level planning (wings/mince/brain/etc.)
    - Dynamic category resolution using hints (categories + synonyms)
    """

    CUT_KEYWORDS = {
        "wing", "wings",
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

    # UK-ish: inward part is digit + 2 letters
    _PC_FULL = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", re.I)
    _PC_OUTWARD_ONLY = re.compile(r"^\s*([A-Z]{1,2}\d{1,2}[A-Z]?)\s*$", re.I)

    def __init__(self, client: Optional[OpenAI] = None, config: Optional[BrainConfig] = None):
        self.client = client or OpenAI()
        self.config = config or BrainConfig()

    # --------------------------------------------------------------- #
    # PUBLIC: PLAN                                                    #
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
        fast = self._fast_path(user_text, session, hints)
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

        completion = self.client.chat.completions.create(
            model=self.config.model,
            response_format={"type": "json_object"},
            messages=messages,
        )
        raw = completion.choices[0].message.content or ""
        return self._post_process(raw, user_text, session, hints)

    # --------------------------------------------------------------- #
    # FAST PATH                                                       #
    # --------------------------------------------------------------- #

    def _fast_path(self, text: str, session: Dict[str, Any], hints: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        low = text.lower().strip()

        # A) standalone postcode => ALWAYS delivery check
        pc_only = self._extract_postcode_anywhere(text, allow_outward_only=True)
        if pc_only and self._looks_like_just_postcode(text):
            return self._plan_delivery(pc_only, session)

        # B) greetings
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
                "meta": self._meta_base(is_greeting=True),
            }

        # C) explicit delivery language (with or without postcode)
        if self._looks_like_delivery(low):
            pc = self._extract_postcode_anywhere(text, allow_outward_only=False) or session.get("postcode")
            if pc:
                return self._plan_delivery(pc, session)
            return {
                "intent": "check_delivery",
                "action": "ASK_SLOT",
                "category": None,
                "product_name": None,
                "postcode": session.get("postcode"),
                "sku": session.get("last_sku"),
                "handoff_channel": None,
                "needs_clarification": True,
                "clarification_question": "What’s your postcode (for example: E1 6AN)?",
                "meta": self._meta_base(),
            }

        # D) "more" / "more options"
        if low in {"more", "more options", "all options", "anything else", "show me more", "more please"}:
            last_cat = session.get("last_category")
            last_intent = session.get("last_intent")
            if last_cat:
                return {
                    "intent": "search_product",
                    "action": "SEARCH_PRODUCTS",
                    "category": last_cat,
                    "product_name": f"more options in {last_cat}",
                    "postcode": session.get("postcode"),
                    "sku": session.get("last_sku"),
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": self._meta_base(search_scope="top_picks", max_items=8),
                }
            if last_intent in {"search_product", "browse_category"}:
                return {
                    "intent": "search_product",
                    "action": "SEARCH_PRODUCTS",
                    "category": None,
                    "product_name": "more options similar to last query",
                    "postcode": session.get("postcode"),
                    "sku": session.get("last_sku"),
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": self._meta_base(search_scope="top_picks", max_items=8),
                }

        # E) Human handoff keywords
        if re.search(r"\b(human|real person|call you|call the shop|speak to someone|agent)\b", low):
            return {
                "intent": "human_handoff",
                "action": "HUMAN_HANDOFF",
                "category": None,
                "product_name": None,
                "postcode": session.get("postcode"),
                "sku": session.get("last_sku"),
                "handoff_channel": "phone",
                "needs_clarification": False,
                "clarification_question": "",
                "meta": self._meta_base(),
            }

        # F) If message CONTAINS a postcode anywhere, treat as delivery check
        # (covers: "E79QS", "postcode is SW1A1AA", "deliver to E7 9QS")
        pc_any = self._extract_postcode_anywhere(text, allow_outward_only=False)
        if pc_any:
            return self._plan_delivery(pc_any, session)

        # G) Full catalog-ish keywords are better handled after category resolution (post-process),
        # but we can early-hint if user says "full chicken list" etc.
        if any(k in low for k in ("full", "all", "everything", "entire", "whole", "catalog", "catalogue", "list")):
            # try resolve category from hints quickly
            cat = self._resolve_category(None, text, session, hints)
            if cat:
                return {
                    "intent": "search_product",
                    "action": "SEARCH_PRODUCTS",
                    "category": cat,
                    "product_name": f"full {cat.replace('_', ' ')} catalog",
                    "postcode": session.get("postcode"),
                    "sku": session.get("last_sku"),
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": self._meta_base(search_scope="full_category", max_items=30, wants_chunking=True),
                }

        return None

    # --------------------------------------------------------------- #
    # CATEGORY MAP (dynamic from hints)                               #
    # --------------------------------------------------------------- #

    @staticmethod
    def _norm_cat_key(raw: str) -> str:
        raw = (raw or "").strip().lower()
        raw = re.sub(r"\s+", "_", raw)
        return raw

    @staticmethod
    def _clean_phrase(label: str) -> str:
        label = (label or "").lower()
        label = re.sub(r"[^a-z0-9\s]+", " ", label)
        label = re.sub(r"\s+", " ", label).strip()
        return label

    @classmethod
    def _add_label_variants(cls, mapping: Dict[str, str], label: str, key: str) -> None:
        base = cls._clean_phrase(label)
        if not base:
            return
        mapping.setdefault(base, key)

        parts = base.split()
        if not parts:
            return
        last = parts[-1]
        if last.endswith("s"):
            singular = last[:-1]
            if singular:
                mapping.setdefault(" ".join(parts[:-1] + [singular]), key)
        else:
            plural = last + "s"
            mapping.setdefault(" ".join(parts[:-1] + [plural]), key)

    def _build_category_mapping(self, hints: Dict[str, Any]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}

        categories = hints.get("categories") or []
        cat_syn = hints.get("category_synonyms") or hints.get("synonyms") or {}

        for c in categories:
            cid = str(c.get("id") or "").strip()
            cname = str(c.get("name") or "").strip()
            if not cid and not cname:
                continue
            key_source = cid or cname
            key = self._norm_cat_key(key_source)
            if cid:
                self._add_label_variants(mapping, cid, key)
            if cname:
                self._add_label_variants(mapping, cname, key)

        if isinstance(cat_syn, dict):
            for base, syns in cat_syn.items():
                base_key = self._norm_cat_key(str(base))
                self._add_label_variants(mapping, str(base), base_key)
                if isinstance(syns, list):
                    for s in syns:
                        self._add_label_variants(mapping, str(s), base_key)

        return mapping

    def _resolve_category(
        self,
        raw_cat: Any,
        user_text: str,
        session: Dict[str, Any],
        hints: Dict[str, Any],
    ) -> Optional[str]:
        mapping = self._build_category_mapping(hints)
        low = (user_text or "").lower()

        if isinstance(raw_cat, str) and raw_cat.strip():
            cleaned = self._clean_phrase(raw_cat)
            if cleaned in mapping:
                return mapping[cleaned]

            norm_key = self._norm_cat_key(raw_cat)
            if norm_key in mapping.values():
                return norm_key

        # scan longest-first phrase match in message
        for phrase in sorted(mapping.keys(), key=len, reverse=True):
            if phrase and phrase in low:
                return mapping[phrase]

        # fallback: session last_category
        last_cat = session.get("last_category")
        if isinstance(last_cat, str) and last_cat.strip():
            return last_cat

        return None

    def _is_pure_category_query(self, user_text: str, cat_key: Optional[str], mapping: Dict[str, str]) -> bool:
        if not cat_key:
            return False
        low = self._clean_phrase(user_text)
        if not low:
            return False

        phrases = [p for p, k in mapping.items() if k == cat_key]
        if not phrases:
            return False

        generic_words = {
            "meat", "meats", "catalog", "catalogue", "category", "products", "range",
            "stuff", "things", "items", "selection", "options", "list", "full", "all"
        }

        for ph in phrases:
            if ph in low:
                leftover = low.replace(ph, " ")
                leftover = re.sub(r"\s+", " ", leftover).strip()
                if not leftover:
                    return True
                tokens = leftover.split()
                if tokens and all(t in generic_words for t in tokens):
                    return True

        return False

    # --------------------------------------------------------------- #
    # POST PROCESS                                                     #
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
        sku = data.get("sku") or session.get("last_sku")
        handoff_channel = data.get("handoff_channel")

        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = str(data.get("clarification_question") or "")

        meta_in = data.get("meta") or {}
        low = (user_text or "").lower()

        meta = self._meta_base(
            is_greeting=bool(meta_in.get("is_greeting", False)),
            is_goodbye=bool(meta_in.get("is_goodbye", False)),
            search_scope=str(meta_in.get("search_scope") or "top_picks"),
            item_level=bool(meta_in.get("item_level", False)),
            search_tags=(meta_in.get("search_tags") or []),
            max_items=self._to_int(meta_in.get("max_items"), default=8),
            wants_chunking=bool(meta_in.get("wants_chunking", False)),
            primary_cut=meta_in.get("primary_cut"),
        )
        if not isinstance(meta["search_tags"], list):
            meta["search_tags"] = []

        # category resolve
        category_map = self._build_category_mapping(hints)
        cat = self._resolve_category(raw_cat, user_text, session, hints)

        # postcode: always try extract, then fallback to session
        postcode = (
            data.get("postcode")
            or self._extract_postcode_anywhere(user_text, allow_outward_only=True)
            or session.get("postcode")
        )

        # 0) If message is basically a postcode, force delivery intent
        if self._looks_like_just_postcode(user_text) and postcode:
            return self._plan_delivery(postcode, session)

        # 1) BBQ upgrade
        if intent in {"unknown", "faq"} and "bbq" in low:
            intent = "search_product"
            action = "SEARCH_PRODUCTS"
            product_name = product_name or "bbq selection, mix of popular cuts for grilling"

        # 2) Full catalog detection (strong)
        full_keywords = ("full", "all", "everything", "entire", "whole", "catalog", "catalogue", "list")
        if any(k in low for k in full_keywords):
            intent = "search_product"
            action = "SEARCH_PRODUCTS"
            if cat:
                meta["search_scope"] = "full_category"
            else:
                meta["search_scope"] = "full_store"
            meta["max_items"] = max(meta["max_items"], 30)
            meta["wants_chunking"] = True
            if not product_name:
                if cat:
                    product_name = f"full {cat.replace('_', ' ')} catalog"
                else:
                    product_name = "full store catalog"

        # 3) Item-level cut detection
        detected_cut = None
        for word in self.CUT_KEYWORDS:
            if re.search(rf"\b{re.escape(word)}\b", low):
                detected_cut = word
                break

        if detected_cut:
            intent = "search_product"
            action = "SEARCH_PRODUCTS"
            meta["item_level"] = True
            meta["primary_cut"] = detected_cut
            if detected_cut not in meta["search_tags"]:
                meta["search_tags"].append(detected_cut)
            if meta["search_scope"] in {"top_picks", None, ""}:
                meta["search_scope"] = "item_list"
            if not product_name:
                product_name = user_text

        # 4) Pure category queries
        if self._is_pure_category_query(user_text, cat, category_map):
            intent = "search_product"
            action = "SEARCH_PRODUCTS"
            if any(k in low for k in full_keywords):
                meta["search_scope"] = "full_category"
                meta["max_items"] = max(meta["max_items"], 30)
                meta["wants_chunking"] = True
            else:
                meta["search_scope"] = "top_picks"
                meta["wants_chunking"] = False

        # 5) Delivery intent without postcode -> ask
        if intent == "check_delivery" and not postcode:
            action = "ASK_SLOT"
            needs_clarification = True
            clarification_question = "What’s your postcode (for example: E1 6AN)?"

        # 6) Greetings safety net
        if self._is_greeting(low) and intent == "unknown":
            intent = "greeting"
            action = "GREET"
            meta["is_greeting"] = True

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
    # PLAN BUILDERS                                                    #
    # --------------------------------------------------------------- #

    def _plan_delivery(self, postcode: str, session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "intent": "check_delivery",
            "action": "CHECK_DELIVERY",
            "category": None,
            "product_name": None,
            "postcode": postcode,
            "sku": session.get("last_sku"),
            "handoff_channel": None,
            "needs_clarification": False,
            "clarification_question": "",
            "meta": self._meta_base(),
        }

    # --------------------------------------------------------------- #
    # BASELINE PLAN                                                    #
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
            "meta": self._meta_base(),
        }

    # --------------------------------------------------------------- #
    # META                                                            #
    # --------------------------------------------------------------- #

    def _meta_base(
        self,
        *,
        is_greeting: bool = False,
        is_goodbye: bool = False,
        search_scope: str = "top_picks",
        item_level: bool = False,
        search_tags: Optional[List[str]] = None,
        max_items: int = 8,
        wants_chunking: bool = False,
        primary_cut: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "is_greeting": bool(is_greeting),
            "is_goodbye": bool(is_goodbye),
            "search_scope": search_scope,
            "item_level": bool(item_level),
            "search_tags": list(search_tags or []),
            "max_items": int(max_items),
            "wants_chunking": bool(wants_chunking),
            "primary_cut": primary_cut,
        }

    @staticmethod
    def _to_int(v: Any, *, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return default

    # --------------------------------------------------------------- #
    # UTILITIES                                                        #
    # --------------------------------------------------------------- #

    @staticmethod
    def _is_greeting(low: str) -> bool:
        return bool(
            re.search(
                r"\b(hi|hello|hey|salam|salaam|assalamu alaikum|assalamualaikum|as-salamu alaykum)\b",
                low or "",
            )
        )

    @staticmethod
    def _looks_like_delivery(low: str) -> bool:
        low = low or ""
        return any(
            w in low
            for w in [
                "deliver", "delivery", "ship", "shipping",
                "postcode", "post code",
                "minimum order", "min order",
            ]
        )

    def _extract_postcode_anywhere(self, text: str, *, allow_outward_only: bool) -> Optional[str]:
        if not text:
            return None
        s = text.strip().upper()

        m = self._PC_FULL.search(s)
        if m:
            return f"{m.group(1)} {m.group(2)}".strip()

        if allow_outward_only:
            m2 = self._PC_OUTWARD_ONLY.match(s)
            if m2:
                return m2.group(1).strip()

        # last resort: compact into alnum then try full again
        compact = re.sub(r"[^A-Z0-9]", "", s)
        m3 = self._PC_FULL.search(compact)
        if m3:
            return f"{m3.group(1)} {m3.group(2)}".strip()

        return None

    def _looks_like_just_postcode(self, text: str) -> bool:
        """
        True if the whole message is basically a postcode (with/without space).
        Prevents the bot from treating "SW1A1AA" as a random product query.
        """
        if not text:
            return False
        t = text.strip().upper()
        # allow only letters/digits/spaces
        if re.sub(r"[A-Z0-9\s]", "", t):
            return False

        # spaced or unspaced full
        if self._PC_FULL.fullmatch(t.replace(" ", "")):
            return True
        if self._PC_FULL.fullmatch(t):
            return True

        # outward-only
        if self._PC_OUTWARD_ONLY.fullmatch(t):
            return True

        # heuristic: short (4-8) and has both letters+digits
        compact = re.sub(r"\s+", "", t)
        if 4 <= len(compact) <= 8:
            letters = sum(ch.isalpha() for ch in compact)
            digits = sum(ch.isdigit() for ch in compact)
            return letters >= 2 and digits >= 1

        return False
