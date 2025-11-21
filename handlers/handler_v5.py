from __future__ import annotations

from typing import Any, Dict, Optional


class MessageHandlerV5:
    """
    V5: Pure hard-coded / deterministic handler.

    - Uses the shared router to detect intent + entities.
    - Gathers facts directly via catalog / policy / geo / faq.
    - Composes a short, factual reply (no AI planner, no v7 brain).
    - Optional: passes text through deps.rewriter for tone only.
    """

    def __init__(self, deps: Any):
        self.router = deps.router
        self.catalog = deps.catalog
        self.policy = deps.policy
        self.geo = deps.geo
        self.faq = deps.faq
        self.rewriter = deps.rewriter
        self.overrides = deps.overrides

    # ------------------------------------------------------------------
    # Public entrypoint called by master MessageHandler
    # ------------------------------------------------------------------

    def handle(self, user_text: str, ctx, sess: Dict[str, Any]) -> Dict[str, Any]:
        """
        user_text: raw incoming message
        ctx: MessageContext (from master handler)
        sess: dict with session values (postcode, last_category, etc.)
        """
        user_text = (user_text or "").strip()

        # 1) Route to intent/entities
        route_ctx = self._ctx_for_router(ctx, sess)
        route = self.router.route(user_text, route_ctx)

        # 2) Handle clarifiers with anti-loop logic for product queries
        intent = (route.get("intent") or "unknown").strip() or "unknown"

        if route.get("needs_clarification"):
            # For product/browse we try to use the user_text as query to avoid loops
            if intent in {"search_product", "browse_category"}:
                route["needs_clarification"] = False
                ent = route.setdefault("entities", {}) or {}
                if not ent.get("query"):
                    ent["query"] = user_text
            elif intent == "price_check":
                # For price_check we really do need a SKU; keep clarifier
                reply_text = route.get("clarifier") or "Which SKU should I check the price for?"
                return self._make_reply(reply_text, mode="v5", route=route, facts={})
            else:
                # Non-product clarifier (faq/unknown/etc.)
                reply_text = route.get("clarifier") or "Could you clarify what you need?"
                return self._make_reply(reply_text, mode="v5", route=route, facts={})

        # 3) Gather facts (delivery rules, items, price, faq)
        facts = self._gather_facts(route, sess, user_text)

        # 4) Compose deterministic draft
        draft = self._compose_draft(route, facts)

        # 5) Optional tone rewrite (still deterministic at this layer)
        final = self._rewrite_tone(draft)

        # 6) Return unified payload for master handler
        return {
            "reply": final,
            "mode": "v5",
            "intent": route.get("intent"),
            "entities": route.get("entities") or {},
            "facts": facts,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ctx_for_router(self, ctx, sess: Dict[str, Any]) -> Dict[str, Any]:
        """
        Context passed to the router for intent/entity detection.
        """
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

    def _gather_facts(
        self,
        route: Dict[str, Any],
        sess: Dict[str, Any],
        user_text: str,
    ) -> Dict[str, Any]:
        """
        V5 fact retrieval – no AI, just direct service calls.
        """
        intent = route.get("intent")
        ent = route.get("entities", {}) or {}
        facts: Dict[str, Any] = {}

        # Delivery check
        if intent in {"check_delivery", "ask_postcode"} or ("postcode" in ent):
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
                items = self.catalog.search(text=query, tags=tags, limit=6)
                facts["items"] = items

        # Price lookup
        if intent == "price_check" and ent.get("sku"):
            sku = ent["sku"]
            facts["price"] = {
                "sku": sku,
                "price": self.catalog.price_of(sku),
                "in_stock": self.catalog.in_stock(sku),
            }

        # FAQ fallback
        if intent in {"faq", "unknown"}:
            hints = ent.get("tags") or []
            utterance = route.get("utterance") or route.get("text") or user_text
            m = self.faq.best_match(utterance, hint_tags=hints, top_k=1)
            if m:
                placeholders: Dict[str, Any] = {}
                if sess.get("postcode"):
                    placeholders["postcode"] = sess["postcode"]
                    placeholders["delivery_summary"] = (
                        self.policy.delivery_summary(sess["postcode"]) or ""
                    )
                if sess.get("nearest_branch_id") and facts.get("branch", {}).get(
                    "nearest"
                ):
                    placeholders["branch_name"] = (
                        facts["branch"]["nearest"].get("name") or ""
                    )

                facts["faq"] = {
                    "entry": m[0],
                    "answer": self.faq.render_answer(m[0], placeholders),
                }

        return facts

    def _compose_draft(
        self,
        route: Dict[str, Any],
        facts: Dict[str, Any],
    ) -> str:
        """
        Deterministic text composition based purely on facts.
        This is the same logic your old handler used, lifted into V5.
        """
        intent = route.get("intent")
        ent = route.get("entities", {}) or {}

        # Delivery
        if intent in {"check_delivery", "ask_postcode"} and facts.get("delivery"):
            d = facts["delivery"]
            if d["rule"]:
                return f"Yes, we deliver to {d['postcode']}. {d['summary']}."
            return f"We currently don’t deliver to {d['postcode']}."

        # Product search / browse
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

        # Generic minimal
        return route.get("clarifier") or "Could you clarify what you need?"

    def _rewrite_tone(self, text: str) -> str:
        """
        For V5 we keep things hard-coded, but if you have a cheap/deterministic
        rewriter you still want to use for tone, we can hook it here.
        If you want *zero* AI in V5, just return text unchanged.
        """
        if not text:
            return ""
        if self.rewriter is None:
            return text

        try:
            # If your rewriter is AI-based and you truly want zero LLM in V5,
            # you can switch this to return text instead.
            return self.rewriter.rewrite(text, style="sales")
        except Exception:
            return text

    def _make_reply(
        self,
        text: str,
        *,
        mode: str,
        route: Dict[str, Any],
        facts: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Small helper when we short-circuit on clarifiers.
        """
        final = self._rewrite_tone(text)
        return {
            "reply": final,
            "mode": mode,
            "intent": route.get("intent"),
            "entities": route.get("entities") or {},
            "facts": facts or {},
        }
