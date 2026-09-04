from __future__ import annotations

import logging
import shutil
from pathlib import Path

from service.sales_agent import SalesAgentPolicy


def test_sales_agent_turns_catalog_results_into_a_recommendation_step():
    policy = SalesAgentPolicy()
    response = policy.guide(
        {
            "reply": "Here are some options. Anything else you'd like to check?",
            "intent": "search_product",
            "facts": {
                "items": [
                    {"name": "Chicken Wings"},
                    {"name": "Chicken Thighs"},
                ]
            },
            "ui": {},
        },
        user_text="show chicken",
        session={},
    )

    assert response["agent"]["stage"] == "recommend"
    assert response["agent"]["next_action"] == "compare_or_price_selection"
    assert response["ui"]["suggested_replies"] == ["Chicken Wings", "Chicken Thighs"]
    assert "Anything else" not in response["reply"]
    assert "Which option would you like" in response["reply"]


def test_sales_agent_does_not_repeat_an_existing_product_selection_prompt():
    policy = SalesAgentPolicy()
    response = policy.guide(
        {
            "reply": "Here are some options. Tell me the number you like and I can give you prices.",
            "intent": "search_product",
            "facts": {"items": [{"name": "Chicken Wings"}]},
        },
        user_text="show chicken",
        session={},
    )

    assert response["agent"]["stage"] == "recommend"
    assert response["reply"].count("Which option would you like") == 0


def test_sales_agent_moves_delivery_eligibility_to_product_selection():
    policy = SalesAgentPolicy()
    response = policy.guide(
        {
            "reply": "Yes, we deliver to E1 6AN.",
            "intent": "check_delivery",
            "facts": {"delivery": {"postcode": "E1 6AN", "rule": {"fee": 3.5}}},
            "entities": {"postcode": "E1 6AN"},
        },
        user_text="Do you deliver to E1 6AN?",
        session={"sales_agent": {"stage": "qualify"}},
    )

    assert response["agent"]["stage"] == "convert"
    assert response["agent"]["previous_stage"] == "qualify"
    assert response["agent"]["postcode_confirmed"] is True
    assert response["ui"]["suggested_replies"] == ["Nearest branch"]


def test_sales_agent_leaves_a_grounded_faq_answer_uninterrupted():
    policy = SalesAgentPolicy()
    response = policy.guide(
        {
            "reply": "Every Northstar Travel bag includes a two-year warranty.",
            "intent": "faq",
            "facts": {"faq": {"answer": "Every Northstar Travel bag includes a two-year warranty."}},
        },
        user_text="Does every bag include a warranty?",
        session={},
    )

    assert response["agent"]["stage"] == "assist"
    assert response["agent"]["next_question"] == ""
    assert response["reply"] == "Every Northstar Travel bag includes a two-year warranty."


def test_greeting_reaches_agent_instead_of_the_short_input_guard(app):
    result = app.container.handler.handle(
        "hi",
        tenant="EXAMPLE",
        session_id="agent-greeting",
        channel="web",
    )

    assert result["intent"] == "greeting"
    assert result["agent"]["stage"] == "discover"
    assert "EXAMPLE Halal Butchers sales assistant" in result["reply"]
    assert "Tariq Halal" not in result["reply"]


def test_v7_uses_each_tenant_catalog_and_currency_without_butcher_copy(app):
    business_root = Path(app.container.storage.business_root)
    tenant = "TRAVEL"
    shutil.copytree(business_root / "EXAMPLE", business_root / tenant)
    storage = app.container.storage
    storage.write_json(
        tenant,
        "catalog.json",
        {
            "version": 1,
            "currency": "USD",
            "categories": [
                {
                    "id": "bags",
                    "name": "Travel bags",
                    "items": [
                        {
                            "sku": "CANVAS_PACK",
                            "name": "Canvas Backpack",
                            "price": 149.0,
                            "unit": "each",
                            "tags": ["travel", "backpack", "canvas"],
                            "in_stock": True,
                        },
                        {
                            "sku": "CABIN_CASE",
                            "name": "Cabin Case",
                            "price": 219.0,
                            "unit": "each",
                            "tags": ["travel", "luggage"],
                            "in_stock": True,
                        },
                        {
                            "sku": "WEEKENDER_DUFFEL",
                            "name": "Weekender Duffel",
                            "price": 189.0,
                            "unit": "each",
                            "tags": ["travel", "luggage", "duffel"],
                            "in_stock": False,
                        },
                        {
                            "sku": "CARRY_ON_DUFFEL",
                            "name": "Carry-on Duffel",
                            "price": 179.0,
                            "unit": "each",
                            "tags": ["travel", "luggage", "duffel"],
                            "in_stock": True,
                        },
                    ],
                }
            ],
        },
        schema="catalog.schema.json",
        snapshot=False,
    )
    storage.write_json(
        tenant,
        "store_info.json",
        {"name": "Northstar Travel", "about": "", "email": "", "phone": "", "website": "", "certifications": [], "social": {}},
        schema="store_info.schema.json",
        snapshot=False,
    )

    handler = app.container.for_tenant(tenant).handler
    product = handler.handle("I need a canvas backpack", tenant=tenant, session_id="travel-product", channel="web")
    catalog = handler.handle("show all products", tenant=tenant, session_id="travel-catalog", channel="web")
    comparison = handler.handle(
        "Compare Canvas Backpack and Cabin Case",
        tenant=tenant,
        session_id="travel-comparison",
        channel="web",
    )
    unavailable = handler.handle(
        "Do you have the Weekender Duffel?",
        tenant=tenant,
        session_id="travel-unavailable",
        channel="web",
    )
    help_reply = handler.handle("help", tenant=tenant, session_id="travel-help", channel="web")

    assert "Canvas Backpack" in product["reply"]
    assert "$149.00" in product["reply"]
    assert len(catalog["facts"]["items"]) == 4
    assert comparison["intent"] == "compare_products"
    assert comparison["entities"]["comparison_skus"] == ["CANVAS_PACK", "CABIN_CASE"]
    assert "Canvas Backpack: $149.00, in stock." in comparison["reply"]
    assert "Cabin Case: $219.00, in stock." in comparison["reply"]
    assert comparison["agent"]["next_action"] == "select_compared_product"
    assert unavailable["intent"] == "unavailable_product"
    assert unavailable["facts"]["unavailable_product"]["sku"] == "WEEKENDER_DUFFEL"
    assert unavailable["entities"]["alternative_skus"][0] == "CARRY_ON_DUFFEL"
    assert "Weekender Duffel is currently out of stock." in unavailable["reply"]
    assert "Carry-on Duffel" in unavailable["reply"]
    assert "$179.00" in unavailable["reply"]
    assert unavailable["agent"]["next_action"] == "select_available_alternative"
    assert unavailable["ui"]["catalog_items"][0]["sku"] == "CARRY_ON_DUFFEL"
    assert all(item["sku"] != "WEEKENDER_DUFFEL" for item in unavailable["ui"]["catalog_items"])
    assert "chicken" not in help_reply["reply"].lower()
    assert "lamb" not in help_reply["reply"].lower()


def test_v7_answers_a_tenant_faq_without_requiring_a_model(app):
    business_root = Path(app.container.storage.business_root)
    tenant = "TRAVEL_FAQ"
    shutil.copytree(business_root / "EXAMPLE", business_root / tenant)
    storage = app.container.storage
    storage.write_json(
        tenant,
        "faq.json",
        [
            {
                "q": "What warranty do your bags include?",
                "a": "Every Northstar Travel bag includes a two-year warranty.",
                "tags": ["warranty", "bags"],
            }
        ],
        schema="faq.schema.json",
        snapshot=False,
    )
    storage.write_json(
        tenant,
        "store_info.json",
        {"name": "Northstar Travel", "about": "Travel bags for frequent flyers.", "email": "hello@northstar.example", "phone": "+1 212 555 0198", "website": "https://northstar.example", "certifications": [], "social": {}},
        schema="store_info.schema.json",
        snapshot=False,
    )

    response = app.container.for_tenant(tenant).handler.handle(
        "Does every bag include a warranty?",
        tenant=tenant,
        session_id="travel-faq",
        channel="web",
    )

    assert response["intent"] == "faq"
    assert response["facts"]["faq"]["answer"] == "Every Northstar Travel bag includes a two-year warranty."
    assert response["reply"] == "Every Northstar Travel bag includes a two-year warranty."
    assert response["agent"]["stage"] == "assist"

    contact = app.container.for_tenant(tenant).handler.handle(
        "How can I contact you?",
        tenant=tenant,
        session_id="travel-contact",
        channel="web",
    )

    assert contact["intent"] == "store_info"
    assert "+1 212 555 0198" in contact["reply"]
    assert "hello@northstar.example" in contact["reply"]


def test_v7_shows_only_active_tenant_offers_without_a_model(app):
    storage = app.container.storage
    storage.write_json(
        "EXAMPLE",
        "offers.json",
        [
            {
                "id": "wings_weekend",
                "title": "Weekend wings saving",
                "description": "Save 10% on Chicken Wings.",
                "code": "WINGS10",
                "active": True,
                "starts_on": "2026-01-01",
                "ends_on": "2099-12-31",
                "product_skus": ["CHICK_WINGS_1KG"],
            },
            {
                "id": "expired_offer",
                "title": "Expired saving",
                "description": "This must not be shown.",
                "active": True,
                "ends_on": "2000-01-01",
                "product_skus": [],
            },
            {
                "id": "future_offer",
                "title": "Future saving",
                "description": "This must not be shown yet.",
                "active": True,
                "starts_on": "2099-01-01",
                "product_skus": [],
            },
        ],
        schema="offers.schema.json",
        snapshot=False,
    )
    app.container.invalidate_tenant("EXAMPLE")

    offer = app.container.handler.handle(
        "Is Chicken Wings (1kg) on offer?",
        tenant="EXAMPLE",
        session_id="wings-offer",
        channel="web",
    )
    no_offer = app.container.handler.handle(
        "Is Chicken Thigh (Bone-in, 1kg) on offer?",
        tenant="EXAMPLE",
        session_id="thigh-offer",
        channel="web",
    )

    assert offer["intent"] == "offers"
    assert [item["id"] for item in offer["facts"]["offers"]["items"]] == ["wings_weekend"]
    assert "Save 10% on Chicken Wings" in offer["reply"]
    assert "code: WINGS10" in offer["reply"]
    assert "ends 2099-12-31" in offer["reply"]
    assert "Expired saving" not in offer["reply"]
    assert offer["agent"]["next_action"] == "offer_product_guidance"
    assert no_offer["facts"]["offers"]["items"] == []
    assert "do not have a current offer recorded for Chicken Thigh" in no_offer["reply"]


def test_v7_applies_the_saved_tenant_response_length(app):
    storage = app.container.storage
    storage.write_json(
        "EXAMPLE",
        "faq.json",
        [
            {
                "q": "What is your returns policy?",
                "a": "Returns are accepted within 30 days. Please keep your receipt.",
                "tags": ["returns"],
            }
        ],
        schema="faq.schema.json",
        snapshot=False,
    )
    storage.write_json(
        "EXAMPLE",
        "overrides.json",
        {"tone": {"style": "concise", "max_sentences": 1}},
        snapshot=False,
    )
    app.container.invalidate_tenant("EXAMPLE")

    response = app.container.handler.handle(
        "What is your returns policy?",
        tenant="EXAMPLE",
        session_id="tenant-tone",
        channel="web",
    )

    assert response["intent"] == "faq"
    assert response["reply"] == "Returns are accepted within 30 days."


def test_v7_captures_a_voluntary_handoff_phone_in_the_tenant_lead(app):
    handler = app.container.handler
    session_id = "handoff-contact"

    handoff = handler.handle(
        "I need to speak to someone",
        tenant="EXAMPLE",
        session_id=session_id,
        channel="web",
    )
    captured = handler.handle(
        "Please call me on 07123456789 about delivery",
        tenant="EXAMPLE",
        session_id=session_id,
        channel="web",
    )
    leads = app.container.crm.list_leads(tenant="EXAMPLE")

    assert handoff["intent"] == "human_handoff"
    assert "phone number or email" in handoff["reply"]
    assert captured["intent"] == "handoff_contact_captured"
    assert captured["entities"]["phone"] == "+447123456789"
    assert captured["agent"]["next_action"] == "team_follow_up"
    assert any(lead["phone"] == "+447123456789" for lead in leads)


def test_v7_captures_a_voluntary_handoff_name_in_the_tenant_lead(app):
    handler = app.container.handler
    session_id = "handoff-named-contact"

    handler.handle(
        "I need to speak to someone",
        tenant="EXAMPLE",
        session_id=session_id,
        channel="web",
    )
    captured = handler.handle(
        "My name is Alex Morgan and you can reach me at alex@example.test",
        tenant="EXAMPLE",
        session_id=session_id,
        channel="web",
    )
    leads = app.container.crm.list_leads(tenant="EXAMPLE")

    assert captured["intent"] == "handoff_contact_captured"
    assert captured["entities"]["name"] == "Alex Morgan"
    assert captured["entities"]["email"] == "alex@example.test"
    assert any(lead["name"] == "Alex Morgan" and lead["email"] == "alex@example.test" for lead in leads)


def test_v7_keeps_customer_content_out_of_operational_logs(app, caplog):
    caplog.set_level(logging.INFO)
    caplog.clear()
    customer_message = "Please call +447123456789 or email customer@example.test"
    session_id = "customer-session-private"

    app.container.handler.handle(
        customer_message,
        tenant="EXAMPLE",
        session_id=session_id,
        channel="web",
    )

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert customer_message not in logs
    assert "+447123456789" not in logs
    assert "customer@example.test" not in logs
    assert session_id not in logs
    assert "text_len=" in logs
