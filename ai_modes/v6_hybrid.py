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
from typing import Any, Dict, Optional

from .contracts import ModeStrategy, safe_minimal_rewrite


_DEFAULT_CLARIFIERS = {
    "check_delivery": "What’s your postcode (e.g., E1 6AN)?",
    "search_product": "Which product or category are you after?",
    "price_check": "Which SKU should I check the price for?",
    "faq": "Could you clarify your question?",
    "unknown": "Could you clarify what you need?",
}


class AIV6Hybrid(ModeStrategy):
    def __init__(self, **deps: Any):
        self.prompts = deps.get("prompts") or {}
        self.clarifiers = {**_DEFAULT_CLARIFIERS, **(self.prompts.get("clarifiers") or {})}
        self.offers = self.prompts.get("offers") or {}
        self.concise = True

    def name(self) -> str:
        return "AIV6"

    # Returned for observability in diagnostics; message_handler doesn't rely on this for execution.
    def plan(self, user_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        intent = (ctx.get("intent") or "").strip()
        ent = ctx.get("entities") or {}
        tools: list[dict] = []
        if intent in {"check_delivery"} and (ent.get("postcode") or ctx.get("session", {}).get("postcode")):
            tools.append({"name": "policy.delivery_rule_for", "args": {"postcode": ent.get("postcode")}})
            tools.append({"name": "geo.nearest_for_postcode", "args": {"postcode": ent.get("postcode")}})
        if intent in {"search_product", "browse_category"}:
            tools.append({"name": "catalog.search", "args": {"query": ent.get("query"), "tags": ent.get("tags"), "limit": 6}})
        if intent == "price_check" and ent.get("sku"):
            tools.append({"name": "catalog.price_of", "args": {"sku": ent.get("sku")}})
        return {
            "goal": f"Rewrite grounded draft for intent={intent}",
            "tools": tools,
            "constraints": {"no_fabrication": True, "concise": self.concise},
        }

    def rewrite(self, draft: str, ctx: Dict[str, Any]) -> str:
        """
        Apply a light 'AI polish' without changing facts:
        - Trim, capitalize, keep to ~2 sentences
        - Insert a restrained CTA if appropriate
        - If ctx indicates clarification needed, prefer a single clear question
        """
        # 1) If a clarifier is still needed (router signaled earlier), return that.
        intent = (ctx.get("intent") or "").strip() or "unknown"
        ent = ctx.get("entities") or {}
        facts = ctx.get("facts") or {}

        # Heuristic: if the draft looks like a generic placeholder, prefer explicit clarifier template.
        if draft.lower().startswith("could you clarify") or draft.lower().startswith("which"):
            return self._clarifier(intent)

        # 2) Strengthen delivery phrasing if present
        if facts.get("delivery"):
            d = facts["delivery"]
            pc = d.get("postcode") or ent.get("postcode")
            rule = d.get("rule")
            summ = (d.get("summary") or "").strip()
            if rule:
                base = f"Yes, we deliver to {pc}. {summ}" if summ else f"Yes, we deliver to {pc}."
                return self._cta(base)
            return f"We currently do not deliver to {pc}."

        # 3) Product / price polish
        if facts.get("items"):
            names = ", ".join(i.get("name", "") for i in (facts["items"] or [])[:3] if i.get("name"))
            if names:
                return self._cta(f"Top picks: {names}.")
        if facts.get("price"):
            p = facts["price"]
            if p.get("price") is not None:
                stock = "in stock" if p.get("in_stock") else "out of stock"
                return f"{p['sku']} is £{p['price']:.2f} and {stock}."

        # 4) FAQ direct answer
        if facts.get("faq") and facts["faq"].get("answer"):
            return self._cta(facts["faq"]["answer"])

        # 5) Fallback: minimal safe rewrite of the deterministic draft
        return self._cta(safe_minimal_rewrite(draft))

    # --- helpers ---

    def _clarifier(self, intent: str) -> str:
        return self.clarifiers.get(intent) or _DEFAULT_CLARIFIERS.get(intent) or _DEFAULT_CLARIFIERS["unknown"]

    def _cta(self, text: str) -> str:
        t = text.strip()
        if not t or t.endswith("?"):
            return t  # don't CTA a question
        # Keep CTA minimal; V6 does not upsell aggressively
        if t.lower().endswith(("anything else.", "anything else")):
            return t
        return f"{t} Anything else you’d like to check?"
