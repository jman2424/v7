"""
AIV7 Flagship Mode

Design principles:
- Planner proposes tool calls; *execution & retrieval remain in services.message_handler*.
- This layer formats final answers with **strict grounding**:
  - Only use facts present in ctx["facts"] (delivery summary, items, price, faq).
  - Never speculate; if required data missing → return a single clarifier.
- Short, sales-focused tone with optional micro-CTAs.

Inputs (ctx) — see AIV6 docstring for the common shape.

Guardrails (optionally passed at construction):
- guardrails["deny_unknown_delivery"] -> phrasing to avoid promising coverage
- guardrails["no_price_without_sku"]  -> strict message when SKU missing

Prompts (optional):
- prompts["clarifiers"], prompts["offers"] (same contract as V6)
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from .contracts import ModeStrategy, Plan, ToolCall, safe_minimal_rewrite


_DEFAULT_CLARIFIERS = {
    "check_delivery": "What’s your postcode (e.g., E1 6AN)?",
    "search_product": "Which product or category are you after?",
    "price_check": "Which SKU should I check the price for?",
    "faq": "Could you clarify your question?",
    "unknown": "Could you clarify what you need?",
}

_DEFAULT_GUARDRAILS = {
    "deny_unknown_delivery": "I don’t have delivery info for that area.",
    "no_price_without_sku": "Tell me the SKU and I’ll confirm the price.",
}


class AIV7Flagship(ModeStrategy):
    def __init__(self, **deps: Any):
        self.catalog = deps.get("catalog")
        self.policy = deps.get("policy")
        self.geo = deps.get("geo")
        self.faq = deps.get("faq")
        self.crm = deps.get("crm")
        self.overrides = deps.get("overrides")
        self.guardrails = {**_DEFAULT_GUARDRAILS, **(deps.get("guardrails") or {})}
        self.prompts = deps.get("prompts") or {}
        self.clarifiers = {**_DEFAULT_CLARIFIERS, **(self.prompts.get("clarifiers") or {})}
        self.offers = self.prompts.get("offers") or {}
        self.concise = True

    def name(self) -> str:
        return "AIV7"

    # The planner describes *what* should be fetched/verified. Execution is upstream.
    def plan(self, user_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        intent = (ctx.get("intent") or "").strip()
        ent = ctx.get("entities") or {}

        tools: List[ToolCall] = []
        if intent == "check_delivery":
            pc = ent.get("postcode") or (ctx.get("session") or {}).get("postcode")
            if not pc:
                return Plan(goal="Clarify postcode", tools=[], constraints={"needs_clarification": True}).to_dict()
            tools.append(ToolCall(name="policy.delivery_rule_for", args={"postcode": pc}, required=True))
            tools.append(ToolCall(name="geo.nearest_for_postcode", args={"postcode": pc}, required=False))

        elif intent in {"search_product", "browse_category"}:
            tools.append(ToolCall(name="catalog.search", args={"query": ent.get("query"), "tags": ent.get("tags"), "limit": 6}, required=True))

        elif intent == "price_check":
            sku = ent.get("sku")
            if not sku:
                return Plan(goal="Clarify SKU", tools=[], constraints={"needs_clarification": True}).to_dict()
            tools.append(ToolCall(name="catalog.price_of", args={"sku": sku}, required=True))
            tools.append(ToolCall(name="catalog.in_stock", args={"sku": sku}, required=False))

        else:  # faq / unknown
            tools.append(ToolCall(name="faq.best_match", args={"question": user_text, "top_k": 1}, required=False))

        return Plan(
            goal=f"Answer intent={intent} with grounded facts.",
            tools=tools,
            constraints={"no_fabrication": True, "concise": self.concise},
        ).to_dict()

    def rewrite(self, draft: str, ctx: Dict[str, Any]) -> str:
        """
        Compose the final reply using verified facts in ctx["facts"].
        If critical facts absent, return a single clarifier.
        """
        intent = (ctx.get("intent") or "").strip() or "unknown"
        facts = ctx.get("facts") or {}
        ent = ctx.get("entities") or {}

        # ---- Delivery ----
        if intent in {"check_delivery", "ask_postcode"}:
            d = facts.get("delivery")
            pc = (d or {}).get("postcode") or ent.get("postcode")
            if not d or pc is None:
                return self._clarifier("check_delivery")
            rule = (d or {}).get("rule")
            summary = (d or {}).get("summary") or ""
            if rule:
                out = f"Yes, we deliver to {pc}."
                if summary:
                    out = f"{out} {summary}"
                # Optional branch
                nb = (facts.get("branch") or {}).get("nearest")
                if nb and nb.get("name"):
                    out = f"{out} Nearest branch: {nb.get('name')}."
                return self._cta(out)
            # No rule → not covered
            return self.guardrails["deny_unknown_delivery"]

        # ---- Product search / browse ----
        if intent in {"search_product", "browse_category"}:
            items = facts.get("items") or []
            if not items:
                # If we lack items, clarify rather than guess
                q = ent.get("query") or ent.get("category")
                if q:
                    return f"I couldn’t find matches for “{q}”. Any alternative product or category?"
                return self._clarifier("search_product")
            names = ", ".join(i.get("name", "") for i in items[:3] if i.get("name"))
            if names:
                return self._cta(f"Top picks: {names}.")
            return "I couldn’t find matching items."

        # ---- Price check ----
        if intent == "price_check":
            p = facts.get("price") or {}
            sku = ent.get("sku") or p.get("sku")
            if not sku:
                return self.guardrails["no_price_without_sku"]
            price = p.get("price")
            if price is not None:
                stock = "in stock" if p.get("in_stock") else "out of stock"
                return f"{sku} is £{price:.2f} and {stock}."
            # If price not found after tool calls, be explicit
            return f"I couldn’t find a price for {sku}."

        # ---- FAQ ----
        if facts.get("faq") and facts["faq"].get("answer"):
            return self._cta(facts["faq"]["answer"])

        # ---- Unknown → clarifier or minimal draft polish ----
        if draft and not draft.lower().startswith("could you"):
            # Draft came from deterministic composer; keep it but ensure tone
            return self._cta(safe_minimal_rewrite(draft))
        return self._clarifier(intent)

    # --- helpers ---

    def _clarifier(self, intent: str) -> str:
        return self.clarifiers.get(intent) or _DEFAULT_CLARIFIERS.get(intent) or _DEFAULT_CLARIFIERS["unknown"]

    def _cta(self, text: str) -> str:
        t = (text or "").strip()
        if not t or t.endswith("?"):
            return t
        if t.lower().endswith(("anything else.", "anything else")):
            return t
        return f"{t} Anything else you’d like to check?"
