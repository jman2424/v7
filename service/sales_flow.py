"""
Sales flows: product recommendations, bundles, and substitutions.

Goals:
- Convert vague user asks into concrete SKUs with quantities and total prices.
- Example: "BBQ for 6" -> wings, drumsticks, skewers, sauces, charcoal.

Connects:
- retrieval/catalog_store.py for search/price/in_stock lookups
- services/rewriter.py for CTA phrasing (outside this module)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SalesFlows:
    catalog: Any  # CatalogStoreLike

    # ---- public API ----

    def bbq_for(self, people: int, *, budget_per_person: float = 10.0) -> Dict[str, Any]:
        """
        Build a simple BBQ bundle scaled by headcount.
        """
        qty_factor = max(1, people)
        # Basic components by tag lookups
        wings = self._pick_by_tag("wings", qty=qty_factor * 3)  # 3 pieces/person
        drum = self._pick_by_tag("drumstick", qty=qty_factor * 2)
        skew = self._pick_by_tag("skewer", qty=qty_factor * 2)
        sauce = self._pick_by_tag("bbq sauce", qty=max(1, people // 4))
        coal = self._pick_by_tag("charcoal", qty=max(1, people // 6))

        items = [x for x in [wings, drum, skew, sauce, coal] if x]
        total = sum((i["unit_price"] or 0) * i["qty"] for i in items)
        budget = people * budget_per_person

        return {
            "title": f"BBQ bundle for {people}",
            "items": items,
            "total": round(total, 2),
            "budget": round(budget, 2),
            "within_budget": total <= budget,
        }

    def suggest_substitutions(self, item_sku: str) -> List[Dict[str, Any]]:
        """
        If an item is out-of-stock, suggest alternates by shared tags.
        """
        item = self.catalog.get_item_by_sku(item_sku)
        if not item:
            return []
        tags = item.get("tags") or []
        # find up to 5 items that share at least one tag and are in stock
        results = self.catalog.search(tags=tags, limit=30)
        out: List[Dict[str, Any]] = []
        for it in results:
            sku = it.get("sku")
            if sku == item_sku:
                continue
            if self.catalog.in_stock(sku):
                out.append({"sku": sku, "name": it.get("name"), "unit_price": self.catalog.price_of(sku)})
            if len(out) >= 5:
                break
        return out

    # ---- helpers ----

    def _pick_by_tag(self, tag: str, *, qty: int) -> Optional[Dict[str, Any]]:
        results = self.catalog.search(tags=[tag], limit=1)
        if not results:
            return None
        it = results[0]
        sku = it.get("sku")
        price = self.catalog.price_of(sku)
        return {"sku": sku, "name": it.get("name"), "qty": qty, "unit_price": price}
