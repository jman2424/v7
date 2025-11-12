"""
Modes tests: parity across V5/V6/V7 and grounding enforcement.

We don't invoke the full message_handler; instead we call each mode's
plan() and rewrite() with realistic 'ctx' structures that would be
assembled upstream after deterministic retrieval.
"""

from __future__ import annotations
import pytest

from ai_modes import make_v5, make_v6, make_v7  # type: ignore


# ---- Shared context helpers ----

def ctx_base():
    return {
        "tenant": "EXAMPLE",
        "channel": "web",
        "session": {"id": "s123", "postcode": "E1 6AN"},
        "style": {"concise": True},
    }


def test_v5_minimal_rewrite_no_fabrication():
    v5 = make_v5()
    draft = "we deliver to e1 6an. free over £50."
    out = v5.rewrite(draft, ctx_base())
    # V5 only polishes minimally — keeps content intact
    assert "deliver to e1 6an" in out.lower()
    # Should not append hallucinated claims
    assert "click here" not in out.lower()


def test_v6_clarifier_when_missing_entities():
    v6 = make_v6(prompts={"clarifiers": {"price_check": "Which SKU should I check?"}})
    # Missing SKU in a price check intent → clarifier
    plan = v6.plan("how much?", {"intent": "price_check", **ctx_base()})
    assert plan["constraints"]["no_fabrication"] is True
    msg = v6.rewrite("Could you clarify?", {"intent": "price_check", "facts": {}, **ctx_base()})
    assert "sku" in msg.lower() or "which" in msg.lower()


def test_v6_formats_delivery_when_facts_present():
    v6 = make_v6()
    facts = {"delivery": {"postcode": "E1 6AN", "rule": {"min_order": 25.0, "fee": 3.5}, "summary": "Min £25, £3.50 fee."}}
    txt = v6.rewrite("", {"intent": "check_delivery", "facts": facts, **ctx_base()})
    assert "deliver to e1 6an" in txt.lower()
    assert "min £25" in txt.lower() or "£3.50" in txt


def test_v7_tool_plan_for_search_and_delivery():
    v7 = make_v7()
    # Delivery: no postcode → plan should request clarification
    p1 = v7.plan("Do you deliver?", {"intent": "check_delivery", "session": {}, **ctx_base()})
    assert p1["constraints"]["no_fabrication"] is True
    assert p1["tools"] == [] or p1["constraints"].get("needs_clarification") is True

    # Product search: should plan catalog.search
    p2 = v7.plan("show wings", {"intent": "search_product", "entities": {"query": "wings"}, **ctx_base()})
    tool_names = [t["name"] for t in p2["tools"]]
    assert any("catalog.search" in n for n in tool_names)


def test_v7_grounded_price_reply_and_guardrail():
    v7 = make_v7()
    # Guardrail when SKU missing
    msg = v7.rewrite("", {"intent": "price_check", "facts": {}, "entities": {}, **ctx_base()})
    assert "sku" in msg.lower()

    # Grounded reply when facts present
    facts = {"price": {"sku": "BEEF_MINCE_5FAT_500G", "price": 4.99, "in_stock": True}}
    txt = v7.rewrite("", {"intent": "price_check", "facts": facts, "entities": {"sku": "BEEF_MINCE_5FAT_500G"}, **ctx_base()})
    assert "£4.99" in txt or "4.99" in txt
    assert "in stock" in txt.lower()


def test_v5_v6_v7_parity_simple_faq():
    draft = "Yes. All products are halal and HMC-inspected."
    ctx = {"intent": "faq", "facts": {"faq": {"answer": draft}}, **ctx_base()}
    v5 = make_v5()
    v6 = make_v6()
    v7 = make_v7()

    r5 = v5.rewrite(draft, ctx)
    r6 = v6.rewrite("", ctx)
    r7 = v7.rewrite("", ctx)

    # All should convey the same grounded fact
    lower = lambda s: (s or "").lower()
    assert "halal" in lower(r5)
    assert "halal" in lower(r6)
    assert "halal" in lower(r7)
    # None should introduce external claims
    for r in (r5, r6, r7):
        assert "guaranteed next-day worldwide" not in r.lower()
