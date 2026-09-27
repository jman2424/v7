"""Business facts take precedence over general-topic scope hints."""
from types import SimpleNamespace

import pytest

from handlers.handler_v7 import MessageHandlerV7
from retrieval.faq_store import FAQStore


def handler(monkeypatch, **deps):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return MessageHandlerV7(SimpleNamespace(**deps))


@pytest.mark.parametrize("question", ["How does training work?", "What is the drainage process?", "Explain brainstorming"])
def test_scope_hints_match_whole_words(monkeypatch, question):
    assert not handler(monkeypatch)._looks_out_of_scope(question)


def test_business_profile_sets_supported_topics(monkeypatch):
    agent = handler(monkeypatch, business_profile={"name": "Sports coaching", "about": "Sports coaching for local teams."})
    assert not agent._looks_out_of_scope("What sports are covered?")
    assert agent._looks_out_of_scope("What is the bitcoin forecast?")


def test_tenant_faq_is_answered_before_scope_rejection(monkeypatch):
    agent = handler(monkeypatch, faq=FAQStore(faq=[{
        "q": "What happens in rain?", "a": "Rain sessions move into our covered studio.", "tags": ["rain"],
    }]))
    response = agent.handle("What happens in rain?", SimpleNamespace(channel="web"), {})
    assert response["intent"] == "faq"
    assert "covered studio" in response["reply"]


def test_imported_website_facts_are_answered_before_scope_rejection(monkeypatch):
    seen = []

    def answer(question, passages):
        seen.extend(passages)
        return "Weather protection includes covered seating."

    agent = handler(monkeypatch, rewriter=SimpleNamespace(answer_from_website=answer))
    agent.website_knowledge = {"pages": [{"url": "https://example.test/events", "title": "Events",
                                         "text": "Weather protection includes covered seating."}]}
    response = agent.handle("What does weather protection include?", SimpleNamespace(channel="web"), {})
    assert response["intent"] == "website_answer"
    assert "covered seating" in response["reply"]
    assert seen[0]["url"] == "https://example.test/events"


def test_unknown_topics_are_still_rejected_without_model_calls(monkeypatch):
    agent = handler(monkeypatch)
    agent.brain = SimpleNamespace(plan=lambda **kwargs: pytest.fail("Unrelated topics must not call the model"))
    response = agent.handle("What are the latest bitcoin headlines?", SimpleNamespace(channel="web"), {})
    assert response["intent"] == "out_of_scope"


@pytest.mark.parametrize("question", [
    "Do you offer roof surveys?", "Can you offer consultations?", "Could you offer training?",
])
def test_service_offer_questions_use_exact_tenant_faq(monkeypatch, question):
    agent = handler(monkeypatch, faq=FAQStore(faq=[{
        "q": question, "a": "Northstar arranges this service with its specialist team.", "tags": [],
    }]), offers=SimpleNamespace(active=lambda: []))
    agent.brain = SimpleNamespace(plan=lambda **kwargs: pytest.fail("Exact FAQs need no provider call"))
    response = agent.handle(question, SimpleNamespace(channel="web"), {})
    assert response["intent"] == "faq"
    assert "Northstar" in response["reply"]
    assert "no current offers" not in response["reply"]


def test_service_offer_question_uses_imported_website_when_no_faq_exists(monkeypatch):
    agent = handler(monkeypatch, offers=SimpleNamespace(active=lambda: []),
                    rewriter=SimpleNamespace(answer_from_website=lambda question, passages:
                        "Northstar arranges roof surveys with its specialist team."))
    agent.website_knowledge = {"pages": [{"url": "https://example.test/surveys",
        "title": "Roof surveys", "text": "Northstar arranges roof surveys with its specialist team."}]}
    agent.brain = SimpleNamespace(plan=lambda **kwargs: pytest.fail("Imported facts precede the planner"))
    response = agent.handle("Do you offer roof surveys?", SimpleNamespace(channel="web"), {})
    assert response["intent"] == "website_answer"
    assert "Northstar" in response["reply"]


@pytest.mark.parametrize("question", [
    "Any offers?", "Do you offer discounts?", "Can you offer deals?", "Do you offer coupons?",
])
def test_promotional_offer_questions_keep_current_offers(monkeypatch, question):
    promotion = {"id": "current-deal", "title": "Current tenant promotion",
                 "description": "A verified seasonal promotion.", "active": True}
    agent = handler(monkeypatch, faq=FAQStore(faq=[{
        "q": question, "a": "Obsolete promotion copy.", "tags": [],
    }]), offers=SimpleNamespace(active=lambda: [promotion]))
    response = agent.handle(question, SimpleNamespace(channel="web"), {})
    assert response["intent"] == "offers"
    assert "Current tenant promotion" in response["reply"]
    assert "Obsolete promotion" not in response["reply"]


@pytest.mark.parametrize("question", [
    "Do you offer delivery?", "Do you offer collection?", "Can you offer stock information?",
    "Do you offer price information?",
])
def test_service_faq_shortcut_does_not_replace_current_sales_facts(monkeypatch, question):
    agent = handler(monkeypatch, faq=FAQStore(faq=[{
        "q": question, "a": "Old FAQ values must not override current sales facts.", "tags": [],
    }]))
    response = agent.handle(question, SimpleNamespace(channel="web"), {})
    assert response["intent"] != "faq"
    assert "Old FAQ values" not in response["reply"]
