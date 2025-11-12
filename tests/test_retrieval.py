"""
Retrieval tests: catalog/policy/geo/faq/synonyms core behaviors.

Uses seeded EXAMPLE tenant data via the fixtures in conftest.py.
"""

from __future__ import annotations
import math
import pytest

from retrieval.storage import Storage  # type: ignore
from retrieval.catalog_store import CatalogStore  # type: ignore
from retrieval.policy_store import PolicyStore  # type: ignore
from retrieval.geo_store import GeoStore  # type: ignore
from retrieval.faq_store import FAQStore  # type: ignore
from retrieval.synonyms_store import SynonymsStore  # type: ignore


# -- Helpers to tolerate minor constructor differences across implementations --

def make_catalog_store(catalog):
    try:
        return CatalogStore(catalog=catalog)
    except TypeError:
        try:
            return CatalogStore(data=catalog)
        except TypeError:
            return CatalogStore(catalog)  # positional

def make_policy_store(delivery):
    try:
        return PolicyStore(delivery=delivery)
    except TypeError:
        try:
            return PolicyStore(data=delivery)
        except TypeError:
            return PolicyStore(delivery)

def make_geo_store(branches):
    try:
        return GeoStore(branches=branches)
    except TypeError:
        try:
            return GeoStore(data=branches)
        except TypeError:
            return GeoStore(branches)

def make_faq_store(faq):
    try:
        return FAQStore(faq=faq)
    except TypeError:
        try:
            return FAQStore(data=faq)
        except TypeError:
            return FAQStore(faq)

def make_synonyms_store(syn):
    try:
        return SynonymsStore(synonyms=syn)
    except TypeError:
        return SynonymsStore(syn)


# --- Tests ---

def test_catalog_search_and_price(storage):
    catalog = storage.load_json("EXAMPLE/catalog.json")
    cs = make_catalog_store(catalog)

    hits = cs.search(query="wings", limit=5)
    assert isinstance(hits, list) and hits
    skus = [h.get("sku") for h in hits]
    assert any("WINGS" in (s or "") for s in skus)

    sku = "CHICK_WINGS_1KG"
    price = cs.price_of(sku)
    assert isinstance(price, (int, float)) and price > 0
    assert cs.in_stock(sku) is True
    item = cs.get_item_by_sku(sku)
    assert item and item.get("name", "").lower().find("wings") >= 0


def test_policy_delivery_rules(storage):
    delivery = storage.load_json("EXAMPLE/delivery.json")
    ps = make_policy_store(delivery)

    # E1 area covered
    rule = ps.delivery_rule_for("E1 6AN")
    assert rule and rule.get("min_order") == 25.0
    assert 3.0 <= rule.get("fee", 0) <= 4.0

    # Non-covered area should return None / falsy
    miss = ps.delivery_rule_for("SW1A 1AA")
    assert not miss


def test_geo_nearest_branch(storage):
    branches = storage.load_json("EXAMPLE/branches.json")
    gs = make_geo_store(branches)

    # close to East London branch
    near = gs.nearest(51.515, -0.07)
    assert near and (near.get("id") or "").startswith("east")
    assert near.get("distance_km") is None or near.get("distance_km") < 2.5

    # Out-of-range query with small radius
    far = gs.nearest(51.515, -0.07, radius_km=0.1)
    assert far is None


def test_faq_best_match(storage):
    faq = storage.load_json("EXAMPLE/faq.json")
    fs = make_faq_store(faq)

    ans = fs.best_match("What time do you open on Sunday?")
    assert ans and "Sun" in ans.get("answer", "") or "10:00" in (ans.get("answer") or "")

    deliv = fs.best_match("Do you deliver to E1 6AN?")
    assert deliv and "{delivery_summary}" in deliv.get("answer", "")


def test_synonyms_merge_and_lookup(storage):
    syn = storage.load_json("EXAMPLE/synonyms.json")
    ss = make_synonyms_store(syn)

    # Direct expansion
    exp = ss.expand_terms(["flapper", "grill"])
    # Should include canonical terms "wing" and "bbq" (or close variants)
    joined = " ".join(exp).lower()
    assert "wing" in joined and "bbq" in joined or "barbecue" in joined

    # Merge new suggestions (simulate self-repair)
    new_map = {"bbq": ["cook out", "braai"]}
    ss.merge_suggestions(new_map)
    exp2 = ss.expand_terms(["braai"])
    assert "bbq" in " ".join(exp2).lower()
