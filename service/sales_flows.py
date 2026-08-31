# service/sales_flows.py

"""
SalesFlows — helper for product suggestions / upsells.

Right now this is intentionally minimal:
- It never crashes if called in unexpected ways.
- It gives simple, safe defaults that your AI layer can still use.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SalesFlows:
    """
    Thin wrapper around the catalog store.

    `catalog` is expected to implement at least:
      - search(text: Optional[str] = None, tags: Optional[list[str]] = None, limit: int = 10)
    """
    catalog: Any

    # --- Simple helpers you can expand later ---

    def bbq_for(self, people: int, *, budget_per_person: float = 10.0) -> Dict[str, Any]:
        """
        Build a simple grounded BBQ bundle from the tenant catalog.
        """
        people = max(1, int(people or 1))
        budget = max(0.0, float(budget_per_person or 0.0) * people)

        candidates = self.related_products(tags=["bbq", "wing", "drumstick", "kebab"], limit=12)
        if len(candidates) < 3:
            candidates = self.related_products(limit=12)

        items: List[Dict[str, Any]] = []
        total = 0.0
        for item in candidates:
            if len(items) >= 4:
                break
            price = self._price(item)
            if price <= 0:
                continue
            if budget and total + price > budget and len(items) >= 3:
                continue
            items.append(
                {
                    "sku": item.get("sku"),
                    "name": item.get("name"),
                    "qty": 1,
                    "unit_price": price,
                    "line_total": price,
                }
            )
            total += price

        return {
            "title": f"BBQ bundle for {people}",
            "items": items,
            "total": round(total, 2),
            "budget": round(budget, 2),
            "within_budget": (total <= budget) if budget else True,
        }

    def suggest_substitutions(self, sku: str, *, limit: int = 4) -> List[Dict[str, Any]]:
        """
        Suggest in-stock-ish alternatives using the original item's tags.
        """
        try:
            item = self.catalog.get_item_by_sku(sku)
        except Exception:
            item = None

        tags = []
        if isinstance(item, dict):
            tags = [str(t) for t in (item.get("tags") or []) if t]

        candidates = self.related_products(tags=tags, limit=max(limit + 3, 8))
        out: List[Dict[str, Any]] = []
        for candidate in candidates:
            if candidate.get("sku") == sku:
                continue
            price = self._price(candidate)
            out.append(
                {
                    "sku": candidate.get("sku"),
                    "name": candidate.get("name"),
                    "unit_price": price,
                    "in_stock": bool(candidate.get("in_stock", True)),
                }
            )
            if len(out) >= limit:
                break
        return out

    def related_products(
        self,
        sku: Optional[str] = None,
        *,
        tags: Optional[List[str]] = None,
        limit: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Return a small list of 'related' products.

        For now:
        - If tags are given, search by tags.
        - Otherwise, just return top `limit` items from catalog.search().
        """
        try:
            if tags:
                results = self.catalog.search(tags=tags, limit=limit)
            else:
                results = self.catalog.search(limit=limit)

            # Normalise to list[dict]
            return [self._to_dict(item) for item in results][:limit]
        except Exception:
            # Never break chatbot flow if something goes wrong
            return []

    def basket_upsell(
        self,
        basket_skus: List[str],
        *,
        limit: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Very naive upsell: just call related_products with no extra info for now.
        You can later:
        - Look at basket_skus and infer matching tags.
        - Exclude SKUs already in basket.
        """
        try:
            return self.related_products(limit=limit)
        except Exception:
            return []

    # --- Internal helpers ---

    def _to_dict(self, item: Any) -> Dict[str, Any]:
        """
        Make sure items are serialisable. If `item` is already a dict, pass it through.
        Otherwise, try to read common attributes; fall back to repr.
        """
        if isinstance(item, dict):
            return item

        data = {}
        for attr in ("sku", "name", "price", "tags", "category"):
            if hasattr(item, attr):
                data[attr] = getattr(item, attr)

        if not data:
            # Absolute fallback
            data = {"raw": repr(item)}

        return data

    def _price(self, item: Dict[str, Any]) -> float:
        for key in ("price", "unit_price"):
            try:
                value = item.get(key)
                if value is not None:
                    return float(value)
            except Exception:
                continue
        return 0.0

    # --- Safety net for unknown calls ---

    def __getattr__(self, name: str):
        """
        If some mode calls an unknown method on SalesFlows, don't crash.
        Return a no-op function that just returns empty structures / None.
        """
        def _fallback(*args, **kwargs):
            # If caller expects list, they’ll just see []; if they expect dict/str,
            # the AI layer will still cope.
            return []
        return _fallback
