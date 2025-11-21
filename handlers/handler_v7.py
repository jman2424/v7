from __future__ import annotations

from typing import Any, Dict, Optional

from brain_v7 import BrainV7
from renderer_v7 import RendererV7


class MessageHandlerV7:
    """
    V7: AI-first handler using BrainV7 + RendererV7.

    Flow:
      1) Build a session snapshot for the brain.
      2) BrainV7.plan(...) -> JSON plan (intent, action, slots, flags).
      3) Execute tools (catalog / delivery / faq) based on the plan.
      4) RendererV7.render(...) -> final reply text in store’s voice.
      5) Return unified payload for master handler (reply, intent, entities, facts).

    This is your “feels-like-its-own-LLM” mode.
    """

    def __init__(self, deps: Any):
        # Core deps
        self.catalog = deps.catalog
        self.policy = deps.policy
        self.geo = deps.geo
        self.faq = deps.faq
        self.overrides = deps.overrides

        # Brain + renderer
        # BrainV7 should internally use your OpenAI client / settings
        self.brain = BrainV7()
        self.renderer = RendererV7(deps.rewriter)

    # ----------------------------------------------------------------------
    # PUBLIC ENTRYPOINT (called by master MessageHandler)
    # ----------------------------------------------------------------------

    def handle(self, user_text: str, ctx, sess: Dict[str, Any]) -> Dict[str, Any]:
        user_text = (user_text or "").strip()

        # 1) Build session snapshot for BrainV7
        session_snapshot = {
            "postcode": sess.get("postcode"),
            "last_intent": sess.get("last_intent"),  # may be None for now
            "last_category": sess.get("last_category"),
            "last_sku": sess.get("last_sku"),
        }

        # 2) Ask BrainV7 for a plan (intent + action + slots)
        plan = self.brain.plan(
            user_text=user_text,
            session=session_snapshot,
            history=[],  # can plug recent turns here later
            hints={},
        )

        # 3) Execute tools according to the plan
        facts = self._execute_plan(plan, user_text, session_snapshot)

        # 4) Derive entities from the plan (for session + analytics)
        entities = self._entities_from_plan(plan)

        # 5) Let RendererV7 craft the final reply
        reply_text = self.renderer.render(
            user_text=user_text,
            plan=plan,
            facts=facts,
            session=session_snapshot,
        )

        # 6) Unified payload for the master handler
        return {
            "reply": reply_text,
            "mode": "v7",
            "intent": plan.get("intent"),
            "entities": entities,
            "facts": facts,
        }

    # ----------------------------------------------------------------------
    # INTERNAL: TOOL EXECUTION LAYER
    # ----------------------------------------------------------------------

    def _execute_plan(
        self,
        plan: Dict[str, Any],
        user_text: str,
        session: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Runs the actual tools (catalog, delivery, faq, etc.) for the chosen action.
        This is where you ground the brain’s plan in real store data.
        """
        action = (plan.get("action") or "DO_NOTHING").strip().upper()
        intent = (plan.get("intent") or "unknown").strip()
        facts: Dict[str, Any] = {}

        category = plan.get("category")
        product_name = plan.get("product_name") or None
        postcode = plan.get("postcode") or session.get("postcode")
        sku = plan.get("sku")

        # --- DELIVERY CHECK ---
        if action == "CHECK_DELIVERY" or intent == "check_delivery":
            if postcode:
                rule = self.policy.delivery_rule_for(postcode)
                facts["delivery"] = {
                    "postcode": postcode,
                    "rule": rule,
                    "summary": self.policy.delivery_summary(postcode),
                }
                nb = self.geo.nearest_for_postcode(postcode)
                if nb:
                    facts["branch"] = {"nearest": nb}

        # --- PRODUCT SEARCH ---
        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            query, tags = self._build_search_query(
                user_text=user_text,
                category=category,
                product_name=product_name,
            )
            if query or tags:
                items = self.catalog.search(text=query, tags=tags, limit=6)
                facts["items"] = items

        # --- PRICE CHECK ---
        if action == "PRICE_CHECK" or intent == "price_check":
            if sku:
                facts["price"] = {
                    "sku": sku,
                    "price": self.catalog.price_of(sku),
                    "in_stock": self.catalog.in_stock(sku),
                }

        # --- STORE / FAQ LOOKUP ---
        if action in {"STORE_INFO", "FAQ_LOOKUP"} or intent in {"store_info", "faq", "unknown"}:
            m = self.faq.best_match(user_text, hint_tags=None, top_k=1)
            if m:
                placeholders: Dict[str, Any] = {}
                if postcode:
                    placeholders["postcode"] = postcode
                    placeholders["delivery_summary"] = (
                        self.policy.delivery_summary(postcode) or ""
                    )
                if session.get("nearest_branch_id") and facts.get("branch", {}).get("nearest"):
                    placeholders["branch_name"] = (
                        facts["branch"]["nearest"].get("name") or ""
                    )

                facts["faq"] = {
                    "entry": m[0],
                    "answer": self.faq.render_answer(m[0], placeholders),
                }

        # SMALLTALK, GREET, HUMAN_HANDOFF, DO_NOTHING don't need facts by default
        return facts

    def _build_search_query(
        self,
        user_text: str,
        category: Optional[str],
        product_name: Optional[str],
    ) -> tuple[str, list[str]]:
        """
        Decide what to send to catalog.search as (text, tags).
        - If product_name is present, use that as the query.
        - If only category is present, use it as both text + tag.
        - If nothing is present, fall back to full user_text.
        """
        tags: list[str] = []
        query = ""

        if product_name:
            query = product_name
        elif category:
            query = category
            tags.append(category.lower())
        else:
            query = user_text

        return query, tags

    def _entities_from_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map BrainV7 slots into the 'entities' payload that the master handler
        will use for session saving and analytics.
        """
        entities: Dict[str, Any] = {}

        cat = plan.get("category")
        if cat:
            entities["category"] = cat

        postcode = plan.get("postcode")
        if postcode:
            entities["postcode"] = postcode

        sku = plan.get("sku")
        if sku:
            entities["sku"] = sku

        product_name = plan.get("product_name")
        if product_name:
            entities["product_name"] = product_name

        handoff_channel = plan.get("handoff_channel")
        if handoff_channel:
            entities["handoff_channel"] = handoff_channel

        return entities
