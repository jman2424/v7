# ai_modes/v7_flagship.py
from __future__ import annotations

from typing import Any, Dict, List

from .contracts import ModeStrategy, Plan, ToolCall, safe_minimal_rewrite


DEFAULT_CLARIFIERS = {
    "check_delivery": "What’s your postcode (e.g. E1 6AN)?",
    "search_product": "Which product or category are you after?",
    "price_check": "Which product should I check the price for?",
    "faq": "Could you clarify your question?",
    "unknown": "Could you clarify what you need?",
}


class AIV7Flagship(ModeStrategy):
    """
    V7 Flagship Strategy
    - Planner creates ToolCalls
    - Tool runner executes and builds `facts`
    - This class formats final message grounded on facts
    """

    def __init__(self, **deps: Any):
        self.catalog = deps.get("catalog")
        self.policy = deps.get("policy")
        self.geo = deps.get("geo")
        self.faq = deps.get("faq")
        self.overrides = deps.get("overrides")
        self.crm = deps.get("crm")

        prompts = deps.get("prompts") or {}
        self.clarifiers = {**DEFAULT_CLARIFIERS, **(prompts.get("clarifiers") or {})}
        self.concise = True

    def name(self) -> str:
        return "AIV7"

    # ------------------------------------------------------------------
    # PLANNER
    # ------------------------------------------------------------------
    def plan(self, user_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        intent = (ctx.get("intent") or "").strip()
        ent = ctx.get("entities") or {}
        tools: List[ToolCall] = []

        if intent == "check_delivery":
            pc = ent.get("postcode")
            if not pc:
                return Plan(
                    goal="Ask for postcode",
                    tools=[],
                    constraints={"no_fabrication": True, "needs_clarification": True},
                ).to_dict()

            tools.append(ToolCall(name="policy.delivery_rule_for", args={"postcode": pc}, required=True))
            # optional but makes replies better
            tools.append(ToolCall(name="policy.delivery_summary", args={"postcode": pc}, required=False))
            tools.append(ToolCall(name="geo.nearest_for_postcode", args={"postcode": pc}, required=False))

        elif intent in {"search_product", "browse_category"}:
            tools.append(
                ToolCall(
                    name="catalog.search",
                    args={"query": ent.get("query"), "tags": ent.get("tags"), "limit": 6},
                    required=True,
                )
            )

        elif intent == "price_check":
            sku = ent.get("sku")
            if not sku:
                return Plan(
                    goal="Ask which product to price check",
                    tools=[],
                    constraints={"no_fabrication": True, "needs_clarification": True},
                ).to_dict()
            tools.append(ToolCall("catalog.price_of", {"sku": sku}, required=True))
            tools.append(ToolCall("catalog.in_stock", {"sku": sku}, required=False))

        else:
            tools.append(ToolCall(name="faq.best_match", args={"question": user_text, "top_k": 1}, required=False))

        return Plan(
            goal=f"Answer intent={intent} with grounded facts.",
            tools=tools,
            constraints={"no_fabrication": True, "concise": self.concise},
        ).to_dict()

    # ------------------------------------------------------------------
    # RENDER
    # ------------------------------------------------------------------
    def rewrite(self, draft: str, ctx: Dict[str, Any]) -> str:
        intent = (ctx.get("intent") or "unknown").strip()
        facts = ctx.get("facts") or {}
        ent = ctx.get("entities") or {}

        if intent == "check_delivery":
            return self._delivery_reply(facts, ent)

        if intent in {"search_product", "browse_category"}:
            return self._product_reply(facts, ent)

        if intent == "price_check":
            return self._price_reply(facts, ent)

        faq = facts.get("faq")
        if faq and faq.get("answer"):
            return self._cta(faq["answer"])

        if draft:
            return self._cta(safe_minimal_rewrite(draft))

        return self.clarifiers.get(intent, self.clarifiers["unknown"])

    # ------------------------------------------------------------------
    # DELIVERY
    # ------------------------------------------------------------------
    def _fmt_branch(self, b: Dict[str, Any]) -> str:
        name = (b.get("name") or "").strip()
        address = (b.get("address") or "").strip()
        pc = (b.get("postcode") or "").strip()
        phone = (b.get("phone") or "").strip()

        bits = []
        if name:
            bits.append(name)
        if address:
            bits.append(address)
        if pc:
            bits.append(pc)
        tail = " — ".join(bits).strip()
        if phone:
            if tail:
                tail = f"{tail}. Call: {phone}"
            else:
                tail = f"Call: {phone}"
        return tail

    def _delivery_reply(self, facts: Dict[str, Any], ent: Dict[str, Any]) -> str:
        d = facts.get("delivery") or {}
        pc = ent.get("postcode") or d.get("postcode")

        if not pc:
            return self.clarifiers["check_delivery"]

        rule = d.get("rule")
        summary = (d.get("summary") or "").strip()

        nearest = (facts.get("branch") or {}).get("nearest") or {}
        nearest_line = self._fmt_branch(nearest) if isinstance(nearest, dict) else ""

        if rule:
            msg = f"Yes, we deliver to {pc}."
            if summary:
                msg += f" {summary}"
            if nearest_line:
                msg += f" Nearest branch: {nearest_line}."
            return self._cta(msg)

        # NO RULE → NO DELIVERY, but STILL show nearest branch
        msg = f"We currently don’t deliver to {pc}."
        if nearest_line:
            msg += f" Nearest branch: {nearest_line}."
        else:
            msg += " You can still visit a nearby branch or call the store."
        return self._cta(msg)

    # ------------------------------------------------------------------
    # PRODUCTS
    # ------------------------------------------------------------------
    def _product_reply(self, facts: Dict[str, Any], ent: Dict[str, Any]) -> str:
        items = facts.get("items") or []
        q = ent.get("query") or ent.get("category")

        if not items:
            if q:
                return self._cta(f'No matching items found for “{q}”. Want to try a different product?')
            return self.clarifiers["search_product"]

        top = items[:3]
        names = [i.get("name") for i in top if isinstance(i, dict) and i.get("name")]

        if not names:
            return self._cta("I found items but couldn’t read their names. Try another search?")

        return self._cta(f"Top picks: {', '.join(names)}.")

    # ------------------------------------------------------------------
    # PRICE
    # ------------------------------------------------------------------
    def _price_reply(self, facts: Dict[str, Any], ent: Dict[str, Any]) -> str:
        p = facts.get("price") or {}
        sku = ent.get("sku") or p.get("sku")

        if not sku:
            return "Tell me the product name or SKU and I’ll check the price for you."

        price = p.get("price")
        stock = p.get("in_stock")

        if price is None:
            return self._cta(f"I couldn’t find a price for {sku}.")

        stock_text = "in stock" if stock else "out of stock"
        return self._cta(f"{sku} is £{price:.2f} and {stock_text}.")

    # ------------------------------------------------------------------
    # CTA
    # ------------------------------------------------------------------
    def _cta(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        if t.endswith("?"):
            return t
        if t.lower().endswith("anything else"):
            return t
        return f"{t} Anything else you’d like to check?"
