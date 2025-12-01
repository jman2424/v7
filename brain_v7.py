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
Your job is to think like a smart sales assistant and decide the best next action.

======================================================================
INTENTS (pick one)
======================================================================
"greeting"        -> hi, salam, hello, etc.
"search_product"  -> user wants items, ideas, or suggestions.
"browse_category" -> user mentions a broad family only (e.g. "chicken", "lamb").
"price_check"     -> user clearly wants the price of a specific item/SKU.
"check_delivery"  -> delivery / shipping / coverage / minimum order.
"store_info"      -> opening times, branches, phone numbers, locations.
"faq"             -> returns, halal status, frozen rules, storage, etc.
"human_handoff"   -> wants a real person (phone / WhatsApp / in-store).
"smalltalk"       -> non-business talk.
"unknown"         -> unclear message.

======================================================================
ACTIONS (pick one)
======================================================================
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

======================================================================
SLOTS
======================================================================
category:
  "chicken" | "lamb" | "beef" | "groceries" | "marinated_meats" | "frozen_meats" | null

product_name:
  - Free text describing what to search for.
  - Include details when relevant:
    example: "bbq for 6 people, medium spicy, budget £30".

postcode:
  - UK postcode (e.g., "E1 6AN") OR null.

sku:
  - Internal SKU OR null.

handoff_channel:
  - "phone" | "whatsapp" | "in_store" | null

======================================================================
CLARIFICATION RULES
======================================================================
Only ask questions when absolutely necessary.

Examples:
- Delivery but no postcode → ask for postcode.
- BBQ query with no clear meat type → ask category.
- Otherwise, TAKE ACTION instead of asking.

======================================================================
OUTPUT FORMAT (STRICT JSON)
======================================================================
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

# -------------------------------------------------------------------
# UTILITIES
# -------------------------------------------------------------------

POSTCODE_REGEX = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b",
    re.IGNORECASE,
)

ALLOWED_CATEGORIES = {
    "chicken",
    "lamb",
    "beef",
    "groceries",
    "marinated_meats",
    "frozen_meats",
}

def extract_postcode(text: str) -> Optional[str]:
    m = POSTCODE_REGEX.search(text.upper())
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return None

def detect_category(text: str) -> Optional[str]:
    t = text.lower()
    for c in ALLOWED_CATEGORIES:
        if c in t:
            return c
    if "bbq" in t:
        return "chicken"
    return None

@dataclass
class BrainConfig:
    model: str = DEFAULT_MODEL
    system_prompt: str = SYSTEM_PROMPT

# -------------------------------------------------------------------
# MAIN CLASS
# -------------------------------------------------------------------

class BrainV7:
    """LLM + rule-based smart planner."""

    def __init__(self, client: Optional[OpenAI] = None, config: Optional[BrainConfig] = None):
        self.client = client or OpenAI()
        self.config = config or BrainConfig()

    # ---------------------------------------------------------------
    # PUBLIC: CREATE PLAN
    # ---------------------------------------------------------------
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

        # Empty → do nothing
        if not user_text:
            return self._blank_plan(session)

        postcode = extract_postcode(user_text)
        category = detect_category(user_text)

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

        messages = [
            {"role": "system", "content": self.config.system_prompt},
            *history,
            {"role": "user", "content": json.dumps(payload)},
        ]

        completion = self.client.chat.completions.create(
            model=self.config.model,
            response_format={"type": "json_object"},
            messages=messages,
            max_output_tokens=400,  # prevent truncation issues
        )

        raw = completion.choices[0].message.content
        plan = self._safe_parse(raw, session)

        if postcode and not plan.get("postcode"):
            plan["postcode"] = postcode

        if category and not plan.get("category"):
            plan["category"] = category

        return plan

    # ---------------------------------------------------------------
    # INTERNAL: PARSE PLAN
    # ---------------------------------------------------------------
    def _safe_parse(self, raw: str, session: Dict[str, Any]) -> Dict[str, Any]:
        try:
            data = json.loads(raw)
        except Exception:
            return self._blank_plan(session)

        intent = (data.get("intent") or "unknown").strip()
        action = (data.get("action") or "DO_NOTHING").strip()

        category = data.get("category")
        if category:
            category = category.lower()
        if category not in ALLOWED_CATEGORIES:
            category = None

        product_name = data.get("product_name")
        postcode = data.get("postcode") or session.get("postcode")
        sku = data.get("sku") or session.get("last_sku")
        handoff_channel = data.get("handoff_channel")

        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = data.get("clarification_question") or ""

        meta = data.get("meta") or {}
        meta = {
            "is_greeting": bool(meta.get("is_greeting", False)),
            "is_goodbye": bool(meta.get("is_goodbye", False)),
        }

        return {
            "intent": intent,
            "action": action,
            "category": category,
            "product_name": product_name,
            "postcode": postcode,
            "sku": sku,
            "handoff_channel": handoff_channel,
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question,
            "meta": meta,
        }

    # ---------------------------------------------------------------
    # INTERNAL: DEFAULT PLAN
    # ---------------------------------------------------------------
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
            "meta": {"is_greeting": False, "is_goodbye": False},
      }
