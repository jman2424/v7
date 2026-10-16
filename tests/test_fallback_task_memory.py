"""A provider fallback must not erase verified customer choices or constraints."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from service.memory import Memory
from service.message_handler import MessageHandler
from service.sales_agent import SalesAgentPolicy


@pytest.fixture
def task():
    return {
        "stage": "recommend", "offering_ids": ["product:basic", "product:pro"],
        "last_offering_ids": ["product:basic", "product:pro"],
        "selected_offering_id": "product:pro", "requirements": ["my budget is £200"],
        "retired_requirements": ["my budget is £100"], "navigation_ids": ["pro_checkout"],
    }


@pytest.mark.parametrize("intent", [
    "faq", "store_info", "system_error", "system_clarify", "human_handoff",
    "handoff_contact_captured", "grounded_answer",
])
def test_deterministic_turn_retains_verified_task_without_reusing_sales_action(task, intent):
    original = deepcopy(task)
    result = SalesAgentPolicy().guide(
        {"reply": "Here is the configured help.", "intent": intent},
        user_text="What are your opening hours?", session={"sales_agent": task})
    for key in ("offering_ids", "last_offering_ids", "selected_offering_id", "requirements",
                "retired_requirements", "navigation_ids"):
        assert result["agent"][key] == original[key]
    assert task == original
    assert result["agent"]["next_action"] != "open_destination"
    assert not result.get("actions")


@pytest.mark.parametrize("intent,text", [
    ("faq", "How do I cancel?"), ("complaint", "I am dissatisfied"),
    ("policy", "Explain the policy"),
])
def test_support_interruptions_preserve_memory_without_sales_prompts(task, intent, text):
    task.update(qualification_pending=True, qualification_index=0)
    policy = SalesAgentPolicy(overrides={"sales_playbook": {
        "qualification_questions": ["What is your budget?"], "primary_goal": "request_quote"}})
    result = policy.guide({"reply": "Use the configured support process.", "intent": intent},
                          user_text=text, session={"sales_agent": task})
    assert result["reply"] == "Use the configured support process."
    assert result["agent"]["stage"] == "assist"
    assert result["agent"]["offering_ids"] == []
    assert result["agent"]["navigation_ids"] == []
    assert result["agent"]["last_offering_ids"] == task["offering_ids"]
    assert result["agent"]["selected_offering_id"] == "product:pro"
    assert result["agent"]["requirements"] == ["my budget is £200"]
    assert result["ui"]["suggested_replies"] == []


@pytest.mark.parametrize("selected,requirements,retired", [
    (None, [], ["my budget is £100", "my budget is £200"]),
    ("product:basic", ["my budget is £100"], ["my budget is £200"]),
])
def test_new_validated_clear_or_correction_takes_precedence(task, selected, requirements, retired):
    updated = {
        "_validated_grounded": True, "stage": "assist", "next_action": "await_customer_question",
        "next_question": "", "suggested_replies": [], "offering_ids": [],
        "selected_offering_id": selected, "requirements": requirements,
        "retired_requirements": retired, "navigation_ids": [],
    }
    result = SalesAgentPolicy().guide(
        {"reply": "Understood.", "intent": "grounded_answer", "agent": updated},
        user_text="Change my requirements", session={"sales_agent": task})
    assert result["agent"]["selected_offering_id"] == selected
    assert result["agent"]["requirements"] == requirements
    assert result["agent"]["retired_requirements"] == retired
    assert result["agent"]["navigation_ids"] == []


def test_retired_requirements_cannot_reappear_in_fallback(task):
    task["requirements"].append("my budget is £100")
    result = SalesAgentPolicy().guide({"reply": "Open weekdays.", "intent": "faq"},
                                     user_text="Opening hours?", session={"sales_agent": task})
    assert result["agent"]["requirements"] == ["my budget is £200"]


def test_saved_fallback_still_supplies_choice_and_constraints_to_next_turn(task):
    handler = object.__new__(MessageHandler)
    handler.memory = Memory()
    context = SimpleNamespace(session_id="same-customer")
    policy = SalesAgentPolicy()
    first = policy.guide({"reply": "Open weekdays.", "intent": "faq"},
                         user_text="Opening hours?", session={"sales_agent": task})
    handler._save_session(context, {}, first)
    reloaded = handler._load_session(context)
    second = policy.guide({"reply": "The team can help.", "intent": "human_handoff"},
                          user_text="Please get a person", session=reloaded)
    handler._save_session(context, reloaded, second)
    persisted = handler._load_session(context)["sales_agent"]
    assert persisted["selected_offering_id"] == "product:pro"
    assert persisted["requirements"] == ["my budget is £200"]
    assert persisted["retired_requirements"] == ["my budget is £100"]
    assert persisted["last_offering_ids"] == ["product:basic", "product:pro"]


def test_unknown_state_keys_are_not_carried_as_task_authority(task):
    task.update(actions=[{"type": "payment"}], private_notes="private", arbitrary="value")
    result = SalesAgentPolicy().guide({"reply": "Open weekdays.", "intent": "faq"},
                                     user_text="Hours?", session={"sales_agent": task})
    assert not {"actions", "private_notes", "arbitrary"}.intersection(result["agent"])


@pytest.mark.parametrize("text", [
    "Forget the Pro option. I do not want it anymore.", "I don't want Pro",
    "Forget that option", "I do not want it anymore.", "I don't want this plan anymore",
])
def test_provider_down_abandonment_removes_selected_option_and_stale_links(task, text):
    result = SalesAgentPolicy().guide({"reply": "Tell me what you need help with.", "intent": "system_clarify"},
                                     user_text=text, session={"sales_agent": task})
    assert result["agent"]["selected_offering_id"] is None
    assert result["agent"]["offering_ids"] == ["product:basic"]
    assert result["agent"]["last_offering_ids"] == ["product:basic"]
    assert result["agent"]["navigation_ids"] == []
    assert result["agent"]["requirements"] == task["requirements"]
    assert result["agent"]["next_question"] == ""


def test_fallback_rejection_uses_exact_catalogue_name_and_preserves_other_options(task):
    task["selected_offering_id"] = "product:SKU42"
    task["offering_ids"] = ["product:basic", "product:SKU42"]
    task["last_offering_ids"] = list(task["offering_ids"])
    catalog = SimpleNamespace(get_item_by_sku=lambda sku: {"name": "Executive Review"} if sku == "SKU42" else {})
    result = SalesAgentPolicy(catalog=catalog).guide(
        {"reply": "Understood.", "intent": "system_clarify"}, user_text="Remove the Executive Review option",
        session={"sales_agent": task})
    assert result["agent"]["selected_offering_id"] is None
    assert result["agent"]["last_offering_ids"] == ["product:basic"]


@pytest.mark.parametrize("text", [
    "How would I remove Pro?", "What happens if I don't want Pro?", "Is Pro available?",
    "I want to cancel my subscription", "Cancel my subscription. I don't want it anymore.",
    "Not now", "I don't want this problem anymore",
])
def test_questions_support_cancellation_and_qualification_declines_do_not_abandon_choice(task, text):
    result = SalesAgentPolicy().guide({"reply": "Here is the configured help.", "intent": "faq"},
                                     user_text=text, session={"sales_agent": task})
    assert result["agent"]["selected_offering_id"] == "product:pro"
    assert result["agent"]["last_offering_ids"] == task["last_offering_ids"]


def test_abandonment_does_not_become_an_answer_to_pending_qualification(task):
    task.update(qualification_pending=True, qualification_index=0)
    policy = SalesAgentPolicy(overrides={"sales_playbook": {"qualification_questions": ["What is your budget?"]}})
    result = policy.guide({"reply": "Understood.", "intent": "system_clarify"},
                          user_text="I don't want Pro", session={"sales_agent": task})
    assert result["agent"]["selected_offering_id"] is None
    assert result["agent"]["qualification_index"] == 0
    assert not result["agent"].get("qualification_answers")
