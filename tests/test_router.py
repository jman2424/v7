"""
Router tests: intent/entity extraction and clarifier decisions.

Covers:
- Delivery intent + postcode normalization
- Product search intent with synonyms influence
- Price check intent requiring SKU clarifier
"""

from __future__ import annotations
import re
import pytest

from services import validators  # normalize_postcode
from retrieval.synonyms_store import SynonymsStore

# Attempt to import Router (your real implementation)
from services.router import Router  # type: ignore


@pytest.fixture()
def synonyms_store():
    # Minimal mapping echoing business/EXAMPLE/synonyms.json
    synonyms = {
        "bbq": ["barbecue", "grill", "cookout"],
        "wing": ["flapper", "wingette"],
        "kofta": ["seekh", "skewer", "kebab"],
        "drumstick": ["leg piece", "drum"],
    }
    return SynonymsStore(synonyms=synonyms)


@pytest.fixture()
def router(synonyms_store):
    # Router may accept dependencies via kwargs; pass what we have.
    try:
        return Router(synonyms=synonyms_store)
    except TypeError:
        return Router()  # fallback


def test_delivery_intent_with_postcode(router):
    text = "Do you deliver to E1 6AN?"
    out = router.route(text)  # type: ignore[attr-defined]
    assert isinstance(out, dict)
    # Intent should be delivery-related
    intent = (out.get("intent") or "").lower()
    assert intent in {"check_delivery", "ask_postcode", "delivery_check", "delivery"}
    # Entities should include normalized postcode if recognized
    ents = out.get("entities") or {}
    pc = ents.get("postcode")
    if pc:
        assert validators.normalize_postcode(pc) == "E1 6AN"


def test_delivery_intent_without_postcode_needs_clarifier(router):
    text = "Do you deliver?"
    out = router.route(text)  # type: ignore[attr-defined]
    intent = (out.get("intent") or "").lower()
    assert intent in {"check_delivery", "ask_postcode", "delivery"}
    ents = out.get("entities") or {}
    assert not ents.get("postcode")  # missing postcode
    # Router may signal clarification in various ways; accept either flag or low confidence
    need_clar = out.get("need_clarification") or out.get("clarify") or False
    conf = out.get("confidence")
    assert need_clar or (isinstance(conf, (int, float)) and conf < 0.75)


def test_product_search_with_synonym_influence(router):
    # "flapper" is a synonym for wing -> should map to product search
    text = "Got any flappers for the BBQ?"
    out = router.route(text)  # type: ignore[attr-defined]
    intent = (out.get("intent") or "").lower()
    assert intent in {"search_product", "browse_category", "product_search"}
    ents = out.get("entities") or {}
    q = (ents.get("query") or "").lower()
    tags = [t.lower() for t in (ents.get("tags") or [])]
    # Either query or tags should reflect the canonical term (wing/wings)
    assert ("wing" in q or "wings" in q) or ("wing" in tags or "wings" in tags)


def test_price_check_requires_sku(router):
    # No SKU provided → same intent but needs clarification
    out = router.route("What's the price?")  # type: ignore[attr-defined]
    intent = (out.get("intent") or "").lower()
    assert intent in {"price_check", "price", "check_price"}
    ents = out.get("entities") or {}
    assert not ents.get("sku")
    need = out.get("need_clarification") or out.get("clarify") or False
    conf = out.get("confidence")
    assert need or (isinstance(conf, (int, float)) and conf < 0.75)


def test_price_check_extracts_sku(router):
    out = router.route("Price for BEEF_MINCE_5FAT_500G?")  # type: ignore[attr-defined]
    intent = (out.get("intent") or "").lower()
    assert intent in {"price_check", "check_price"}
    ents = out.get("entities") or {}
    sku = ents.get("sku")
    assert sku and re.match(r"[A-Z0-9_]{6,}", sku)
