from __future__ import annotations

from typing import Any, Dict, Optional


class RendererV7:
    """
    V7 renderer: turns BrainV7 plan + facts into the final user-facing message.

    - NO planning here (no intent detection, no slot logic).
    - ONLY phrasing, grounded strictly on `facts` and `plan`.
    - Optional LLM-based polish via `rewriter`, but never hallucinate products/prices.
    """

    def __init__(self, rewriter: Optional[Any] = None) -> None:
        # `rewriter` is expected to have: rewrite(text, style="sales", facts=...)
        self.rewriter = rewriter

    # ------------------------------------------------------------------
    # PUBLIC ENTRYPOINT
    # ------------------------------------------------------------------

    def render(
        self,
        *,
        user_text: str,
        plan: Dict[str, Any],
        facts: Dict[str, Any],
        session: Dict[str, Any],
    ) -> str:
        intent = (plan.get("intent") or "unknown").strip()
        action = (plan.get("action") or "").strip().upper()
        needs_clarification = bool(plan.get("needs_clarification", False))
        clarification_question = (plan.get("clarification_question") or "").strip()

        # 1) Brain explicitly requested a clarifier
        if needs_clarification:
            if clarification_question:
                return clarification_question
            # fallback clarifiers based on intent if brain gave no text
            return self._fallback_clarifier(intent, plan, session)

        # 2) Special/cheap actions that don't depend heavily on facts
        if action == "GREET" or intent == "greeting":
            base = "Wa alaikum salam! How can I help you today?"
            return self._polish(base, facts)

        if action == "SMALLTALK_REPLY" or intent == "smalltalk":
            base = "I’m your Tariq Halal assistant. I can help with products, prices, and delivery details."
            return self._polish(base, facts)

        if action == "DO_NOTHING":
            # keep it silent or nudge very lightly
            base = "Could you tell me what you’d like help with? For example: chicken for BBQ or delivery to your postcode."
            return self._polish(base, facts)

        if action == "HUMAN_HANDOFF" or intent == "human_handoff":
            base = "No problem, I can connect you to the store team. What’s your postcode so I can find the nearest branch and number?"
            return self._polish(base, facts)

        # 3) Data-backed actions
        if action == "CHECK_DELIVERY" or intent == "check_delivery":
            msg = self._delivery_reply(plan, facts, session)
            return self._polish(msg, facts)

        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            msg = self._products_reply(plan, facts, user_text)
            return self._polish(msg, facts)

        if action == "PRICE_CHECK" or intent == "price_check":
            msg = self._price_reply(plan, facts)
            return self._polish(msg, facts)

        if action in {"STORE_INFO", "FAQ_LOOKUP"} or intent in {"store_info", "faq", "unknown"}:
            msg = self._faq_reply(plan, facts, user_text)
            return self._polish(msg, facts)

        # 4) Absolute fallback
        base = "I’m not fully sure what you need yet. Are you looking for chicken, lamb, beef, groceries, or delivery info?"
        return self._polish(base, facts)

    # ------------------------------------------------------------------
    # DELIVERY
    # ------------------------------------------------------------------

    def _delivery_reply(
        self,
        plan: Dict[str, Any],
        facts: Dict[str, Any],
        session: Dict[str, Any],
    ) -> str:
        delivery = facts.get("delivery") or {}
        postcode = (
            delivery.get("postcode")
            or plan.get("postcode")
            or session.get("postcode")
        )

        if not delivery:
            if postcode:
                return f"I don’t have delivery info for {postcode} yet. Could you double-check the postcode or ask about a branch instead?"
            return "What’s your postcode (for example: E1 6AN)? I’ll check delivery options for you."

        rule = delivery.get("rule")
        summary = (delivery.get("summary") or "").strip()

        if rule:
            base = f"Yes, we deliver to {postcode}."
            if summary:
                base = f"{base} {summary}"
            branch = (facts.get("branch") or {}).get("nearest") or {}
            if branch.get("name"):
                base = f"{base} Nearest branch: {branch['name']}."
            return self._append_cta(base)

        # No rule means no coverage
        if postcode:
            return f"We currently don’t deliver to {postcode}. You can still visit the nearest branch or call the store for options."
        return "We currently don’t deliver to that area. You can still visit the nearest branch or call the store for options."

    # ------------------------------------------------------------------
    # PRODUCTS
    # ------------------------------------------------------------------

    def _products_reply(
        self,
        plan: Dict[str, Any],
        facts: Dict[str, Any],
        user_text: str,
    ) -> str:
        items = facts.get("items") or []
        category = (plan.get("category") or "").strip().lower()
        product_name = (plan.get("product_name") or "").strip()

        if not items:
            # No matches found – ask for an alternative with some context
            if product_name:
                return f"I couldn’t find matches for “{product_name}”. Any alternative product or cut?"
            if category:
                return f"I couldn’t find matches in {category}. Any different cut or product you’d like?"
            return "I couldn’t find matching items. Any specific product or cut you’re after?"

        # Build a short list of top picks
        top = items[:3]
        name_list = [
            i.get("name") or i.get("_norm_name", "")
            for i in top
            if i.get("name") or i.get("_norm_name")
        ]
        name_list = [n for n in name_list if n]

        if not name_list:
            return "I found some items, but I couldn’t read their names. Could you try describing the product again?"

        base = f"Top picks: {', '.join(name_list)}."
        # Optionally mention category / BBQ etc.
        if category:
            base = f"For {category}, top picks: {', '.join(name_list)}."
        base = f"{base} Want prices or more options?"

        return self._append_cta(base)

    # ------------------------------------------------------------------
    # PRICE
    # ------------------------------------------------------------------

    def _price_reply(self, plan: Dict[str, Any], facts: Dict[str, Any]) -> str:
        price_block = facts.get("price") or {}
        sku = price_block.get("sku") or plan.get("sku")

        if not sku:
            return "Tell me the SKU or exact product name and I’ll confirm the price for you."

        price = price_block.get("price", None)
        in_stock = price_block.get("in_stock", None)

        if price is None:
            return f"I couldn’t find a price for {sku}. It might be missing or not available right now."

        stock_str = "in stock" if in_stock else "out of stock"
        base = f"{sku} is £{price:.2f} and {stock_str}."
        return self._append_cta(base)

    # ------------------------------------------------------------------
    # FAQ / STORE INFO
    # ------------------------------------------------------------------

    def _faq_reply(
        self,
        plan: Dict[str, Any],
        facts: Dict[str, Any],
        user_text: str,
    ) -> str:
        faq = facts.get("faq") or {}
        answer = (faq.get("answer") or "").strip()

        if answer:
            return self._append_cta(answer)

        # If we have no FAQ answer, gently redirect
        return (
            "I’m not fully sure about that from my data. "
            "You can ask about products, prices, delivery, or store branches."
        )

    # ------------------------------------------------------------------
    # CLARIFIERS
    # ------------------------------------------------------------------

    def _fallback_clarifier(
        self,
        intent: str,
        plan: Dict[str, Any],
        session: Dict[str, Any],
    ) -> str:
        intent = (intent or "unknown").strip()

        if intent == "check_delivery":
            return "What’s your postcode (for example: E1 6AN)?"

        if intent in {"search_product", "browse_category"}:
            return "Are you after chicken, lamb, beef, groceries or something else?"

        if intent == "price_check":
            return "Which product or SKU should I check the price for?"

        if intent == "human_handoff":
            return "What’s your postcode so I can find the nearest branch and number?"

        return "Could you clarify what you need? For example: delivery, chicken for BBQ, or store opening times."

    # ------------------------------------------------------------------
    # POLISH / CTA HELPERS
    # ------------------------------------------------------------------

    def _append_cta(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return t
        # Don’t double-CTA
        lower = t.lower()
        if lower.endswith(("anything else?", "anything else.", "anything else")):
            return t
        if t.endswith("?"):
            return t
        return f"{t} Anything else you’d like to check?"

    def _polish(self, text: str, facts: Dict[str, Any]) -> str:
        """
        Optional AI polish:
        - Keep it short, clear, and store-focused.
        - Must NOT add products or prices that aren’t in `facts`.
        """
        text = (text or "").strip()
        if not text:
            return ""

        if not self.rewriter:
            return text

        try:
            return self.rewriter.rewrite(
                text,
                style="sales",  # your tone label
                facts=facts,
            )
        except Exception:
            return text
