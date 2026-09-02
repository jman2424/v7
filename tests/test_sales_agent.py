from __future__ import annotations

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
