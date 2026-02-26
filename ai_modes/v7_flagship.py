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

DEFAULT_GUARDRAILS = {
    "deny_unknown_delivery": "We currently don’t deliver to that area.",
    "no_price_without_sku": "Tell me the product name and I’ll check the price for you.",
}


class AIV7Flagship(ModeStrategy):
    """
    V7 Flagship Strategy
    --------------------
    - Planner describes operations (delivery check, product search, etc.)
    - Handler executes tools
    - This class formats the **final reply** using grounded facts ONLY

    IMPORTANT:
    - Nearest branch must be read from facts robustly (several possible shapes).
    - When delivery is NOT available, still show nearest branch + phone if we have it.
    """

    def __init__(self, **deps: Any):
        # Injected stores/services
        self.catalog = deps.get("catalog")
        self.policy = deps.get("policy")
        self.geo = deps.get("geo")
        self.faq = deps.get("faq")
        self.overrides = deps.get("overrides")
        self.crm = deps.get("crm")

        # Guardrails / clarifiers
        self.guardrails = {**DEFAULT_GUARDRAILS, **(deps.get("guardrails") or {})}
        prompts = deps.get("prompts") or {}
        self.clarifiers = {**DEFAULT_CLARIFIERS, **(prompts.get("clarifiers") or {})}

        self.offers = prompts.get("offers") or {}
        self.concise = True

    def name(self) -> str:
        return "AIV7"

    # ------------------------------------------------------------------
    # PLANNER → tool plan creator
    # ------------------------------------------------------------------

    def plan(self, user_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a machine-readable plan describing which tools should run.
        Renderer will create user-facing output later using facts from these tools.
        """
        intent = (ctx.get("intent") or "").strip()
        ent = ctx.get("entities") or {}
        sess = ctx.get("session") or {}

        tools: List[ToolCall] = []

        # DELIVERY CHECK
        if intent == "check_delivery":
            pc = ent.get("postcode") or sess.get("postcode")
            if not pc:
                return Plan(
                    goal="Ask for postcode",
                    tools=[],
                    constraints={"needs_clarification": True},
                ).to_dict()

            # Rule (required)
            tools.append(
                ToolCall(
                    name="policy.delivery_rule_for",
                    args={"postcode": pc},
                    required=True,
                )
            )

            # Nearest branch (optional but very useful)
            tools.append(
                ToolCall(
                    name="geo.nearest_for_postcode",
                    args={"postcode": pc},
                    required=False,
                )
            )

        # PRODUCT SEARCH
        elif intent in {"search_product", "browse_category"}:
            tools.append(
                ToolCall(
                    name="catalog.search",
                    args={"query": ent.get("query"), "tags": ent.get("tags"), "limit": 6},
                    required=True,
                )
            )

        # PRICE CHECK
        elif intent == "price_check":
            sku = ent.get("sku")
            if not sku:
                return Plan(
                    goal="Ask which product to price check",
                    tools=[],
                    constraints={"needs_clarification": True},
                ).to_dict()

            tools.append(ToolCall("catalog.price_of", {"sku": sku}, required=True))
            tools.append(ToolCall("catalog.in_stock", {"sku": sku}, required=False))

        # GENERAL FAQ / UNKNOWN
        else:
            tools.append(
                ToolCall(
                    name="faq.best_match",
                    args={"question": user_text, "top_k": 1},
                    required=False,
                )
            )

        return Plan(
            goal=f"Answer intent={intent} with grounded facts.",
            tools=tools,
            constraints={"no_fabrication": True, "concise": self.concise},
        ).to_dict()

    # ------------------------------------------------------------------
    # RENDER: create final response using grounded facts
    # ------------------------------------------------------------------

    def rewrite(self, draft: str, ctx: Dict[str, Any]) -> str:
        """
        Convert tool output + plan intent into a final, clean, grounded message.
        """
        intent = (ctx.get("intent") or "unknown").strip()
        facts = ctx.get("facts") or {}
        ent = ctx.get("entities") or {}

        # DELIVERY
        if intent == "check_delivery":
            return self._delivery_reply(facts, ent)

        # PRODUCT SEARCH
        if intent in {"search_product", "browse_category"}:
            return self._product_reply(facts, ent)

        # PRICE CHECK
        if intent == "price_check":
            return self._price_reply(facts, ent)

        # FAQ
        faq = facts.get("faq")
        if faq and faq.get("answer"):
            return self._cta(str(faq["answer"]).strip())

        # Unknown → clarifier / cleaned draft
        if draft:
            return self._cta(safe_minimal_rewrite(draft))

        return self.clarifiers.get(intent, self.clarifiers["unknown"])

    # ------------------------------------------------------------------
    # FACT HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_phone(phone: Any) -> str:
        p = str(phone or "").strip()
        # keep it simple; don’t reformat aggressively
        return p

    def _get_nearest_branch(self, facts: Dict[str, Any]) -> Dict[str, Any] | None:
        """
        Your pipeline may store nearest branch under different keys.
        We try them all, and only accept dict-shaped branches.
        """
        # Preferred shape: facts["branch"]["nearest"] = {..}
        br_block = facts.get("branch")
        if isinstance(br_block, dict):
            n = br_block.get("nearest")
            if isinstance(n, dict):
                return n

        # Common alternates
        for k in ("nearest_branch", "geo_nearest", "nearest"):
            v = facts.get(k)
            if isinstance(v, dict):
                return v

        # If you stored only an ID, we can't reliably inflate it here without direct access
        # to geo store. So we do not fake it.
        return None

    # ------------------------------------------------------------------
    # DELIVERY RENDERING
    # ------------------------------------------------------------------

    def _delivery_reply(self, facts: Dict[str, Any], ent: Dict[str, Any]) -> str:
        """
        Expected ideal facts shape (but we defend against variations):
          facts["delivery"] = {"postcode": "...", "rule": {...}|None, "summary": "..."}
          facts["branch"]["nearest"] = {"name": "...", "phone": "...", "address": "...", "postcode": "..."}
        """
        d = facts.get("delivery") or {}
        pc = ent.get("postcode") or d.get("postcode")
        if not pc:
            return self.clarifiers["check_delivery"]

        rule = d.get("rule")
        summary = str(d.get("summary") or "").strip()

        nearest = self._get_nearest_branch(facts)

        # If we have a rule → deliverable
        if rule:
            base = f"Yes, we deliver to {pc}."
            if summary:
                base += f" {summary}"
            if nearest and nearest.get("name"):
                base += f" Nearest branch: {nearest['name']}."
                phone = self._clean_phone(nearest.get("phone"))
                if phone:
                    base += f" Call: {phone}."
            return self._cta(base)

        # No rule → not deliverable, BUT still show nearest branch if available
        base = f"We currently don’t deliver to {pc}."
        if nearest and nearest.get("name"):
            base += f" Nearest branch: {nearest['name']}."
            # include address/postcode if present
            addr = str(nearest.get("address") or "").strip()
            bpc = str(nearest.get("postcode") or "").strip()
            if addr:
                base += f" {addr}"
                if bpc and bpc not in addr:
                    base += f", {bpc}"
                base += "."
            phone = self._clean_phone(nearest.get("phone"))
            if phone:
                base += f" Call: {phone}."
        else:
            base += " You can still visit the nearest branch or call the store for options."

        return self._cta(base)

    # ------------------------------------------------------------------
    # PRODUCT SEARCH RENDERING
    # ------------------------------------------------------------------

    def _product_reply(self, facts: Dict[str, Any], ent: Dict[str, Any]) -> str:
        items = facts.get("items") or []
        q = ent.get("query") or ent.get("category")

        if not items:
            if q:
                return self._cta(f"No matching items found for “{q}”. Want to try a different product?")
            return self.clarifiers["search_product"]

        top = items[:3]
        names = [i.get("name") for i in top if isinstance(i, dict) and i.get("name")]

        if not names:
            return self._cta("I found items but couldn’t read their names. Try another search?")

        msg = f"Top picks: {', '.join(names)}."
        return self._cta(msg)

    # ------------------------------------------------------------------
    # PRICE RENDERING
    # ------------------------------------------------------------------

    def _price_reply(self, facts: Dict[str, Any], ent: Dict[str, Any]) -> str:
        p = facts.get("price") or {}
        sku = ent.get("sku") or p.get("sku")

        if not sku:
            return self.guardrails["no_price_without_sku"]

        price = p.get("price")
        stock = p.get("in_stock")

        if price is None:
            return self._cta(f"I couldn’t find a price for {sku}.")

        stock_text = "in stock" if stock else "out of stock"
        msg = f"{sku} is £{float(price):.2f} and {stock_text}."
        return self._cta(msg)

    # ------------------------------------------------------------------
    # CTA HELPER
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
