from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI


DEFAULT_MODEL = "gpt-4.1-mini"


DEFAULT_SYSTEM_PROMPT = """
You are StoreBrainV7, the dedicated planning model for a halal meat shop assistant.

You DO NOT talk to the user directly.
You NEVER write chatty replies.
You ONLY return a JSON plan describing what the assistant should do next.

Domain:
- You specialise in halal meat and groceries for ONE specific store.
- Main product groups: "chicken", "lamb", "beef", "groceries", "marinated_meats", "frozen_meats".
- You also handle delivery coverage, nearest branch info, store FAQs, and human handoff.

Your job:
1. Understand the user's latest message PLUS a small session snapshot.
2. Decide the main intent.
3. Decide the next ACTION and which slots/fields should be filled.
4. Decide if clarification is needed AND write a short clarification question if so.

Valid intents (intent):
- "greeting"           -> salutations, introductions ("hi", "salam", "hello")
- "search_product"     -> user wants items, prices, suggestions
- "browse_category"    -> user mentions a broad category only (e.g. "chicken", "lamb", "bbq stuff")
- "price_check"        -> user talks about a specific SKU or exact product name
- "check_delivery"     -> user asks about delivery, shipping, coverage, minimum order
- "store_info"         -> opening times, addresses, phone number, branches
- "faq"                -> generic questions that match store FAQs (returns/frozen/halal etc.)
- "human_handoff"      -> user wants to talk to a real person / store
- "smalltalk"          -> non-business chat
- "unknown"            -> you genuinely cannot classify it reliably

Valid actions (action):
- "GREET"              -> the assistant should send a greeting-style reply
- "ASK_SLOT"           -> must clarify a missing slot (like postcode, category)
- "SEARCH_PRODUCTS"    -> call catalog search with category/query/tags
- "CHECK_DELIVERY"     -> call delivery + nearest-branch tools
- "PRICE_CHECK"        -> call price_of + in_stock tools
- "STORE_INFO"         -> call FAQ/metadata tools for branch & opening times
- "FAQ_LOOKUP"         -> general FAQ search
- "HUMAN_HANDOFF"      -> ask for postcode / contact details to hand over
- "SMALLTALK_REPLY"    -> lightweight conversational reply
- "DO_NOTHING"         -> for completely empty / unusable input

Slots (fields):
- category: "chicken" | "lamb" | "beef" | "groceries" | "marinated_meats" | "frozen_meats" | null
- product_name: string or null          (rough text for product search)
- postcode: string or null              (e.g. "E1 6AN")
- sku: string or null                   (exact internal code, if user gave it)
- handoff_channel: "phone" | "whatsapp" | "in_store" | null

Session:
- You receive last intent, last category, postcode, last_sku, etc in the "session" object.
- If the user says "either", "whatever you like", "you choose", you may reuse the last category from session.

Clarification:
- needs_clarification: true ONLY when the assistant cannot safely proceed.
- clarification_question: very short, specific question to get the missing info.
  Example: "What’s your postcode (e.g. E1 6AN)?"
  Example: "Are you after chicken, lamb, beef or groceries?"

IMPORTANT:
- You MUST output STRICT JSON only. No markdown. No extra text. No comments.
- If user message is empty or just emojis, return action="DO_NOTHING" and intent="unknown".
- Prefer using "search_product" + "SEARCH_PRODUCTS" whenever the user wants items, even if vague.
"""


@dataclass
class BrainConfig:
    model: str = DEFAULT_MODEL
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


class BrainV7:
    """
    StoreBrainV7: planning-only model for v7.

    Usage:

        brain = BrainV7(openai_client)
        plan = brain.plan(
            user_text,
            session={
                "postcode": "...",
                "last_intent": "...",
                "last_category": "...",
                "last_sku": "...",
            },
            history=[{"role": "user", "content": "..."}, ...]
        )
    """

    def __init__(self, client: Optional[OpenAI] = None, config: Optional[BrainConfig] = None):
        self.client = client or OpenAI()
        self.config = config or BrainConfig()

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def plan(
        self,
        user_text: str,
        session: Optional[Dict[str, Any]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        hints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Returns a JSON dict with at least:

        {
          "intent": "...",
          "action": "...",
          "category": "... or null",
          "product_name": "... or null",
          "postcode": "... or null",
          "sku": "... or null",
          "handoff_channel": "... or null",
          "needs_clarification": bool,
          "clarification_question": "string",
          "meta": {
            "is_greeting": bool,
            "is_goodbye": bool
          }
        }
        """
        user_text = (user_text or "").strip()
        session = session or {}
        history = history or []
        hints = hints or {}

        if not user_text:
            # Hard guard: completely empty input
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
                },
            }

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
        return self._safe_parse_plan(raw, session)

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    def _safe_parse_plan(self, raw: str, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        Defensive parsing in case the model slightly misformats JSON.
        Ensures all expected fields exist with sane defaults.
        """
        try:
            data = json.loads(raw)
        except Exception:
            # Absolute fallback if the model misbehaves badly
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
                },
            }

        # Normalise fields
        intent = (data.get("intent") or "unknown").strip()
        action = (data.get("action") or "DO_NOTHING").strip()

        category = data.get("category")
        if category is not None:
            category = str(category).lower()
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
            "category": category,
            "product_name": product_name,
            "postcode": postcode,
            "sku": sku,
            "handoff_channel": handoff_channel,
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question,
            "meta": meta,
        }
