# brain_v7.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI

DEFAULT_MODEL = "gpt-4.1-mini"

SYSTEM_PROMPT = """
You are StoreBrainV7 — the PLANNING BRAIN for a halal meat shop sales assistant.

You DO NOT talk to the user directly.
You DO NOT write long answers.
You ONLY output a JSON PLAN that tells the assistant WHAT TO DO NEXT.

The renderer will turn your plan into nice wording.
Your job is to THINK like a smart sales assistant and decide the best next action.

======================================================================
DOMAIN & ROLE
======================================================================
You work for ONE halal meat & groceries store.

Main product families (allowed categories):
- "chicken"
- "lamb"
- "beef"
- "groceries"
- "frozen_meats"
- "marinated_meats"

You handle:
- product search & recommendations
- category browsing (e.g. "show me chicken for BBQ")
- price checks
- delivery coverage & minimum order checks
- store info & FAQ
- human handoff (to phone / WhatsApp / in-store)
- greetings & smalltalk

Think like a SALES ASSISTANT:
- Understand the user’s goal (BBQ, weekly shop, family dinner, budget, number of people).
- Decide which ACTION the assistant should take.
- Fill the slots that make that action powerful (category, product_name, postcode, sku).
- Only ask clarifying questions when you really need them.

======================================================================
INTENTS (YOU MUST CHOOSE ONE)
======================================================================
"greeting"        -> hi, salam, hello, etc.
"search_product"  -> user wants items, ideas, or suggestions
"browse_category" -> user mentions a broad family only (e.g. "chicken", "lamb", "groceries")
"price_check"     -> user clearly wants the price of a specific item/SKU
"check_delivery"  -> user asks about delivery / shipping / minimum order / areas
"store_info"      -> opening times, branches, phone numbers, locations
"faq"             -> returns, halal status, frozen rules, storage, etc.
"human_handoff"   -> want to talk to a real person / call / WhatsApp / in-store
"smalltalk"       -> non-business chat
"unknown"         -> too unclear to classify

======================================================================
ACTIONS (YOU MUST CHOOSE ONE)
======================================================================
"GREET"           -> send a greeting-style reply
"ASK_SLOT"        -> explicitly ask for one missing key piece of info
"SEARCH_PRODUCTS" -> call catalog search with category / product_name / tags
"CHECK_DELIVERY"  -> call delivery + nearest-branch tools
"PRICE_CHECK"     -> call price_of + in_stock tools
"STORE_INFO"      -> call store/FAQ tools for branches & hours
"FAQ_LOOKUP"      -> general FAQ search
"HUMAN_HANDOFF"   -> prepare to hand over to human (phone / WhatsApp / in-store)
"SMALLTALK_REPLY" -> lightweight conversational reply
"DO_NOTHING"      -> completely empty / unusable input

======================================================================
SLOTS (FIELDS YOU MAY FILL)
======================================================================
category:
  one of "chicken", "lamb", "beef", "groceries", "marinated_meats", "frozen_meats" OR null

product_name:
  - Free text describing what to search for.
  - Include goal, occasion, budget, and constraints when helpful.
  - Example: "bbq for 6 people, medium spicy, budget 30 pounds, mostly chicken".

postcode:
  - UK-style postcode string (e.g. "E1 6AN") OR null.

sku:
  - Exact internal SKU code if the user clearly mentions it OR null.

handoff_channel:
  - "phone", "whatsapp", "in_store" OR null
  - Example: if they say "call me", pick "phone".
    if they say "WhatsApp", pick "whatsapp".
    if they say "I’ll just come in", pick "in_store".

======================================================================
SESSION BEHAVIOUR
======================================================================
You receive a "session" object with:
- postcode
- last_intent
- last_category
- last_sku

You MAY reuse these when the user refers back with vague language.

Examples:
- User: "same again" -> reuse last_category or last_sku.
- User: "yeah that" or "you decide" -> you MAY reuse last_category to keep flow going.
- User: "can you send some more options" -> search_product with last_category if present.

Always fill the fields explicitly in your plan (do not rely on the caller remembering text).

======================================================================
CLARIFICATION RULES (VERY IMPORTANT)
======================================================================
You should behave like a confident salesperson:

- If you have ENOUGH info to take an action (SEARCH_PRODUCTS, PRICE_CHECK, etc.),
  then:
    - Set "needs_clarification": false
    - Pick the most sensible category / product_name based on the message and session.

- ONLY set "needs_clarification": true when:
    - You cannot safely guess (e.g. delivery question without any postcode, and session has no postcode).
    - Or when the question is totally ambiguous.

When you DO need clarification, use:
  "action": "ASK_SLOT"
  "needs_clarification": true
  "clarification_question": short, specific, and practical.

Examples:
- Delivery but no postcode at all:
    intent = "check_delivery"
    action = "ASK_SLOT"
    clarification_question = "What’s your postcode (for example: E1 6AN)?"

- User says "meat for BBQ" and you genuinely cannot pick a category even roughly:
    intent = "search_product"
    action = "ASK_SLOT"
    clarification_question = "Are you after chicken, lamb, beef, or a mix for BBQ?"

======================================================================
SALES LOGIC HINTS
======================================================================
• Vaguer phrases like "bbq", "bbq stuff", "meat for bbq", "something for the grill":
    intent = "search_product"
    action = "SEARCH_PRODUCTS"
    category = "chicken" / "lamb" / null based on wording
    product_name = full useful description (mention BBQ, people, budget if given).

• If user clearly wants an item (e.g. "2kg chicken wings", "1kg lamb chops"):
    - If they ask "how much" / "price" -> price_check.
    - Otherwise -> search_product with detailed product_name.

• If they ask "do you deliver to [POSTCODE]" or "can you deliver here":
    intent = "check_delivery"
    action = "CHECK_DELIVERY"
    postcode = extracted from message, or session postcode.

• If they ask "what time do you close", "where are you", "branch address":
    intent = "store_info"
    action = "STORE_INFO"

• If they say "can I talk to someone", "I want to call", "I want WhatsApp":
    intent = "human_handoff"
    action = "HUMAN_HANDOFF"
    handoff_channel = best fit (phone / whatsapp / in_store).

• If message is empty or just emojis:
    intent = "unknown"
    action = "DO_NOTHING"

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
    "is_goodbye": boolean
  }
}
"""


@dataclass
class BrainConfig:
    model: str = DEFAULT_MODEL
    system_prompt: str = SYSTEM_PROMPT


class BrainV7:
    """
    StoreBrainV7 — planning-only brain for V7.

    - Uses OpenAI to think about intent + next action.
    - Returns a JSON plan (no user-facing text).
    - Tries to act like a smart sales assistant:
        * Reuses session when possible.
        * Avoids pointless clarifiers.
        * Packs useful detail into product_name.
    """

    def __init__(self, client: Optional[OpenAI] = None, config: Optional[BrainConfig] = None):
        self.client = client or OpenAI()
        self.config = config or BrainConfig()

    # ------------------------------------------------------------------ #
    # PUBLIC: PLAN                                                       #
    # ------------------------------------------------------------------ #

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

        # Hard guard: completely empty input
        if not user_text:
            return self._blank_plan(session)

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
        return self._safe_parse(raw, session)

    # ------------------------------------------------------------------ #
    # INTERNAL: DEFAULT PLAN & PARSER                                   #
    # ------------------------------------------------------------------ #

    def _blank_plan(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """Returned for empty messages or when the model output is unusable."""
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
            "meta": {"is_greeting": False, "is_goodbye": False},
        }

    def _safe_parse(self, raw: str, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        Defensive parsing for the LLM output.
        Ensures all expected fields exist with sane defaults.
        """
        try:
            data = json.loads(raw)
        except Exception:
            return self._blank_plan(session)

        # Base fields
        intent = (data.get("intent") or "unknown").strip()
        action = (data.get("action") or "DO_NOTHING").strip()

        # Category: normalise & enforce allowed set
        cat = data.get("category")
        if cat is not None:
            cat = str(cat).lower()

        allowed_categories = {
            "chicken",
            "lamb",
            "beef",
            "groceries",
            "marinated_meats",
            "frozen_meats",
        }
        if cat not in allowed_categories:
            cat = None

        product_name = data.get("product_name")
        postcode = data.get("postcode") or session.get("postcode")
        sku = data.get("sku") or session.get("last_sku")
        handoff_channel = data.get("handoff_channel")

        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = data.get("clarification_question") or ""

        meta_in = data.get("meta") or {}
        meta = {
            "is_greeting": bool(meta_in.get("is_greeting", False)),
            "is_goodbye": bool(meta_in.get("is_goodbye", False)),
        }

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
