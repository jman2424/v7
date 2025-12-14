# handlers/message_handler_v7.py
from __future__ import annotations

import re
from typing import Any, Dict, Optional, List

from brain_v7 import BrainV7
from renderer_v7 import RendererV7


class MessageHandlerV7:
    """
    V7: AI-first handler using BrainV7 + RendererV7.
    """

    def __init__(self, deps: Any):
        self.catalog = getattr(deps, "catalog", None)
        self.policy = getattr(deps, "policy", None)
        self.geo = getattr(deps, "geo", None)
        self.faq = getattr(deps, "faq", None)
        self.overrides = getattr(deps, "overrides", None)
        self.synonyms = getattr(deps, "synonyms", None)

        self.logger = getattr(deps, "logger", None)

        self.brain = BrainV7(getattr(deps, "openai_client", None))
        self.renderer = RendererV7(getattr(deps, "rewriter", None))

    # ------------------------------------------------------------------
    # PUBLIC ENTRYPOINT
    # ------------------------------------------------------------------

    def handle(self, user_text: str, ctx: Dict[str, Any], sess: Dict[str, Any]) -> Dict[str, Any]:
        user_text = (user_text or "").strip()

        session_snapshot = {
            "postcode": sess.get("postcode"),
            "last_intent": sess.get("last_intent"),
            "last_category": sess.get("last_category"),
            "last_sku": sess.get("last_sku"),
        }

        plan = self._safe_plan(user_text=user_text, session=session_snapshot)

        # ✅ NEW: normalize plan so simple category prompts actually browse
        plan = self._normalize_plan(plan=plan, user_text=user_text)

        facts = self._execute_plan(plan, user_text, session_snapshot)
        entities = self._entities_from_plan(plan)

        reply_text = self.renderer.render(
            user_text=user_text,
            plan=plan,
            facts=facts,
            session=session_snapshot,
        )

        # ✅ NEW: structured UI payload for webchat (cards/list)
        ui = {
            "catalog_items": self._format_items_for_ui(facts.get("items") or []),
            "has_catalog": bool(facts.get("items")),
        }

        return {
            "reply": reply_text,
            "mode": "v7",
            "intent": plan.get("intent"),
            "entities": entities,
            "facts": facts,      # keep for debugging/logging
            "ui": ui,            # ✅ webchat should use this
        }

    # ------------------------------------------------------------------
    # ✅ NEW: Plan normalization (stops “chicken -> clarify” loop)
    # ------------------------------------------------------------------

    def _normalize_plan(self, plan: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        """
        If the model already identified a category/product but chose a weak action
        (or asked clarification), force a browse/search so the user gets items.
        """
        p = dict(plan or {})
        action = (p.get("action") or "").strip().upper()
        intent = (p.get("intent") or "").strip()

        category = p.get("category")
        product_name = p.get("product_name")

        # Detect “simple” prompts like: "chicken", "lamb", "beef"
        simple_prompt = bool(user_text) and (len(user_text.split()) <= 2)

        # If we have a category/product, we should be searching.
        has_signal = bool(category or product_name)

        if has_signal and action in {"", "DO_NOTHING", "FAQ_LOOKUP", "STORE_INFO"}:
            p["action"] = "SEARCH_PRODUCTS"
            if intent == "unknown":
                p["intent"] = "browse_category" if category and not product_name else "search_product"

        # If the model tries to clarify even though category is clear, don’t block results.
        if simple_prompt and category:
            if p.get("needs_clarification"):
                p["needs_clarification"] = False
                p["clarification_question"] = ""

        # Ensure meta exists + default max_items
        meta = p.get("meta") or {}
        if "max_items" not in meta:
            meta["max_items"] = 8
        p["meta"] = meta

        return p

    # ------------------------------------------------------------------
    # INTERNAL: BRAIN WRAPPER
    # ------------------------------------------------------------------

    def _safe_plan(self, user_text: str, session: Dict[str, Any]) -> Dict[str, Any]:
        try:
            hints: Dict[str, Any] = {}

            if self.catalog:
                try:
                    cats = self.catalog.categories()
                    hints["categories"] = [
                        {"id": c.get("id"), "name": c.get("name")}
                        for c in (cats or [])
                        if c.get("id") and c.get("name")
                    ]
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: failed to load categories for hints: %s", e)

            if self.synonyms:
                hints["synonyms"] = self.synonyms

            return self.brain.plan(
                user_text=user_text,
                session=session,
                history=[],
                hints=hints,
            )
        except Exception as e:
            if self.logger:
                self.logger.exception("V7: Brain plan failed: %s", e)

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

    # ------------------------------------------------------------------
    # ✅ NEW: Format catalog items into clean UI-friendly dicts
    # ------------------------------------------------------------------

    def _format_items_for_ui(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert whatever catalog.search returns into a stable shape for webchat.
        Your frontend should render ui.catalog_items.
        """
        out: List[Dict[str, Any]] = []
        for it in items or []:
            if not isinstance(it, dict):
                continue

            # Try common keys (your catalog might vary)
            sku = it.get("sku") or it.get("id") or it.get("code")
            name = it.get("name") or it.get("title")
            price = it.get("price") or it.get("price_gbp") or it.get("amount")
            unit = it.get("unit") or it.get("size") or ""
            in_stock = it.get("in_stock")
            if in_stock is None:
                in_stock = it.get("stock", None)
                if isinstance(in_stock, int):
                    in_stock = in_stock > 0

            out.append({
                "sku": sku,
                "name": name,
                "price": price,
                "unit": unit,
                "in_stock": bool(in_stock) if in_stock is not None else None,
                "tags": it.get("tags") or [],
                "category": it.get("category") or it.get("category_id"),
                "url": it.get("url") or it.get("link"),
                "image": it.get("image") or it.get("image_url"),
                "raw": it,  # keep raw so you can debug without breaking UI
            })
        return out

    # ------------------------------------------------------------------
    # INTERNAL: TOOL EXECUTION LAYER (unchanged)
    # ------------------------------------------------------------------
    # ... keep your _execute_plan, _build_search_query, _entities_from_plan as-is ...
