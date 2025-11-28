# message_handler_v7.py
from __future__ import annotations

from typing import Any, Dict, Optional, List

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
        # Core deps (all are light wrappers around your JSON + logic)
        self.catalog = getattr(deps, "catalog", None)
        self.policy = getattr(deps, "policy", None)
        self.geo = getattr(deps, "geo", None)
        self.faq = getattr(deps, "faq", None)
        self.overrides = getattr(deps, "overrides", None)

        # Optional extras
        self.logger = getattr(deps, "logger", None)

        # Brain + renderer
        # BrainV7 uses the OpenAI SDK; API key is taken from env/settings.
        self.brain = BrainV7(getattr(deps, "openai_client", None))
        self.renderer = RendererV7(getattr(deps, "rewriter", None))

    # ------------------------------------------------------------------
    # PUBLIC ENTRYPOINT (called by master MessageHandler)
    # ------------------------------------------------------------------

    def handle(self, user_text: str, ctx: Dict[str, Any], sess: Dict[str, Any]) -> Dict[str, Any]:
        user_text = (user_text or "").strip()

        # 1) Build session snapshot for BrainV7
        session_snapshot = {
            "postcode": sess.get("postcode"),
            "last_intent": sess.get("last_intent"),
            "last_category": sess.get("last_category"),
            "last_sku": sess.get("last_sku"),
        }

        # 2) Ask BrainV7 for a plan (intent + action + slots)
        plan = self._safe_plan(user_text=user_text, session=session_snapshot)

        # 3) Execute tools according to the plan (grounding layer)
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

    # ------------------------------------------------------------------
    # INTERNAL: BRAIN WRAPPER
    # ------------------------------------------------------------------

    def _safe_plan(self, user_text: str, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wrap BrainV7.plan with a hard fallback so a model error
        never crashes the WhatsApp webhook.
        """
        try:
            return self.brain.plan(
                user_text=user_text,
                session=session,
                history=[],  # can plug recent turns here later
                hints={},
            )
        except Exception as e:
            if self.logger:
                self.logger.exception("V7: Brain plan failed: %s", e)

            # Minimal safe fallback
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
    # INTERNAL: TOOL EXECUTION LAYER
    # ------------------------------------------------------------------

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
            if self.policy and postcode:
                try:
                    rule = self.policy.delivery_rule_for(postcode)
                    summary = self.policy.delivery_summary(postcode)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: delivery lookup failed: %s", e)
                    rule, summary = None, ""
                facts["delivery"] = {
                    "postcode": postcode,
                    "rule": rule,
                    "summary": summary or "",
                }

            if self.geo and postcode:
                try:
                    nb = self.geo.nearest_for_postcode(postcode)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: geo lookup failed: %s", e)
                    nb = None
                if nb:
                    facts.setdefault("branch", {})["nearest"] = nb

        # --- PRODUCT SEARCH ---
        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            query, tags = self._build_search_query(
                user_text=user_text,
                category=category,
                product_name=product_name,
            )
            if self.catalog and (query or tags):
                try:
                    items = self.catalog.search(text=query, tags=tags, limit=6)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: catalog.search failed: %s", e)
                    items = []
                facts["items"] = items

        # --- PRICE CHECK ---
        if action == "PRICE_CHECK" or intent == "price_check":
            if self.catalog and sku:
                try:
                    price_val = self.catalog.price_of(sku)
                    in_stock = self.catalog.in_stock(sku)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: price check failed: %s", e)
                    price_val, in_stock = None, None
                facts["price"] = {
                    "sku": sku,
                    "price": price_val,
                    "in_stock": in_stock,
                }

        # --- STORE / FAQ LOOKUP ---
        if action in {"STORE_INFO", "FAQ_LOOKUP"} or intent in {"store_info", "faq", "unknown"}:
            if self.faq:
                try:
                    m = self.faq.best_match(user_text, hint_tags=None, top_k=1)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: faq.best_match failed: %s", e)
                    m = None

                if m:
                    entry = m[0]
                    placeholders: Dict[str, Any] = {}
                    if postcode and self.policy:
                        placeholders["postcode"] = postcode
                        try:
                            placeholders["delivery_summary"] = self.policy.delivery_summary(postcode) or ""
                        except Exception:
                            placeholders["delivery_summary"] = ""

                    # nearest branch placeholder if we already fetched it
                    if session.get("nearest_branch_id") and facts.get("branch", {}).get("nearest"):
                        placeholders["branch_name"] = facts["branch"]["nearest"].get("name") or ""

                    try:
                        answer = self.faq.render_answer(entry, placeholders)
                    except Exception as e:
                        if self.logger:
                            self.logger.exception("V7: faq.render_answer failed: %s", e)
                        answer = ""

                    facts["faq"] = {
                        "entry": entry,
                        "answer": answer,
                    }

        # SMALLTALK, GREET, HUMAN_HANDOFF, DO_NOTHING don't need facts by default
        return facts

    # ------------------------------------------------------------------
    # INTERNAL: SEARCH QUERY BUILDER
    # ------------------------------------------------------------------

    def _build_search_query(
        self,
        user_text: str,
        category: Optional[str],
        product_name: Optional[str],
    ) -> tuple[str, List[str]]:
        """
        Decide what to send to catalog.search as (text, tags).
        - If product_name is present, use that as the query.
        - If only category is present, use it as both text + tag.
        - If nothing is present, fall back to full user_text.
        """
        tags: List[str] = []
        query = ""

        if product_name:
            query = product_name
        elif category:
            query = category
            tags.append(category.lower())
        else:
            query = user_text

        return query, tags

    # ------------------------------------------------------------------
    # INTERNAL: ENTITY MAPPING
    # ------------------------------------------------------------------

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
