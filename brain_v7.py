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
  "chicken" | "lamb" | "beef" | "groceries" | "marinated_meats" | "frozen_meats" | null

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

Examples:

User: "beef catalog"
  -> intent="search_product"
     category="beef"
     meta.search_scope="top_picks" (OR "full_category" if they explicitly say "full")
     meta.max_items=8
     meta.wants_chunking=false

User: "lamb full catalog" or "all lamb options"
  -> intent="search_product"
     category="lamb"
     meta.search_scope="full_category"
     meta.list_all_items = true
     meta.max_items ≈ 30
     meta.wants_chunking=true

User: "full product catalog", "show me everything"
  -> intent="search_product"
     category=null
     meta.search_scope="full_store"
     meta.list_all_items = true
     meta.max_items ≈ 30
     meta.wants_chunking=true
  The renderer will usually answer that the catalog is too big and ask for a category.

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

Examples:
- Delivery but no postcode at all:
    intent = "check_delivery"
    action = "ASK_SLOT"
    clarification_question = "What’s your postcode (for example: E1 6AN)?"

- User says "meat for BBQ" and you truly can’t pick category:
    intent = "search_product"
    action = "ASK_SLOT"
    clarification_question = "Are you after chicken, lamb, beef or a mix for BBQ?"

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

    - Same external interface as before.
    - More intelligence for:
        * full catalog / all options
        * item-level searches ("wings", "lamb brain")
        * rough control of answer size via meta.search_scope, max_items, wants_chunking
    """

    CUT_KEYWORDS = {
        "wing", "wings",
        "thigh", "thighs",
        "breast", "breasts",
        "drumstick", "drumsticks",
        "mince",
        "burger", "burgers",
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

    # --------------------------------------------------------------- #
    # INIT
    # --------------------------------------------------------------- #

    def __init__(self, client: Optional[OpenAI] = None, config: Optional[BrainConfig] = None):
        self.client = client or OpenAI()
        self.config = config or BrainConfig()

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

        # Empty message → blank plan
        if not user_text:
            return self._blank_plan(session)

        # 1) Fast heuristics (no OpenAI call for obvious stuff)
        fast = self._fast_path(user_text, session)
        if fast is not None:
            return fast

        # 2) Full LLM plan
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

        # 3) Post-process to enforce rules & add extra intelligence
        return self._post_process(raw, user_text, session)

    # --------------------------------------------------------------- #
    # INTERNAL: FAST PATHS                                            #
    # --------------------------------------------------------------- #

    def _fast_path(self, text: str, session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Cheap, deterministic behaviour for trivial queries so we don't
        waste tokens or get weird LLM mistakes.
        """
        low = text.lower().strip()

        # --- greetings (strong) ---
        if low in {"hi", "hello", "hey", "salam", "salaam"} or self._is_greeting(low):
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
                    "max_items": 0,
                    "wants_chunking": False,
                    "primary_cut": None,
                },
            }

        # --- generic "more" / "more options" / "all options" ---
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
                # Ask for more from the last category
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

        # --- meat queries like "meat", "meat catalog", "meat full catalog" ---
        if "meat" in low:
            # Customer clearly wants meat but we don't know which type.
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

        # --- quick delivery detection with explicit postcode in text ---
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
                        "max_items": 0,
                        "wants_chunking": False,
                        "primary_cut": None,
                    },
                }
            # no postcode anywhere → ask for it
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
                    "max_items": 0,
                    "wants_chunking": False,
                    "primary_cut": None,
                },
            }

        return None

    # --------------------------------------------------------------- #
    # INTERNAL: POST-PROCESSOR                                        #
    # --------------------------------------------------------------- #

    def _post_process(self, raw: str, user_text: str, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the LLM JSON, enforce allowed values, and upgrade behaviour
        for common patterns (bbq, vague meat, full catalog, item cuts, more options).
        """
        try:
            data = json.loads(raw)
        except Exception:
            # model completely misbehaved → safe blank
            return self._blank_plan(session)

        intent = (data.get("intent") or "unknown").strip()
        action = (data.get("action") or "DO_NOTHING").strip()

        # Normalise category
        allowed_categories = {
            "chicken",
            "lamb",
            "beef",
            "groceries",
            "marinated_meats",
            "frozen_meats",
        }
        cat = data.get("category")
        cat = str(cat).lower() if cat is not None else None
        if cat not in allowed_categories:
            cat = None

        product_name = data.get("product_name")
        postcode = data.get("postcode") or session.get("postcode") or self._extract_postcode(user_text)
        sku = data.get("sku") or session.get("last_sku")
        handoff_channel = data.get("handoff_channel")

        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = data.get("clarification_question") or ""

        meta_in = data.get("meta") or {}
        low = user_text.lower()

        # --- meta defaults / normalisation ---
        search_scope = (
            meta_in.get("search_scope")
            or data.get("search_scope")
            or "top_picks"
        )
        item_level = bool(meta_in.get("item_level", False))
        search_tags = meta_in.get("search_tags") or data.get("search_tags") or []
        if not isinstance(search_tags, list):
            search_tags = []

        try:
            max_items = int(meta_in.get("max_items", data.get("max_items", 8)))
        except Exception:
            max_items = 8

        wants_chunking = bool(meta_in.get("wants_chunking", data.get("wants_chunking", False)))
        primary_cut = meta_in.get("primary_cut") or data.get("primary_cut")

        meta = {
            "is_greeting": bool(meta_in.get("is_greeting", False)),
            "is_goodbye": bool(meta_in.get("is_goodbye", False)),
     
