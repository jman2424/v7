"""Different business models get grounded, relevant follow-ups and planning context."""
import json
from types import SimpleNamespace

import pytest

from brain_v7 import BrainV7
from service.sales_agent import SalesAgentPolicy
from service.sales_playbook import default_sales_playbook
from service.tenant_sales_context import planning_business_context


def policy(**settings):
    return SalesAgentPolicy(overrides={"sales_playbook": {**default_sales_playbook(), **settings}})


def offering_reply(**item):
    return {"intent": "business_knowledge", "reply": "Configured service — Quote required.",
            "facts": {"items": [{"name": "Configured service", "type": "service", **item}]}}


@pytest.mark.parametrize(("goal", "action", "phrase"), [
    ("request_quote", "request_quote", "prepare a quote"),
    ("book_appointment", "request_appointment", "arrange an appointment"),
    ("start_subscription", "discuss_subscription", "choose a subscription"),
])
def test_selected_generic_offering_uses_business_goal(goal, action, phrase):
    response = policy(offering_type="services", primary_goal=goal, fulfilment_mode="remote").guide(
        offering_reply(), user_text="Tell me about the configured service", session={})
    assert response["agent"]["next_action"] == action
    assert phrase in response["reply"]
    assert "Check delivery" not in response["ui"]["suggested_replies"]
    assert "shopping" not in response["reply"]


def test_remote_product_business_does_not_propose_delivery():
    response = policy(fulfilment_mode="remote").guide(
        {"intent": "price_check", "reply": "Digital guide costs USD 25.", "facts": {}},
        user_text="How much is the digital guide?", session={})
    assert "check delivery" not in response["reply"].lower()
    assert response["agent"]["next_action"] == "arrange_team_handoff"


def test_information_goal_does_not_push_quote_or_restart_discovery():
    response = policy(offering_type="services", primary_goal="answer_questions").guide(
        offering_reply(price_type="quote"), user_text="What does the service cost?", session={})
    assert response["agent"]["next_action"] == "await_customer_question"
    assert response["agent"]["next_question"] == ""


def test_generic_location_answer_stays_in_assistance_stage():
    response = policy(offering_type="services", fulfilment_mode="on_site").guide(
        {"intent": "business_knowledge", "reply": "Mobile service covers the configured area.", "facts": {}},
        user_text="What areas do you cover?", session={})
    assert response["agent"]["stage"] == "assist"
    assert response["agent"]["next_question"] == ""


def test_declining_qualification_stops_repeated_questions():
    agent = policy(offering_type="services", primary_goal="request_quote",
                   qualification_questions=["When do you need the work?"])
    first = agent.guide(offering_reply(), user_text="I need that service", session={})
    declined = agent.guide(offering_reply(), user_text="No thanks", session={"sales_agent": first["agent"]})
    assert declined["agent"]["qualification_complete"] is True
    assert declined["agent"]["next_question"] == ""
    later = agent.guide(offering_reply(), user_text="More information", session={"sales_agent": declined["agent"]})
    assert "When do you need the work?" not in later["reply"]


def test_public_planning_context_is_bounded_and_excludes_private_or_inactive_data():
    offerings = [{"name": f"Public option {index}", "active": True, "type": "service",
                  "price_type": "quote", "description": "x" * 1000} for index in range(50)]
    offerings.append({"name": "Roof inspection", "active": True, "type": "service", "private_notes": "PRIVATE"})
    offerings.append({"name": "Retired roof survey", "active": False, "description": "RETIRED"})
    context = planning_business_context({"business_model": "project_services", "response_guidance": "x" * 900,
        "private_staff_notes": "PRIVATE", "business_core": {"industry": "Surveying", "offerings": offerings,
        "work": [{"customer_reference": "PRIVATE"}], "locations": [], "business_rules": []}}, "roof inspection")
    assert context["business_core"]["offerings"][0]["name"] == "Roof inspection"
    assert len(context["business_core"]["offerings"]) == 8
    assert len(context["response_guidance"]) == 600
    assert "PRIVATE" not in json.dumps(context)
    assert "RETIRED" not in json.dumps(context)


@pytest.mark.parametrize("raw", ["{broken", "[]", "null", '"text"'])
def test_malformed_planning_output_retains_useful_local_price_action(monkeypatch, raw):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plan = BrainV7()._post_process(raw, "How much does a consultation cost?", {}, {})
    # A consultation enquiry goes to the team rather than fabricating a price.
    assert plan["action"] == "HUMAN_HANDOFF"


def test_model_receives_new_preferences_as_data_and_only_public_facts(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"intent":"unknown","action":"ASK_SLOT","needs_clarification":true,"clarification_question":"What outcome do you need?"}'))])

    brain = BrainV7(client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    brain.plan("Help me choose a service", hints={"business": {
        "business_model": "professional_services", "fulfilment_mode": "remote",
        "customer_type": "businesses", "response_guidance": "Ask about the intended outcome.",
        "private_staff_notes": "PRIVATE", "business_core": {"offerings": [{"name": "Strategy review", "active": True}],
        "locations": [], "business_rules": [], "work": [{"title": "PRIVATE"}]}}})
    sent = json.loads(calls[0]["messages"][-1]["content"])["business"]
    assert sent["business_model"] == "professional_services"
    assert sent["fulfilment_mode"] == "remote"
    assert sent["customer_type"] == "businesses"
    assert sent["response_guidance"] == "Ask about the intended outcome."
    assert "PRIVATE" not in json.dumps(sent)
