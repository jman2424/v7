"""
SalesFlows tests:
- BBQ bundle sizing and totals
- Substitutions when an item is out of stock
"""

from __future__ import annotations
import pytest

from retrieval.storage import Storage  # type: ignore
from retrieval.catalog_store import CatalogStore  # type: ignore
from services.sales_flows import SalesFlows  # type: ignore


def make_catalog(storage: Storage) -> CatalogStore:
    catalog = storage.load_json("EXAMPLE/catalog.json")
    try:
        return CatalogStore(catalog=catalog)
    except TypeError:
        try:
            return CatalogStore(data=catalog)
        except TypeError:
            return CatalogStore(catalog)


def test_bbq_bundle_for_6(storage):
    cs = make_catalog(storage)
    flows = SalesFlows(catalog=cs)
    bundle = flows.bbq_for(6, budget_per_person=10.0)

    assert bundle["title"].startswith("BBQ bundle for 6")
    assert isinstance(bundle["items"], list) and len(bundle["items"]) >= 3
    assert bundle["total"] > 0
    assert "within_budget" in bundle
    # Rough sanity: at least wings or drumsticks present
    names = " ".join(i["name"].lower() for i in bundle["items"])
    assert ("wing" in names) or ("drum" in names) or ("skewer" in names)


def test_suggest_substitutions(storage, monkeypatch):
    cs = make_catalog(storage)

    # Force a known SKU to "out of stock" to trigger alternates
    sku = "CHICK_WINGS_1KG"
    orig_in_stock = cs.in_stock

    def fake_in_stock(x):
        if x == sku:
            return False
        return orig_in_stock(x)

    monkeypatch.setattr(cs, "in_stock", fake_in_stock)

    flows = SalesFlows(catalog=cs)
    subs = flows.suggest_substitutions(sku)
    # Should return a few alternates with same-ish tags (e.g., wings/drumsticks/BBQ)
    assert isinstance(subs, list)
    # Not required but helpful: avoid returning the same SKU
    assert all(s["sku"] != sku for s in subs)
    # Each substitution should include price info
    assert all("unit_price" in s for s in subs)
