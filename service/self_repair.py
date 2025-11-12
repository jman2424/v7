"""
Self-repair / validation service

Goals:
- Validate tenant JSON (lightweight; full schema check already in storage layer)
- Detect catalog holes: zero-price, duplicate SKUs, empty categories
- Suggest synonyms from frequent unmatched tokens
- Detect delivery gaps (coverage prefixes vs. branches)
- Produce a human-readable report for /__diag/* routes
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from retrieval.catalog_store import CatalogStore  # type: ignore
from retrieval.synonyms_store import SynonymsStore  # type: ignore
from retrieval.policy_store import PolicyStore  # type: ignore
from retrieval.geo_store import GeoStore  # type: ignore


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{1,}")


@dataclass
class SelfRepairService:
    catalog: CatalogStore
    synonyms: SynonymsStore
    policy: PolicyStore
    geo: GeoStore

    # -------- public API --------

    def run(self) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "catalog": self._check_catalog(),
            "delivery": self._check_delivery(),
            "synonyms": self._suggest_synonyms(),
        }
        report["summary"] = self._summarize(report)
        return report

    # -------- catalog checks --------

    def _check_catalog(self) -> Dict[str, Any]:
        issues: List[str] = []
        seen_skus = set()
        zero_price = []
        empty_cats = []

        cats = self.catalog.categories()
        for cat in cats:
            items = cat.get("items") or []
            if not items:
                empty_cats.append(cat.get("id") or cat.get("name"))
            for it in items:
                sku = (it.get("sku") or "").strip()
                if not sku:
                    issues.append(f"Item without SKU in category {cat.get('id') or cat.get('name')}")
                elif sku in seen_skus:
                    issues.append(f"Duplicate SKU: {sku}")
                else:
                    seen_skus.add(sku)
                try:
                    price = float(it.get("price"))
                    if price <= 0:
                        zero_price.append(sku or it.get("name"))
                except Exception:
                    issues.append(f"Invalid price for SKU {sku or it.get('name')}")

        return {"issues": issues, "zero_price": zero_price, "empty_categories": empty_cats}

    # -------- delivery checks --------

    def _check_delivery(self) -> Dict[str, Any]:
        prefixes = set(self.geo.coverage_prefixes())
        branches = self.geo.branches()
        branch_outwards = set()
        for b in branches:
            pc = (b.get("postcode") or "").replace(" ", "").upper()
            if len(pc) > 3:
                branch_outwards.add(pc[:-3])
        missing = sorted(prefixes - branch_outwards)
        return {"coverage_prefixes": sorted(prefixes), "branch_outward_codes": sorted(branch_outwards), "gaps": missing}

    # -------- synonyms suggestions --------

    def _suggest_synonyms(self, top_n: int = 10) -> Dict[str, List[str]]:
        # Build a token universe from catalog names and tags
        universe = set()
        for it in self.catalog.list_all_items():
            for t in _TOKEN_RE.findall(it.get("name") or ""):
                universe.add(t.lower())
            for tag in (it.get("tags") or []):
                for t in _TOKEN_RE.findall(tag):
                    universe.add(t.lower())

        # Derive candidate misspellings/variants (simple heuristics)
        suggestions: Dict[str, List[str]] = {}
        for term in sorted(universe):
            canon = self.synonyms.canonical(term)
            if canon != term:
                continue  # already mapped
            # naive variants: plurals and hyphen removal
            variants = set()
            if term.endswith("s") and len(term) > 3:
                variants.add(term[:-1])
            if "-" in term:
                variants.add(term.replace("-", ""))
            if variants:
                suggestions[term] = sorted(variants)

            if len(suggestions) >= top_n:
                break
        return suggestions

    # -------- summary --------

    @staticmethod
    def _summarize(rep: Dict[str, Any]) -> str:
        cat = rep.get("catalog", {})
        deliv = rep.get("delivery", {})
        parts = []
        if cat.get("issues") or cat.get("zero_price") or cat.get("empty_categories"):
            parts.append("Catalog needs attention")
        if deliv.get("gaps"):
            parts.append("Delivery gaps detected")
        if not parts:
            return "All checks passed"
        return "; ".join(parts)
