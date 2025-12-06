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

======================================================================
INTENTS (pick one)
======================================================================
"greeting"        -> hi, salam, hello, etc.
"search_product"  -> customer wants items, ideas, or suggestions.
"browse_category" -> they only specify a broad family (e.g. "chicken", "lamb").
"price_check"     -> clearly asking price of a specific product/SKU.
"check_delivery"  -> anything about delivery / shipping / coverage / minimum order.
"store_info"      -> opening times, branches, phone numbers, locations.
"faq"             -> returns, halal status, frozen rules, storage, etc.
"human_handoff"   -> wants a real person (phone / WhatsApp / in-store).
"smalltalk"       -> non-business chat.
"unknown"         -> too unclear to classify.

======================================================================
ACTIONS (pick one)
======================================================================
"GREET"           -> send a greeting-style reply.
"ASK_SLOT"        -> ask for one missing key piece of info.
"SEARCH_PRODUCTS" -> call catalog search with category / product_name / tags.
"CHECK_DELIVERY"  -> call delivery + nearest-branch tools.
"PRICE_CHECK"     -> call price_of + in_stock tools.
"STORE_INFO"      -> call store/FAQ tools for branches & hours.
"FAQ_LOOKUP"      -> general FAQ search.
"HUMAN_HANDOFF"   -> prepare to hand over to human (phone / WhatsApp / in-store).
"SMALLTALK_REPLY" -> lightweight conversational reply.
"DO_NOTHING"      -> completely empty / unusable input.

======================================================================
SLOTS
======================================================================
category:
  - Short category key like "poultry", "lamb", "beef", "groceries",
    "marinated_meats", "frozen_meats", "exotic_meats", etc.
  - Use whatever categories exist for the store.
  - null if no category is implied.

product_name:
  - Free text used for catalog search.
  - Include occasion, budget, people, etc when helpful.
  - Example: "bbq for 6 people, medium spicy, budget 30 pounds, mostly chicken".

postcode:
  - UK-style postcode string (e.g. "E1 6AN") OR null.

sku:
  - Exact internal SKU code OR null.

handoff_channel:
  - "phone" | "whatsapp" | "in_store" | null

======================================================================
SESSION
======================================================================
You receive a "session" object with:
- postcode
- last_intent
- last_category
- last_sku

You MAY reuse these when the user refers back with vague language.

Examples:
- "same again", "same thing", "that one"      -> reuse last_sku if present.
- "more", "more options", "all options"      -> reuse last_category.
- "anything else for chicken"                -> intent=search_product, category="chicken".

======================================================================
PRODUCT-LEVEL UNDERSTANDING
======================================================================
You must treat products as INDIVIDUAL ITEMS when the user clearly
asks for a specific cut or item, for example:

- "wings", "chicken wings", "prime wings"
- "lamb brain", "brain", "paya", "kidneys", "liver"
- "mince", "5% mince", "beef burgers"

In those cases:
- intent = "search_product"
- action = "SEARCH_PRODUCTS"
- category = best guess (reuse last_category if reasonable)
- product_name = the concrete request (e.g. "chicken wings only")
- meta.item_level = true
- meta.search_scope = "item_list"
- meta.search_tags should include the main cut name ("wings", "brain", "mince")
- meta.primary_cut = that main cut name (e.g. "wings")

======================================================================
CATALOG SCOPE & MESSAGE SIZE
======================================================================
You must also decide HOW BIG the answer should be (roughly):

meta.search_scope:
  - "top_picks"     -> small curated list (3–8 items)
  - "item_list"     -> list of items matching a specific cut (e.g. wings)
  - "full_category" -> as many products as available in one category (needs chunking)
  - "full_store"    -> all products in the shop (the renderer will usually ask the user to narrow down)

meta.max_items:
  - Suggest a maximum number of items the renderer should show at once.
  - Default 8 for normal queries.
  - For full_category requests, 20–40 and set meta.wants_chunking = true.

meta.wants_chunking:
  - true when the result will be LONG (full category or store).
  - This tells the renderer/handler to split into multiple WhatsApp messages.

======================================================================
CLARIFICATION (be confident)
======================================================================
- If you have enough info to act (SEARCH_PRODUCTS, PRICE_CHECK, etc.), then:
    needs_clarification = false
    action = chosen action

- Only set needs_clarification = true when:
    - you cannot safely choose a category / postcode / sku
    - or the message is totally ambiguous.

When you DO need clarification:
  action = "ASK_SLOT"
  clarification_question = short and specific.

======================================================================
OUTPUT FORMAT (STRICT JSON)
======================================================================
You MUST ALWAYS return valid JSON (no markdown, no comments).

Required fields:

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

    Dynamic version:
    - No hard-coded category list.
    - Any category string from the model/user is accepted (normalised).
    - Still gives hints about size (search_scope, max_items, wants_chunking).
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
    }

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
        fast = self._fast_path(user_text, session)
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
        raw = completion.choices[0].message.content
        return self._post_process(raw, user_text, session)

    # --------------------------------------------------------------- #
    # FAST PATH                                                       #
    # --------------------------------------------------------------- #

    def _fast_path(self, text: str, session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        low = text.lower().strip()

        # greetings
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

        # more / more options
        if low in {"more", "more options", "all options", "anything else"}:
            last_cat = session.get("last_category")
            last_intent = session.get("last_intent")
            base_meta = {
                "is_greeting": False,
                "is_goodbye": False,
                "search_scope": "top_picks",
                "item_level": False,
                "search_tags": [],
                "max_items": 8,
                "wants_chunking": False,
                "primary_cut": None,
            }
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
                    "meta": base_meta,
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
                    "meta": base_meta,
                }

        # "meat" / "meat catalog"
        if low.startswith("meat"):
            return {
                "intent": "search_product",
                "action": "ASK_SLOT",
                "category": None,
                "product_name": "mixed meat request",
                "postcode": session.get("postcode"),
                "sku": session.get("last_sku"),
                "handoff_channel": None,
                "needs_clarification": True,
                "clarification_question": "Are you looking for chicken, lamb, beef, or a mix of meats?",
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

        # delivery with postcode
        postcode = self._extract_postcode(text)
        if self._looks_like_delivery(low):
            if postcode:
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

        return None

    # --------------------------------------------------------------- #
    # POST PROCESS                                                     #
    # --------------------------------------------------------------- #

    def _post_process(self, raw: str, user_text: str, session: Dict[str, Any]) -> Dict[str, Any]:
        try:
            data = json.loads(raw)
        except Exception:
            return self._blank_plan(session)

        intent = (data.get("intent") or "unknown").strip()
        action = (data.get("action") or "DO_NOTHING").strip()

        # dynamic category: accept any string, just normalise
        cat = data.get("category")
        if isinstance(cat, str):
            cat = cat.strip()
            if not cat:
                cat = None
            else:
                # normalise spaces / casing but DO NOT restrict values
                cat = re.sub(r"\s+", "_", cat.lower())
        else:
            cat = None

        product_name = data.get("product_name")
        postcode = data.get("postcode") or session.get("postcode") or self._extract_postcode(user_text)
        sku = data.get("sku") or session.get("last_sku")
        handoff_channel = data.get("handoff_channel")
        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = data.get("clarification_question") or ""

        meta_in = data.get("meta") or {}
        low = user_text.lower()

        # meta defaults
        search_scope = meta_in.get("search_scope") or "top_picks"
        item_level = bool(meta_in.get("item_level", False))
        search_tags = meta_in.get("search_tags") or []
        if not isinstance(search_tags, list):
            search_tags = []
        try:
            max_items = int(meta_in.get("max_items", 8))
        except Exception:
            max_items = 8
        wants_chunking = bool(meta_in.get("wants_chunking", False))
        primary_cut = meta_in.get("primary_cut")

        meta = {
            "is_greeting": bool(meta_in.get("is_greeting", False)),
            "is_goodbye": bool(meta_in.get("is_goodbye", False)),
            "search_scope": search_scope,
            "item_level": item_level,
            "search_tags": search_tags,
            "max_items": max_items,
            "wants_chunking": wants_chunking,
            "primary_cut": primary_cut,
        }

        # bbq upgrade
        if intent in {"unknown", "faq"} and "bbq" in low:
            intent = "search_product"
            action = "SEARCH_PRODUCTS"
            # if model didn't pick a category, we don't force it:
            # keep cat as-is (could be None); catalog layer can still search.
            product_name = product_name or "bbq selection, mix of popular cuts for grilling"

        # vague meat
        if intent in {"unknown", "faq"} and low.strip() == "meat":
            intent = "search_product"
            action = "ASK_SLOT"
            needs_clarification = True
            clarification_question = "Are you looking for chicken, lamb, beef, or a mix of meats?"

        # full catalog detection: "full catalog", "all options", etc.
        full_keywords = ("full", "all", "everything", "entire", "whole", "catalog")
        if any(k in low for k in full_keywords):
            # if the model already suggested a category, treat it as full_category
            if cat:
                intent = "search_product"
                action = "SEARCH_PRODUCTS"
                meta["search_scope"] = "full_category"
                meta["max_items"] = max_items if max_items > 8 else 30
                meta["wants_chunking"] = True
                product_name = product_name or f"full {cat.replace('_', ' ')} catalog"
            else:
                # no category → full store
                intent = "search_product"
                action = "SEARCH_PRODUCTS"
                meta["search_scope"] = "full_store"
                meta["max_items"] = max_items if max_items > 8 else 30
                meta["wants_chunking"] = True

        # item-level cuts like wings / brain / mince
        detected_cut = None
        for word in self.CUT_KEYWORDS:
            if re.search(rf"\b{re.escape(word)}\b", low):
                detected_cut = word
                break

        if detected_cut:
            intent = "search_product"
            action = "SEARCH_PRODUCTS"
            item_level = True
            meta["item_level"] = True
            meta["primary_cut"] = detected_cut
            if detected_cut not in search_tags:
                search_tags.append(detected_cut)
                meta["search_tags"] = search_tags
            if meta["search_scope"] in {"top_picks", None}:
                meta["search_scope"] = "item_list"
            if not max_items or max_items < 1:
                meta["max_items"] = 8

            # infer category only very lightly; keep it dynamic
            if not cat and session.get("last_category"):
                cat = session["last_category"]
            if not product_name:
                product_name = user_text

        # if intent says CHECK_DELIVERY but no postcode
        if intent == "check_delivery" and not postcode:
            action = "ASK_SLOT"
            needs_clarification = True
            clarification_question = "What’s your postcode (for example: E1 6AN)?"

        # more-options safety net based on text
        if intent in {"unknown", "smalltalk"} and self._looks_like_more_options(low):
            last_cat = session.get("last_category")
            if last_cat:
                intent = "search_product"
                action = "SEARCH_PRODUCTS"
                cat = last_cat
                product_name = f"more options in {last_cat}"
                needs_clarification = False
                clarification_question = ""

        # greetings safety net
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
    # UTILITIES                                                        #
    # --------------------------------------------------------------- #

    @staticmethod
    def _is_greeting(low: str) -> bool:
        return bool(
            re.search(
                r"\b(hi|hello|hey|salam|salaam|assalamu alaikum|assalamualaikum|as-salamu alaykum)\b",
                low,
            )
        )

    @staticmethod
    def _looks_like_more_options(low: str) -> bool:
        return low in {
            "more",
            "more options",
            "all options",
            "anything else",
            "show me more",
            "more please",
        }

    @staticmethod
    def _looks_like_delivery(low: str) -> bool:
        return any(
            w in low
            for w in [
                "deliver",
                "delivery",
                "ship",
                "shipping",
                "postcode",
                "post code",
                "minimum order",
                "min order",
            ]
        )

    @staticmethod
    def _extract_postcode(text: str) -> Optional[str]:
        m = re.search(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})\b", text.upper())
        if not m:
            return None
        pc = m.group(1)
        pc = re.sub(r"\s+", " ", pc).strip()
        return pc
