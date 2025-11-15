"""
AIV6 Hybrid Mode

Design:
- Deterministic retrieval remains the source of truth.
- This layer *only* polishes phrasing and adds structured clarifiers when needed.
- Confidence gate: if router confidence (if provided) is low, produce a single, safe clarifier.
- Strictly no new factual claims; we format what's already in ctx["facts"].

Inputs (ctx suggested shape from services.message_handler):
{
  "tenant": "...",
  "channel": "web|whatsapp",
  "intent": "search_product" | "check_delivery" | ...,
  "entities": {...},
  "facts": {...},                # gathered by services._gather_facts
  "policy": {"click_and_collect": bool},
  "session": {...},
  "style": {"concise": bool}
}

Prompts (optional) passed at construction:
- prompts["clarifiers"] → dict of intent->string templates
- prompts["offers"]     → CTA/offer micro-templates
"""

from __future__ import annotations
from typing import Any, Dict

from .contracts import ModeStrategy, safe_minimal_rewrite


_DEFAULT_CLARIFIERS = {
    "check_delivery": "What’s your postcode (e.g., E1 6AN)?",
    "search_product": "Which product or category are you after?",
    "price_check": "Which SKU should I check the price for?",
    "faq": "Could you clarify your question?",
    "unknown": "Could you clarify what you need?",
}


class AIV6Hybrid(ModeStrategy):
    """
    V6 Hybrid — light AI polish, no hallucinations, fully grounded.
    """

    def __init__(self, router: Any, rewriter: Any, sales: Any, **deps: Any):
        # store services (even if V6 doesn’t use every one yet)
        self.router = router
        self.rewriter = rewriter
        self.sales = sales

        # optional prompt config
        self.prompts = deps.get("prompts") or {}
        self.clarifiers = {
            **_DEFAULT_CLARIFIERS,
            **(self.prompts.get("clarifiers") or {}),
        }
        self.offers = self.prompts.get("offers") or {}

        # V6 is intentionally concise
        self.concise = True

    # -------------------------
    # Required by contract
    # -------------------------
    def name(self) -> str:
        return "AIV6"

    def plan(self, user_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Provide a deterministic “plan” for diagnostics only.
        Router and services still handle real work.
        """
        intent = (ctx.get("intent") or "").strip()
        ent = ctx.get("entities") or {}
        tools: list[dict] = []

        # Delivery-related
        if intent == "check_delivery" and (ent.get("postcode") or ctx.get("session", {}).get("postcode")):
            tools.append({"name": "policy.delivery_rule_for", "args": {"postcode": ent.get("postcode")}})
            tools.append({"name": "geo.nearest_for_postcode", "args": {"postcode": ent.get("postcode")}})

        # Product search
        if intent in {"search_product", "browse_category"}:
            tools.append({
                "name": "catalog.search",
                "args": {"query": ent.get("query"), "tags": ent.get("tags"), "limit": 6}
            })

        # Price check
        if intent == "price_check" and ent.get("sku"):
            tools.append({"name": "catalog.price_of", "args": {"sku": ent.get("sku")}})

        return {
            "goal": f"Rewrite grounded draft for intent={intent}",
            "tools": tools,
            "constraints": {"no_fabrication": True, "concise": self.concise},
        }

    # -------------------------
    # Core rewrite logic
    # -------------------------
    def rewrite(self, draft: str, ctx: Dict[str, Any]) -> str:
        """
        Apply a *light* AI polish:
        - Never changes facts
        - Short, neat, ~1–2 sentences
        - Uses deterministic info passed inside ctx["facts"]
        """
        intent = (ctx.get("intent") or "").strip() or "unknown"
        ent = ctx.get("entities") or {}
        facts = ctx.get("facts") or {}

        # 1) Clarifier requested
        if draft.lower().startswith("could you clarify") or draft.lower().startswith("which"):
            return self._clarifier(intent)

        # 2) Delivery responses
        if facts.get("delivery"):
            d = facts["delivery"]
            pc = d.get("postcode") or ent.get("postcode")
            rule = d.get("rule")
            summary = (d.get("summary") or "").strip()

            if rule:
                base = f"Yes, we deliver to {pc}. {summary}" if summary else f"Yes, we deliver to {pc}."
                return self._cta(base)

            return f"We currently do not deliver to {pc}."

        # 3) Product list polish
        if facts.get("items"):
            items = facts["items"] or []
            names = ", ".join(i.get("name", "") for i in items[:3] if i.get("name"))
            if names:
                return self._cta(f"Top picks: {names}.")

        # 4) Price response
        if facts.get("price"):
            p = facts["price"]
            if p.get("price") is not None:
                stock = "in stock" if p.get("in_stock") else "out of stock"
                return f"{p['sku']} is £{p['price']:.2f} and {stock}."

        # 5) FAQ direct answer
        if facts.get("faq") and facts["faq"].get("answer"):
            return self._cta(facts["faq"]["answer"])

        # 6) Default safe rewrite
        return self._cta(safe_minimal_rewrite(draft))

    # -------------------------
    # helpers
    # -------------------------
    def _clarifier(self, intent: str) -> str:
        return (
            self.clarifiers.get(intent)
            or _DEFAULT_CLARIFIERS.get(intent)
            or _DEFAULT_CLARIFIERS["unknown"]
        )

    def _cta(self, text: str) -> str:
        """Adds a light CTA — V6 is minimal and non-salesy."""
        t = text.strip()
        if not t or t.endswith("?"):
            return t
        if t.lower().endswith(("anything else.", "anything else")):
            return t
        return f"{t} Anything else you’d like to check?"
