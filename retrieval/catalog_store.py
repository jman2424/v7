"""
CatalogStore (Auto-Refreshing Version)
--------------------------------------

This version FIXES the issue where the bot still uses default seed data
even after the Google Sheets webhook updates catalog.json.

Key change:
- Every public read method now calls `_refresh()` to reload the latest
  catalog.json from disk before serving any results.

This guarantees that:
- You push → webhook writes catalog.json → bot replies use NEW DATA instantly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from retrieval.storage import Storage


# ---------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------

def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _slug_id(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_") or "item"


def _parse_price_str(price_str: str) -> Optional[float]:
    if not price_str:
        return None
    s = price_str.replace("£", "").strip()
    m = re.findall(r"[0-9]+(?:[.,][0-9]+)?", s)
    if not m:
        return None
    try:
        return float(m[0].replace(",", "."))
    except Exception:
        return None


# ---------------------------------------------------
# MAIN CLASS
# ---------------------------------------------------

@dataclass
class CatalogStore:
    storage: Storage

    # --------------- INIT -----------------

    def __post_init__(self):
        # Load once initially — but every API call refreshes anyway.
        self._catalog: Dict[str, Any] = self._load()
        self._sku_index: Dict[str, Dict[str, Any]] = {}
        self._tag_index: Dict[str, List[Dict[str, Any]]] = {}
        self._cat_index: Dict[str, Dict[str, Any]] = {}
        self._build_indices()

    # --------------- AUTO REFRESH -----------------

    def _refresh(self) -> None:
        """
        ALWAYS reload latest catalog.json and rebuild indices.
        This fixes your issue permanently.
        """
        self._catalog = self._load()
        self._build_indices()

    # --------------- LOAD + NORMALISE -----------------

    def _load(self) -> Dict[str, Any]:
        try:
            raw = self.storage.read_json(self.storage.tenant_key, "catalog.json")
            if not isinstance(raw, dict):
                raise ValueError("catalog.json must be a JSON object")

            def _safe_version(v: Any) -> int:
                try:
                    return int(v)
                except Exception:
                    return 1

            # Case 1: Sheets webhook schema
            if isinstance(raw.get("product_catalog"), list):
                cat = self._from_legacy_product_catalog(raw["product_catalog"])
                cat["version"] = _safe_version(raw.get("version", 1))
                return cat

            # Case 2: Already in v7 schema
            if isinstance(raw.get("categories"), list):
                return {
                    "version": _safe_version(raw.get("version", 1)),
                    "categories": raw.get("categories") or [],
                }

            # Fallback empty
            return {"version": 1, "categories": []}

        except FileNotFoundError:
            return {"version": 1, "categories": []}

    def _from_legacy_product_catalog(self, pc: List[Dict[str, Any]]) -> Dict[str, Any]:
        categories: List[Dict[str, Any]] = []

        for cat in pc:
            cat_name = str(cat.get("name") or "").strip()
            if not cat_name:
                continue

            cat_id = _slug_id(cat_name)
            items_out: List[Dict[str, Any]] = []
            used_skus: set[str] = set()

            for item in (cat.get("items") or []):
                if not isinstance(item, dict):
                    continue

                raw_name = str(item.get("name") or "").strip()
                if not raw_name:
                    continue

                price = _parse_price_str(item.get("price_str") or "")
                stock_str = (item.get("stock") or "").strip().lower()
                in_stock = not any(x in stock_str for x in ("out", "sold", "no"))

                base = f"{cat_id}_{_slug_id(raw_name)}"
                sku = base
                i = 2
                while sku in used_skus:
                    sku = f"{base}_{i}"
                    i += 1
                used_skus.add(sku)

                subcat = (item.get("subcategory") or "").strip()

                tags = [cat_id, _slug_id(raw_name)]
                if subcat:
                    tags.append(_slug_id(subcat))

                items_out.append(
                    {
                        "sku": sku,
                        "name": raw_name,
                        "price": price,
                        "unit": "each",
                        "tags": tags,
                        "in_stock": in_stock,
                        "options": [],
                    }
                )

            if items_out:
                categories.append(
                    {
                        "id": cat_id,
                        "name": cat_name,
                        "items": items_out,
                    }
                )

        return {"version": 1, "categories": categories}

    # --------------- INDEXING -----------------

    def _build_indices(self) -> None:
        self._sku_index.clear()
        self._tag_index.clear()
        self._cat_index.clear()

        for cat in self._catalog.get("categories") or []:
            cid = str(cat.get("id") or "").strip()
            if not cid:
                continue

            self._cat_index[cid] = cat

            for item in cat.get("items") or []:
                sku = str(item.get("sku") or "").strip()
                if not sku:
                    continue

                entry = {
                    **item,
                    "_category_id": cid,
                    "_category_name": cat.get("name"),
                    "_norm_name": _norm_text(item.get("name")),
                    "_norm_tags": [_norm_text(t) for t in (item.get("tags") or [])],
                }

                self._sku_index[sku] = entry

                for t in entry["_norm_tags"]:
                    if t:
                        self._tag_index.setdefault(t, []).append(entry)

    # --------------- PUBLIC API (AUTO REFRESH HERE) -----------------

    def version(self) -> int:
        self._refresh()
        return int(self._catalog.get("version", 1))

    def categories(self) -> List[Dict[str, Any]]:
        self._refresh()
        return list(self._catalog.get("categories") or [])

    def category_by_id(self, category_id: str):
        self._refresh()
        return self._cat_index.get(category_id)

    def list_all_items(self) -> List[Dict[str, Any]]:
        self._refresh()
        return list(self._sku_index.values())

    def count_items(self) -> int:
        self._refresh()
        return len(self._sku_index)

    def get_item_by_sku(self, sku: str):
        self._refresh()
        return self._sku_index.get(str(sku).strip())

    def price_of(self, sku: str):
        self._refresh()
        item = self.get_item_by_sku(sku)
        if not item:
            return None
        try:
            return float(item.get("price"))
        except Exception:
            return None

    def in_stock(self, sku: str):
        self._refresh()
        item = self.get_item_by_sku(sku)
        if not item:
            return None
        return bool(item.get("in_stock", True))

    # --------------- SEARCH -----------------

    def search(self, text=None, tags=None, limit=10):
        self._refresh()

        limit = max(1, min(limit, 50))
        text_q = _norm_text(text or "")
        tag_qs = [_norm_text(t) for t in (tags or []) if t]

        results: List[Tuple[int, Dict[str, Any]]] = []

        # Tag-priority search
        if tag_qs:
            seen = set()
            for tq in tag_qs:
                for item in self._tag_index.get(tq, []):
                    if item["sku"] in seen:
                        continue
                    if text_q and text_q not in item["_norm_name"]:
                        continue
                    seen.add(item["sku"])
                    results.append((self._score(item, text_q, tag_qs), item))

        # Text-only search
        elif text_q:
            for item in self._sku_index.values():
                if text_q in item["_norm_name"]:
                    results.append((self._score(item, text_q, tag_qs), item))
                elif any(text_q in t for t in item["_norm_tags"]):
                    # weaker fallback
                    results.append((self._score(item, text_q, tag_qs) - 1, item))

        # No filter → return all
        else:
            for item in self._sku_index.values():
                results.append((0, item))

        results.sort(key=lambda x: x[0], reverse=True)

        return [item for _, item in results[:limit]]

    def _score(self, item, text_q, tags):
        score = 0
        name = item.get("_norm_name") or ""

        if text_q:
            if name.startswith(text_q):
                score += 4
            elif text_q in name:
                score += 3

        for t in tags:
            if t in (item.get("_norm_tags") or []):
                score += 2

        if item.get("in_stock", True):
            score += 1

        return score
