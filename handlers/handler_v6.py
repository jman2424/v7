from __future__ import annotations

from typing import Any, Dict, Optional

from . import HandlerDeps


class MessageHandlerV6:
    """
    V6: Hybrid handler.
    - Deterministic draft from facts.
    - AI rewrite ONLY for tone, clarity, and natural flow.
    - No planner, no V7 brain.
    - Same router + services pipeline as V5, but better surface-level polish.
    """

    def __init__(self, deps: HandlerDeps):
        self.router = deps.router
        self.catalog = deps.catalog
        self.policy = deps.policy
        self.geo = deps.geo
        self.faq = deps.faq

        # Rewrite engine (AI polish, but grounded)
        self.rewriter = deps.rewriter
        self.overrides = deps.overrides

    # ----------------------------------------------------------------------
    # PUBLIC ENTRYPOINT (called by master handler)
    # ----------------------------------------------------------------------

    def handle(self, user_text: str, ctx, sess: Dict[str, Any]) -> Dict[str, Any]:

        user_text = (user_text or "").strip()

        # 1) Route via V5/V6 shared router
        route_ctx = self._ctx_for_router(ctx, sess)
        route = self.router.route(user_text, route_ctx)

        # 2) Clarifiers — anti-loop for product/category queries
        intent = (route.get("intent") or "unknown").strip()

        if route.get("needs_clarification"):
            if intent in {"search_product", "browse_category"}:
                route["needs_clarification"] = False
                ent = route.setdefault("entities", {})
                if not ent.get("query"):
                    ent["query"] = user_text
            elif intent == "price_check":
                reply_text = route.get("clarifier") or "Which SKU should I check the price for?"
                return self._make_reply(reply_text, mode="v6", route=route, facts={})
            else:
                reply_text = route.get("clarifier") or "Could you clarify what you need?"
                return self._make_reply(reply_text, mode="v6", route=route, facts={})

        # 3) Gather facts (same as V5)
        facts = self._gather_facts(route, sess, user_text)

        # 4) Deterministic draft
        draft = self._compose_draft(route, facts)

        # 5) AI polish (rewrite)
        final = self._ai_polish(draft, route, facts)

        # 6) Unified payload
        return {
            "reply": final,
            "mode": "v6",
            "intent": route.get("intent"),
            "entities": route.get("entities") or {},
            "facts": facts,
        }

    # ----------------------------------------------------------------------
    # INTERNAL HELPERS
    # ----------------------------------------------------------------------

    def _ctx_for_router(self, ctx, sess):
        return {
            "tenant": ctx.tenant,
            "channel": ctx.channel,
            "session": {
                "postcode": sess.get("postcode"),
                "nearest_branch_id": sess.get("nearest_branch_id"),
                "last_category": sess.get("last_category"),
                "last_sku": sess.get("last_sku"),
            },
            "coverage_prefixes": getattr(self.geo, "coverage_prefixes", lambda: [])(),
        }

    def _gather_facts(self, route, sess, user_text):
        intent = route.get("intent")
        ent = route.get("entities", {}) or {}
        facts: Dict[str, Any] = {}

        # Delivery
        if intent in {"check_delivery", "ask_postcode"} or ent.get("postcode"):
            pc = ent.get("postcode") or sess.get("postcode")
            if pc:
                rule = self.policy.delivery_rule_for(pc)
                facts["delivery"] = {
                    "postcode": pc,
                    "rule": rule,
                    "summary": self.policy.delivery_summary(pc),
                }

                nb = self.geo.nearest_for_postcode(pc)
                if nb:
                    facts["branch"] = {"nearest": nb}

        # Product search
        if intent in {"search_product", "browse_category"}:
            query = ent.get("query") or ent.get("category")
            tags = ent.get("tags") or []
            if query or tags:
                facts["items"] = self.catalog.search(
                    text=query,
                    tags=tags,
                    limit=6,
                )

        # Price check
        if intent == "price_check" and ent.get("sku"):
            sku = ent["sku"]
            facts["price"] = {
                "sku": sku,
                "price": self.catalog.price_of(sku),
                "in_stock": self.catalog.in_stock(sku),
            }

        # FAQ
        if intent in {"faq", "unknown"}:
            utterance = route.get("utterance") or route.get("text") or user_text
            m = self.faq.best_match(utterance, hint_tags=ent.get("tags"), top_k=1)
            if m:
                placeholders = {}

                if sess.get("postcode"):
                    placeholders["postcode"] = sess["postcode"]
                    placeholders["delivery_summary"] = (
                        self.policy.delivery_summary(sess["postcode"]) or ""
                    )

                if sess.get("nearest_branch_id") and facts.get("branch"):
                    placeholders["branch_name"] = (
                        facts["branch"]["nearest"].get("name") or ""
                    )

                facts["faq"] = {
                    "entry": m[0],
                    "answer": self.faq.render_answer(m[0], placeholders),
                }

        return facts

    def _compose_draft(self, route, facts):
        """
        Same deterministic draft logic as V5.
        """
        intent = route.get("intent")
        ent = route.get("entities", {}) or {}

        # Delivery
        if intent in {"check_delivery", "ask_postcode"} and facts.get("delivery"):
            d = facts["delivery"]
            if d["rule"]:
                return f"Yes, we deliver to {d['postcode']}. {d['summary']}."
            return f"We currently don’t deliver to {d['postcode']}."

        # Product search
        if intent in {"search_product", "browse_category"} and facts.get("items"):
            items = facts["items"]
            names = ", ".join(
                i.get("name") or i.get("_norm_name", "") for i in items[:3]
            ).strip(", ")
            if names:
                return f"Top picks: {names}. Want prices or more options?"
            return "I couldn’t find matching items."

        # Price check
        if intent == "price_check" and facts.get("price"):
            p = facts["price"]
            if p["price"] is not None:
                stock = "in stock" if p.get("in_stock") else "out of stock"
                return f"{p['sku']} is £{p['price']:.2f} and {stock}."
            return f"I couldn’t find a price for {p['sku']}."

        # FAQ
        if facts.get("faq"):
            return facts["faq"]["answer"]

        # Default fallback
        return route.get("clarifier") or "Could you clarify what you need?"

    def _ai_polish(self, draft, route, facts):
        """
        V6 rewrite = minor LLM polish.
        - Must NOT add new products or hallucinate prices.
        - Only rewrite wording.
        """
        if not self.rewriter:
            return draft

        try:
            return self.rewriter.rewrite(
                draft,
                style="sales",  # or "friendly", "concise" — depends on your pipeline
                facts=facts,
            )
        except Exception:
            return draft

    def _make_reply(self, text: str, *, mode: str, route, facts=None):
        """
        For clarifier short-circuits.
        """
        final = self._ai_polish(text, route, facts or {})
        return {
            "reply": final,
            "mode": mode,
            "intent": route.get("intent"),
            "entities": route.get("entities") or {},
            "facts": facts or {},
        }
