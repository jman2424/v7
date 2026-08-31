"""
CatalogStore (Auto-Refreshing + Smarter Search Version)

Upgrades:
- Always reloads catalog.json before serving data
- Builds richer token/tag indices
- Works with any categories in catalog.json
- Better fuzzy search for typos and partial terms
- Better scoring for product names, tags, and category matches
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from retrieval.storage import Storage


# ---------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
_WS_RE = re.compile(r"\s+")


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\s_/-]+", " ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _slug_id(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_") or "item"


def _parse_price_str(price_str: str) -> Optional[float]:
    if not price_str:
        return None
    s = str(price_str).replace("£", "").strip()
    m = re.findall(r"[0-9]+(?:[.,][0-9]+)?", s)
    if not m:
        return None
    try:
        return float(m[0].replace(",", "."))
    except Exception:
        return None


def _tokenize(text: str) -> List[str]:
    t = _norm_text(text)
    if not t:
        return []
    toks = _WORD_RE.findall(t)
    out: List[str] = []
    for tok in toks:
        if tok not in out:
            out.append(tok)
        # crude singular
        if tok.endswith("s") and len(tok) > 3:
            sing = tok[:-1]
            if sing not in out:
                out.append(sing)
    return out


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------
# MAIN CLASS
# ---------------------------------------------------

@dataclass(init=False)
class CatalogStore:
    storage: Optional[Storage]

    # --------------- INIT -----------------

    def __init__(
        self,
        storage: Optional[Storage | Dict[str, Any]] = None,
        *,
        catalog: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if isinstance(storage, dict) and catalog is None and data is None:
            catalog = storage
            storage = None

        self.storage = storage if isinstance(storage, Storage) else None
        self._static = catalog is not None or data is not None
        self._catalog: Dict[str, Any] = self._normalize_catalog(catalog or data) if self._static else self._load()
        self._sku_index: Dict[str, Dict[str, Any]] = {}
        self._tag_index: Dict[str, List[Dict[str, Any]]] = {}
        self._cat_index: Dict[str, Dict[str, Any]] = {}
        self._build_indices()

    # --------------- AUTO REFRESH -----------------

    def _refresh(self) -> None:
        if self._static:
            return
        self._catalog = self._load()
        self._build_indices()

    # --------------- LOAD + NORMALISE -----------------

    def _load(self) -> Dict[str, Any]:
        if self.storage is None:
            return {"version": 1, "categories": []}
        try:
            raw = self.storage.read_json(self.storage.tenant_key, "catalog.json")
            if not isinstance(raw, dict):
                raise ValueError("catalog.json must be a JSON object")

            def _safe_version(v: Any) -> int:
                try:
                    return int(v)
                except Exception:
                    return 1

            if isinstance(raw.get("product_catalog"), list):
                cat = self._from_legacy_product_catalog(raw["product_catalog"])
                cat["version"] = _safe_version(raw.get("version", 1))
                return cat

            if isinstance(raw.get("categories"), list):
                return {
                    "version": _safe_version(raw.get("version", 1)),
                    "categories": raw.get("categories") or [],
                }

            return {"version": 1, "categories": []}

        except FileNotFoundError:
            return {"version": 1, "categories": []}

    def _normalize_catalog(self, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            return {"version": 1, "categories": []}

        def _safe_version(v: Any) -> int:
            try:
                return int(v)
            except Exception:
                return 1

        if isinstance(raw.get("product_catalog"), list):
            cat = self._from_legacy_product_catalog(raw["product_catalog"])
            cat["version"] = _safe_version(raw.get("version", 1))
            return cat

        if isinstance(raw.get("categories"), list):
            return {
                "version": _safe_version(raw.get("version", 1)),
                "categories": raw.get("categories") or [],
            }

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
                stock_str = str(item.get("stock") or "").strip().lower()
                in_stock = not any(x in stock_str for x in ("out", "sold", "no"))

                base = f"{cat_id}_{_slug_id(raw_name)}"
                sku = base
                i = 2
                while sku in used_skus:
                    sku = f"{base}_{i}"
                    i += 1
                used_skus.add(sku)

                subcat = str(item.get("subcategory") or "").strip()

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
            cname = str(cat.get("name") or "").strip()
            if not cid:
                continue

            self._cat_index[cid] = cat
            cat_tokens = _tokenize(cid) + _tokenize(cname)

            for item in cat.get("items") or []:
                sku = str(item.get("sku") or "").strip()
                if not sku:
                    continue

                raw_tags = item.get("tags") or []
                norm_tags: List[str] = []
                token_pool: List[str] = []

                # item tags
                for t in raw_tags:
                    nt = _norm_text(str(t))
                    if not nt:
                        continue
                    if nt not in norm_tags:
                        norm_tags.append(nt)

                    for token in _tokenize(nt):
                        if token not in token_pool:
                            token_pool.append(token)

                # category id/name tokens
                for tok in cat_tokens:
                    if tok not in token_pool:
                        token_pool.append(tok)
                    if tok not in norm_tags:
                        norm_tags.append(tok)

                # product name tokens
                name = str(item.get("name") or "")
                name_tokens = _tokenize(name)
                for tok in name_tokens:
                    if tok not in token_pool:
                        token_pool.append(tok)

                entry = {
                    **item,
                    "_category_id": cid,
                    "_category_name": cname,
                    "_norm_name": _norm_text(name),
                    "_norm_tags": norm_tags,
                    "_name_tokens": name_tokens,
                    "_all_tokens": token_pool,
                }

                self._sku_index[sku] = entry

                for tok in token_pool:
                    self._tag_index.setdefault(tok, []).append(entry)

    # --------------- PUBLIC API (AUTO REFRESH) -----------------

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

    def search(self, text=None, tags=None, limit=10, query=None):
        """
        Smarter search:
        - tags are primary hints, but fuzzy/partial matching is allowed
        - text is split into tokens and matched against name/tags/category
        - supports typo-ish inputs like 'chciken'
        """
        self._refresh()

        limit = max(1, min(int(limit or 10), 50))
        text_q = _norm_text(text or query or "")
        text_tokens = _tokenize(text_q)
        tag_qs = [_norm_text(t) for t in (tags or []) if t]
        tag_tokens: List[str] = []
        for t in tag_qs:
            for tok in _tokenize(t):
                if tok not in tag_tokens:
                    tag_tokens.append(tok)

        query_tokens: List[str] = []
        for tok in text_tokens + tag_tokens:
            if tok not in query_tokens:
                query_tokens.append(tok)

        # no filters -> return all ranked lightly by stock/name
        if not text_q and not query_tokens:
            items = list(self._sku_index.values())
            items.sort(key=lambda x: (bool(x.get("in_stock", True)), x.get("name") or ""), reverse=True)
            return items[:limit]

        candidates: Dict[str, Tuple[int, Dict[str, Any]]] = {}

        # First pass: direct token-index hits
        for qtok in query_tokens:
            direct_hits = self._tag_index.get(qtok, [])
            for item in direct_hits:
                score = self._score(item, text_q=text_q, query_tokens=query_tokens)
                prev = candidates.get(item["sku"])
                if prev is None or score > prev[0]:
                    candidates[item["sku"]] = (score, item)

        # Second pass: broader scan for partial/fuzzy name matches
        for item in self._sku_index.values():
            score = self._score(item, text_q=text_q, query_tokens=query_tokens)
            if score <= 0:
                continue
            prev = candidates.get(item["sku"])
            if prev is None or score > prev[0]:
                candidates[item["sku"]] = (score, item)

        results = sorted(candidates.values(), key=lambda x: x[0], reverse=True)
        return [item for _, item in results[:limit]]

    def _score(self, item: Dict[str, Any], text_q: str, query_tokens: List[str]) -> int:
        score = 0
        name = item.get("_norm_name") or ""
        name_tokens = item.get("_name_tokens") or []
        all_tokens = item.get("_all_tokens") or []
        category_id = str(item.get("_category_id") or "").lower()
        category_name = _norm_text(item.get("_category_name") or "")

        # full phrase boosts
        if text_q:
            if name == text_q:
                score += 14
            elif name.startswith(text_q):
                score += 10
            elif text_q in name:
                score += 7

            if text_q == category_id or text_q == category_name:
                score += 9
            elif text_q in category_name:
                score += 5

        # token-based scoring
        for q in query_tokens:
            # exact token in name
            if q in name_tokens:
                score += 6
                continue

            # exact token anywhere
            if q in all_tokens:
                score += 4
                continue

            # partial token match
            if any(q in tok or tok in q for tok in all_tokens):
                score += 2
                continue

            # fuzzy token match
            best_sim = 0.0
            for tok in all_tokens:
                sim = _similar(q, tok)
                if sim > best_sim:
                    best_sim = sim

            if best_sim >= 0.90:
                score += 4
            elif best_sim >= 0.82:
                score += 2

        # bonus when multiple query tokens hit
        matched_count = 0
        for q in query_tokens:
            if (
                q in name_tokens
                or q in all_tokens
                or any(q in tok or tok in q for tok in all_tokens)
            ):
                matched_count += 1
        score += matched_count

        # in stock bonus
        if item.get("in_stock", True):
            score += 1

        return score
