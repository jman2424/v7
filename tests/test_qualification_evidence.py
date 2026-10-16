"""Qualification records customer evidence rather than counting vague turns."""
from types import SimpleNamespace

import pytest

from service.memory import Memory
from service.message_handler import MessageHandler
from service.sales_agent import SalesAgentPolicy


QUESTIONS = ["What is your budget?", "When do you need it completed?"]


def policy():
    return SalesAgentPolicy(overrides={"sales_playbook": {
        "offering_type": "services", "primary_goal": "book_consultation",
        "qualification_questions": QUESTIONS}})


def pending():
    return {"stage": "qualify", "next_action": "ask_qualification_question",
            "qualification_pending": True, "qualification_index": 0}


def turn(text, previous, *, intent="unknown", facts=None):
    return policy().guide({"reply": "Here is the information.", "intent": intent, "facts": facts or {}},
                          user_text=text, session={"sales_agent": previous})


@pytest.mark.parametrize("text", [
    "I have no idea yet", "I still have no idea", "I don't know", "Not sure yet",
    "I haven't decided", "No budget yet", "Not yet", "Maybe", "N/A",
])
def test_unknown_detail_is_recorded_without_completing_or_repeating_qualification(text):
    result = turn(text, pending())
    agent = result["agent"]
    assert agent["qualification_complete"] is False
    assert agent["qualification_paused"] is True
    assert agent["qualification_answers"][QUESTIONS[0]] == {"status": "unknown", "evidence": text}
    assert agent["next_question"] == ""
    assert result["reply"] == "Here is the information."
    for followup in ("Thanks!", "What are your hours?", "Show more services"):
        continued = turn(followup, agent)
        assert continued["agent"]["qualification_answers"] == agent["qualification_answers"]
        assert continued["agent"]["qualification_index"] == 0
        assert continued["agent"]["next_question"] == ""


def test_concrete_answers_resume_after_unknown_and_finish_with_evidence():
    unknown = turn("I don't know", pending())["agent"]
    budget = turn("My budget is £500", unknown)["agent"]
    assert budget["qualification_answers"][QUESTIONS[0]] == {
        "status": "answered", "evidence": "My budget is £500"}
    assert budget["qualification_index"] == 1
    assert budget["next_question"] == QUESTIONS[1]
    final = turn("Next Friday", budget)["agent"]
    assert final["qualification_answers"][QUESTIONS[1]] == {
        "status": "answered", "evidence": "Next Friday"}
    assert final["qualification_complete"] is True
    assert final["qualification_pending"] is False
    assert final["next_action"] == "book_consultation"


@pytest.mark.parametrize("text", ["No thanks", "Not now", "Skip this question", "I'd rather not say",
                                  "I prefer not to share", "I don't want to share my budget",
                                  "I'd rather not answer that", "No thanks, please", "Stop asking", "Stop"])
def test_decline_persists_without_false_completion_or_blocking_help(text):
    declined = turn(text, pending())["agent"]
    assert declined["qualification_complete"] is False
    assert declined["qualification_declined"] is True
    assert declined["qualification_answers"][QUESTIONS[0]]["status"] == "declined"
    result = turn("Tell me more about the service", declined, intent="business_knowledge",
                  facts={"items": [{"name": "Configured service"}]})
    assert result["reply"] == "Here is the information."
    assert result["agent"]["qualification_declined"] is True
    assert result["agent"]["qualification_complete"] is False
    assert result["agent"]["next_question"] == ""
    assert result["agent"]["next_action"] == "await_customer_question"


def test_declining_qualification_does_not_block_later_handoff():
    declined = turn("No thanks", pending())["agent"]
    result = turn("I want to speak to a person", declined, intent="human_handoff")
    assert result["agent"]["stage"] == "handoff"
    assert result["agent"]["next_action"] == "collect_contact_details"
    assert result["agent"]["qualification_declined"] is True


def test_declining_before_the_first_question_suppresses_qualification():
    declined = turn("Not now", {})["agent"]
    assert declined["qualification_declined"] is True
    assert declined["qualification_complete"] is False
    assert declined["next_question"] == ""


def test_obvious_verified_details_are_not_requested_again():
    previous = {"requirements": ["My budget is £500", "I need it next Friday"]}
    result = turn("Show the configured service", previous, intent="business_knowledge",
                  facts={"items": [{"name": "Configured service"}]})
    assert result["agent"]["qualification_complete"] is True
    assert result["agent"]["qualification_answers"][QUESTIONS[0]]["evidence"] == "My budget is £500"
    assert result["agent"]["qualification_answers"][QUESTIONS[1]]["evidence"] == "I need it next Friday"


def test_retired_and_unrelated_details_do_not_answer_questions():
    previous = {"requirements": ["My budget is £500", "I like Friday discounts"],
                "retired_requirements": ["My budget is £500"]}
    result = turn("Show the configured service", previous, intent="business_knowledge",
                  facts={"items": [{"name": "Configured service"}]})
    assert result["agent"]["qualification_answers"] == {}
    assert result["agent"]["next_question"] == QUESTIONS[0]


def test_contact_details_are_not_stored_as_qualification_evidence():
    result = turn("Email me at customer@example.test", pending())
    assert result["agent"]["qualification_answers"] == {}
    assert result["agent"]["qualification_complete"] is False


def test_unknown_and_decline_flags_survive_real_session_serialization():
    handler = object.__new__(MessageHandler)
    handler.memory = Memory()
    context = SimpleNamespace(session_id="qualification-evidence")
    unknown = turn("I don't know", pending())
    handler._save_session(context, {}, unknown)
    saved = handler._load_session(context)["sales_agent"]
    assert saved["qualification_paused"] is True
    assert saved["qualification_answers"][QUESTIONS[0]]["status"] == "unknown"
    declined = turn("No thanks", saved)
    handler._save_session(context, {}, declined)
    saved = handler._load_session(context)["sales_agent"]
    assert saved["qualification_declined"] is True
    assert saved["qualification_complete"] is False
    assert saved["qualification_answers"][QUESTIONS[0]]["status"] == "declined"


def completed_task():
    return {
        "stage": "convert", "next_action": "book_consultation", "qualification_complete": True,
        "qualification_pending": False, "qualification_index": 1,
        "requirements": ["My budget is £100", "I need it next Friday"], "retired_requirements": [],
        "qualification_answers": {
            QUESTIONS[0]: {"status": "answered", "evidence": "My budget is £100"},
            QUESTIONS[1]: {"status": "answered", "evidence": "I need it next Friday"},
        },
    }


@pytest.mark.parametrize("retired_index,replacement", [
    (0, "My budget is now £200"), (1, "I need it next Monday"),
])
def test_validated_correction_retires_old_qualification_evidence_before_next_context(retired_index, replacement):
    from service.grounded_conversation import _agent_state, agent_context_rows

    previous = completed_task()
    old = previous["requirements"][retired_index]
    raw = {"intent": "answer", "stage": "assist", "next_action": "await_customer_question",
           "requirements_update": {"add": [replacement], "remove": [old], "evidence": replacement}}
    # Exercise the actual grounded requirement validator, without any API call.
    validated = _agent_state({"agent": raw}, knowledge={}, sources=[], navigation=[],
                             question=replacement, history=[],
                             context={"previous_agent": previous, "offering_ids": []})
    result = policy().guide({"reply": "Understood.", "intent": "grounded_answer", "agent": validated},
                            user_text=replacement, session={"sales_agent": previous})
    handler = object.__new__(MessageHandler)
    handler.memory = Memory()
    context = SimpleNamespace(session_id="corrected-qualification")
    handler._save_session(context, {}, result)
    saved = handler._load_session(context)["sales_agent"]
    next_context = agent_context_rows({"playbook": {"qualification_questions": QUESTIONS},
                                      "previous_agent": saved}, {})["previous_agent"]
    assert next_context["qualification_complete"] is False
    assert next_context["qualification_index"] == retired_index
    assert QUESTIONS[retired_index] not in next_context["qualification_answers"]
    other = QUESTIONS[1 - retired_index]
    assert next_context["qualification_answers"][other] == previous["qualification_answers"][other]
    assert replacement in next_context["requirements"]
    assert old not in next_context["requirements"]


@pytest.mark.parametrize('with_requirements', [True, False])
def test_validated_reset_removes_all_answered_qualification_evidence(with_requirements):
    from service.grounded_conversation import _agent_state, agent_context_rows

    previous = completed_task()
    if not with_requirements:
        previous['requirements'] = []
    validated = _agent_state({"agent": {
        "intent": "answer", "stage": "assist", "next_action": "await_customer_question",
        "requirements_update": {"clear": True, "evidence": "Start again"},
    }}, knowledge={}, sources=[], navigation=[], question="Start again", history=[],
        context={"previous_agent": previous, "offering_ids": []})
    result = policy().guide({"reply": "Understood.", "intent": "grounded_answer", "agent": validated},
                            user_text="Start again", session={"sales_agent": previous})
    agent = result["agent"]
    next_context = agent_context_rows({"playbook": {"qualification_questions": QUESTIONS},
                                      "previous_agent": agent}, {})["previous_agent"]
    assert agent["qualification_answers"] == {}
    assert next_context["qualification_complete"] is False
    assert next_context["qualification_index"] == 0
    assert next_context.get("qualification_answers", {}) == {}
    assert next_context["requirements"] == []


@pytest.mark.parametrize('index,replacement', [(0, 'My budget is now £200'), (1, 'I need it next Monday')])
def test_new_requirement_invalidates_an_independent_deterministic_answer(index, replacement):
    from service.grounded_conversation import _agent_state

    previous = turn('Next Friday', turn('My budget is £500', pending())['agent'])['agent']
    assert previous['qualification_complete'] is True
    assert not previous.get('requirements')
    validated = _agent_state({'agent': {
        'intent': 'answer', 'stage': 'assist', 'next_action': 'await_customer_question',
        'requirements_update': {'add': [replacement], 'evidence': replacement},
    }}, knowledge={}, sources=[], navigation=[], question=replacement, history=[],
        context={'previous_agent': previous, 'offering_ids': []})
    result = policy().guide({'reply': 'Understood.', 'intent': 'grounded_answer', 'agent': validated},
                            user_text=replacement, session={'sales_agent': previous})['agent']
    assert result['qualification_complete'] is False
    assert result['qualification_index'] == index
    assert QUESTIONS[index] not in result['qualification_answers']
    assert result['qualification_answers'][QUESTIONS[1 - index]] == previous['qualification_answers'][QUESTIONS[1 - index]]
    assert result['requirements'] == [replacement]


def test_clearing_requirements_preserves_an_explicit_qualification_opt_out():
    from service.grounded_conversation import _agent_state

    previous = turn('Stop asking', pending())['agent']
    question = 'Forget those requirements; do not ask me those questions again'
    validated = _agent_state({'agent': {
        'intent': 'answer', 'stage': 'assist', 'next_action': 'await_customer_question',
        'requirements_update': {'clear': True, 'evidence': question},
    }}, knowledge={}, sources=[], navigation=[], question=question, history=[],
        context={'previous_agent': previous, 'offering_ids': []})
    result = policy().guide({'reply': 'Understood.', 'intent': 'grounded_answer', 'agent': validated},
                            user_text=question, session={'sales_agent': previous})['agent']
    assert result['qualification_declined'] is True
    assert result['qualification_complete'] is False
    assert '_reset_qualification' not in result
    followup = turn('Show the configured service', result, intent='business_knowledge',
                    facts={'items': [{'name': 'Configured service'}]})['agent']
    assert followup['next_question'] == ''


def test_existing_stale_fallback_answer_map_cannot_keep_qualification_complete():
    previous = completed_task()
    previous["retired_requirements"] = ["My budget is £100"]
    previous["requirements"] = ["My budget is now £200", "I need it next Friday"]
    result = turn("What are your hours?", previous, intent="faq")
    assert result["agent"]["qualification_complete"] is False
    assert result["agent"]["qualification_index"] == 0
    assert QUESTIONS[0] not in result["agent"]["qualification_answers"]
    assert result["agent"]["qualification_answers"][QUESTIONS[1]]["status"] == "answered"
    assert result["agent"]["next_question"] == ""


@pytest.mark.parametrize("retired,evidence,removed", [
    ("My budget is £100", "£100", True),
    ("£100", "My budget is £100 per month", True),
    ("my budget is £100", "My BUDGET is £100", True),
    ("£10", "My budget is £100", False),
    ("£10", "My budget is £10.50", False),
    ("next Friday", "I need it next Friday", True),
])
def test_retired_qualification_evidence_uses_whole_tokens(retired, evidence, removed):
    assert SalesAgentPolicy._retired_evidence(evidence, [retired]) is removed


@pytest.mark.parametrize("status,evidence", [("unknown", "I don't know"), ("declined", "No thanks")])
def test_retiring_an_answer_preserves_other_unknown_or_declined_evidence(status, evidence):
    previous = completed_task()
    previous["qualification_answers"][QUESTIONS[0]] = {"status": status, "evidence": evidence}
    previous["qualification_declined"] = status == "declined"
    updated = {
        "_validated_grounded": True, "stage": "assist", "next_action": "await_customer_question",
        "next_question": "", "suggested_replies": [], "requirements": [],
        "retired_requirements": list(previous["requirements"]),
    }
    result = policy().guide({"reply": "Understood.", "intent": "grounded_answer", "agent": updated},
                            user_text="Start again", session={"sales_agent": previous})
    assert result["agent"]["qualification_answers"] == {
        QUESTIONS[0]: {"status": status, "evidence": evidence}}
    assert result["agent"]["qualification_complete"] is False
    assert result["agent"]["qualification_declined"] is (status == "declined")


def test_grounded_retirement_invalidates_legacy_completion_without_evidence_map():
    previous = completed_task()
    previous.pop("qualification_answers")
    updated = {"_validated_grounded": True, "stage": "assist", "next_action": "await_customer_question",
               "next_question": "", "suggested_replies": [], "requirements": [],
               "retired_requirements": list(previous["requirements"])}
    result = policy().guide({"reply": "Understood.", "intent": "grounded_answer", "agent": updated},
                            user_text="Start again", session={"sales_agent": previous})
    assert result["agent"]["qualification_complete"] is False
    assert result["agent"]["qualification_index"] == 0
