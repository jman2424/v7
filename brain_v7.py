# brain_v7.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI


DEFAULT_MODEL = "gpt-4.1-mini"


SYSTEM_PROMPT = """
You are StoreBrainV7 — the planning module for a halal meat shop assistant.

You DO NOT talk to the user.
You DO NOT create full answers.
You ONLY output a JSON plan that tells the assistant **what action to take**.

======================================================================
DOMAIN
======================================================================
You specialise in one store with these product families:

- chicken
- lamb
- beef
- groceries
- frozen_meats
- marinated_meats

You handle:
- product search
- category browsing
- price checks
- delivery coverage checks
- store info / FAQ
- human handoff
- greetings
- smalltalk

======================================================================
INTENTS (YOU MUST CHOOSE ONE)
======================================================================
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

======================================================================
ACTIONS (YOU MUST CHOOSE ONE)
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
SLOTS (fields you may fill)
======================================================================
category: one of:
  "chicken", "lamb", "beef", "groceries", "marinated_meats", "frozen_meats"
product_name: free text OR null
postcode: string OR null
sku: exact product code OR null
handoff_channel: "phone"|"whatsapp"|"in_store"|null

======================================================================
CLARIFICATION RULES
======================================================================
If you cannot safely proceed, set:

  "needs_clarification": true
  "clarification_question": <SHORT, specific question>

Example:
  - Missing postcode → "What's your postcode?"
  - Missing category → "Are you after chicken, lamb, beef, groceries, or frozen meats?"

======================================================================
GENERAL RULES
======================================================================
• Never hallucinate categories — only those listed above.
• If user says "meat", "any meat", "bbq", "bbq stuff", classify as:
      intent = "search_product"
      category = null
      product_name = extracted text (if possible)
• If user mentions a product directly → price_check or search_product.
• If user asks yes/no about delivery → check_delivery.
• If message is empty or emojis → DO_NOTHING.

======================================================================
OUTPUT FORMAT
======================================================================
STRICT JSON. NO markdown. NO comments.

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
    Clean, final version of StoreBrainV7.

    - Only produces JSON.
    - Zero hallucinations.
    - Very stable intent→action mapping.
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

        messages = [
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
    # INTERNAL: SAFE PARSER                                              #
    # ------------------------------------------------------------------ #

    def _blank_plan(self, session):
        """Returned for empty messages or model errors."""
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
        try:
            data = json.loads(raw)
        except Exception:
            return self._blank_plan(session)

        # Normalised fields
        intent = (data.get("intent") or "unknown").strip()
        action = (data.get("action") or "DO_NOTHING").strip()

        # CATEGORY
        cat = data.get("category")
        if cat is not None:
            cat = str(cat).lower()
        # enforce allowed set
        allowed = {
            "chicken",
            "lamb",
            "beef",
            "groceries",
            "marinated_meats",
            "frozen_meats",
        }
        if cat not in allowed:
            cat = None

        product_name = data.get("product_name")
        postcode = data.get("postcode") or session.get("postcode")
        sku = data.get("sku") or session.get("last_sku")
        handoff = data.get("handoff_channel")

        needs = bool(data.get("needs_clarification", False))
        question = data.get("clarification_question") or ""

        meta_in = data.get("meta") or {}
        meta = {
            "is_greeting": bool(meta_in.get("is_greeting")),
            "is_goodbye": bool(meta_in.get("is_goodbye")),
        }

        return {
            "intent": intent,
            "action": action,
            "category": cat,
            "product_name": product_name,
            "postcode": postcode,
            "sku": sku,
            "handoff_channel": handoff,
            "needs_clarification": needs,
            "clarification_question": question,
            "meta": meta,
        }
