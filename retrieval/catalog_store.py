"""
CatalogStore
- Loads and normalizes business/{TENANT}/catalog.json
- Text/tag/SKU search
- Category tree access
- Price and availability lookups
- Safe, read-only API (mutations happen via storage.write_json from admin)

Schema (validated by schemas/catalog.schema.json):
{
  "version": int,
  "categories": [
    {
      "id": "chicken",
      "name": "Chicken",
      "items": [
        {
          "sku": "WINGS_1KG",
          "name": "Chicken Wings 1kg",
          "price": 7.99,
          "unit": "kg",
          "tags": ["wings", "bbq"],
          "in_stock": true,
          "options": [{"name":"size","value":"1kg"}]
        }
      ]
    }
  ]
}
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from retrieval.storage import Storage


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


@dataclass
class CatalogStore:
    storage: Storage

    def __post_init__(self):
        self._catalog: Dict[str, Any] = self._load()
        # Fast indices
        self._sku_index: Dict[str, Dict[str, Any]] = {}
        self._tag_index: Dict[str, List[Dict[str, Any]]] = {}
        self._cat_index: Dict[str, Dict[str, Any]] = {}
        self._build_indices()

    # -------- internal --------

    def _load(self) -> Dict[str, Any]:
        try:
            data = self.storage.read_json(self.storage.tenant_key, "catalog.json")
            if not isinstance(data, dict):
                raise ValueError("catalog.json must be an object")
            return data
        except FileNotFoundError:
            # Minimal empty structure
            return {"version": 1, "categories": []}

    def _build_indices(self) -> None:
        self._sku_index.clear()
        self._tag_index.clear()
        self._cat_index.clear()

        cats = self._catalog.get("categories") or []
        for cat in cats:
            cid = str(cat.get("id") or cat.get("name") or "").strip()
            if not cid:
                continue
            self._cat_index[cid] = cat
            for item in (cat.get("items") or []):
                sku = str(item.get("sku") or "").strip()
                if not sku:
                    continue
                entry = {
                    **item,
                    "_category_id": cid,
                    "_category_name": cat.get("name"),
                    "_norm_name": _norm_text(item.get("name", "")),
                    "_norm_tags": [ _norm_text(t) for t in (item.get("tags") or []) ],
                }
                self._sku_index[sku] = entry
                for t in entry["_norm_tags"]:
                    self._tag_index.setdefault(t, []).append(entry)

    # -------- read-only API --------

    def version(self) -> int:
        return int(self._catalog.get("version", 1))

    def categories(self) -> List[Dict[str, Any]]:
        return list(self._catalog.get("categories") or [])

    def category_by_id(self, category_id: str) -> Optional[Dict[str, Any]]:
        return self._cat_index.get(category_id)

    def list_all_items(self) -> List[Dict[str, Any]]:
        return list(self._sku_index.values())

    def count_items(self) -> int:
        return len(self._sku_index)

    def get_item_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        return self._sku_index.get(str(sku).strip())

    def price_of(self, sku: str) -> Optional[float]:
        item = self.get_item_by_sku(sku)
        if not item:
            return None
        try:
            return float(item.get("price"))
        except Exception:
            return None

    def in_stock(self, sku: str) -> Optional[bool]:
        item = self.get_item_by_sku(sku)
        if not item:
            return None
        v = item.get("in_stock")
        return bool(v) if v is not None else True

    # -------- search --------

    def search(
        self,
        text: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search by free text (name contains) and/or canonicalized tags.
        Returns normalized item dicts (with _category_id/_category_name).
        """
        limit = max(1, min(limit, 50))
        text_q = _norm_text(text or "")
        tag_qs = [ _norm_text(t) for t in (tags or []) if t ]

        results: List[Tuple[int, Dict[str, Any]]] = []

        # Tag-first match gives better precision
        if tag_qs:
            seen = set()
            for tq in tag_qs:
                for item in self._tag_index.get(tq, []):
                    if item["sku"] in seen:
                        continue
                    if text_q and text_q not in item["_norm_name"]:
                        # if both provided, enforce both
                        continue
                    seen.add(item["sku"])
                    score = self._score(item, text_q, tag_qs)
                    results.append((score, item))
        elif text_q:
            for item in self._sku_index.values():
                if text_q in item["_norm_name"]:
                    score = self._score(item, text_q, tag_qs)
                    results.append((score, item))
                else:
                    # fallback: partial tag match
                    if any(text_q in t for t in item["_norm_tags"]):
                        score = self._score(item, text_q, tag_qs) - 1
                        results.append((score, item))
        else:
            # No filters → just return popular (here: alphabetical)
            for item in self._sku_index.values():
                results.append((0, item))

        results.sort(key=lambda t: t[0], reverse=True)
        return [r for _, r in results[:limit]]

    def _score(self, item: Dict[str, Any], text_q: str, tags: List[str]) -> int:
        score = 0
        if text_q:
            name = item.get("_norm_name") or ""
            if name.startswith(text_q):
                score += 4
            elif text_q in name:
                score += 3
        for t in tags:
            if t in (item.get("_norm_tags") or []):
                score += 2
        # small bonus for in_stock
        if item.get("in_stock", True):
            score += 1
        return score

    # -------- helpers for sales flows --------

    def shortlist_by_category(self, category_id: str, n: int = 2) -> List[Dict[str, Any]]:
        cat = self._cat_index.get(category_id)
        if not cat:
            return []
        items = [self.get_item_by_sku(i.get("sku")) for i in (cat.get("items") or [])]
        items = [i for i in items if i]
        # prioritize in-stock, then alphabetical
        items.sort(key=lambda x: (not x.get("in_stock", True), x.get("_norm_name", "")))
        return items[: max(1, n)]

    def related_by_tags(self, sku: str, n: int = 2) -> List[Dict[str, Any]]:
        item = self.get_item_by_sku(sku)
        if not item:
            return []
        tags = set(item.get("_norm_tags") or [])
        if not tags:
            return []
        candidates: Dict[str, Dict[str, Any]] = {}
        for t in tags:
            for it in self._tag_index.get(t, []):
                if it["sku"] == sku:
                    continue
                candidates[it["sku"]] = it
        outs = list(candidates.values())
        outs.sort(key=lambda x: (not x.get("in_stock", True), x.get("_norm_name", "")))
        return outs[: max(1, n)]
