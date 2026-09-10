"""Validated tenant sales-playbook settings shared by the API and agent."""

from __future__ import annotations

from typing import Any, Dict, Tuple


OFFERING_TYPES = frozenset({"products", "services", "mixed"})
PRIMARY_GOALS = frozenset(
    {"drive_sales", "book_consultation", "capture_leads", "answer_questions"}
)
MAX_BUSINESS_FOCUS_LENGTH = 240
MAX_IDEAL_CUSTOMER_LENGTH = 240
MAX_HANDOFF_MESSAGE_LENGTH = 360
MAX_VALUE_PROPOSITIONS = 5
MAX_VALUE_PROPOSITION_LENGTH = 160
MAX_QUALIFICATION_QUESTIONS = 4
MAX_QUALIFICATION_QUESTION_LENGTH = 180


class SalesPlaybookValidationError(ValueError):
    """Raised when a tenant playbook cannot be safely stored."""


def default_sales_playbook() -> Dict[str, Any]:
    """Return a new, backwards-compatible playbook for an existing tenant."""
    return {
        "business_focus": "",
        "ideal_customer": "",
        "value_propositions": [],
        "offering_type": "products",
        "primary_goal": "drive_sales",
        "qualification_questions": [],
        "handoff_message": "",
    }


def _clean_text(value: Any, *, field: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SalesPlaybookValidationError(f"{field}_must_be_string")
    cleaned = " ".join(value.split())
    if len(cleaned) > maximum:
        raise SalesPlaybookValidationError(f"{field}_too_long")
    return cleaned


def _enum(value: Any, *, field: str, allowed: frozenset[str], default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise SalesPlaybookValidationError(f"{field}_must_be_string")
    cleaned = value.strip().lower()
    if cleaned not in allowed:
        raise SalesPlaybookValidationError(f"invalid_{field}")
    return cleaned


def validate_sales_playbook(value: Any) -> Dict[str, Any]:
    """Validate and normalize the supported tenant playbook fields."""
    if not isinstance(value, dict):
        raise SalesPlaybookValidationError("sales_playbook_must_be_object")

    questions_value = value.get("qualification_questions", [])
    if not isinstance(questions_value, list):
        raise SalesPlaybookValidationError("qualification_questions_must_be_list")

    questions = []
    seen = set()
    for question_value in questions_value:
        question = _clean_text(
            question_value,
            field="qualification_question",
            maximum=MAX_QUALIFICATION_QUESTION_LENGTH,
        )
        if not question:
            continue
        key = question.casefold()
        if key in seen:
            continue
        seen.add(key)
        questions.append(question)

    if len(questions) > MAX_QUALIFICATION_QUESTIONS:
        raise SalesPlaybookValidationError("too_many_qualification_questions")

    propositions_value = value.get("value_propositions", [])
    if not isinstance(propositions_value, list):
        raise SalesPlaybookValidationError("value_propositions_must_be_list")

    propositions = []
    seen_propositions = set()
    for proposition_value in propositions_value:
        proposition = _clean_text(
            proposition_value,
            field="value_proposition",
            maximum=MAX_VALUE_PROPOSITION_LENGTH,
        )
        if not proposition:
            continue
        key = proposition.casefold()
        if key in seen_propositions:
            continue
        seen_propositions.add(key)
        propositions.append(proposition)

    if len(propositions) > MAX_VALUE_PROPOSITIONS:
        raise SalesPlaybookValidationError("too_many_value_propositions")

    return {
        "business_focus": _clean_text(
            value.get("business_focus"),
            field="business_focus",
            maximum=MAX_BUSINESS_FOCUS_LENGTH,
        ),
        "ideal_customer": _clean_text(
            value.get("ideal_customer"),
            field="ideal_customer",
            maximum=MAX_IDEAL_CUSTOMER_LENGTH,
        ),
        "value_propositions": propositions,
        "offering_type": _enum(
            value.get("offering_type"),
            field="offering_type",
            allowed=OFFERING_TYPES,
            default="products",
        ),
        "primary_goal": _enum(
            value.get("primary_goal"),
            field="primary_goal",
            allowed=PRIMARY_GOALS,
            default="drive_sales",
        ),
        "qualification_questions": questions,
        "handoff_message": _clean_text(
            value.get("handoff_message"),
            field="handoff_message",
            maximum=MAX_HANDOFF_MESSAGE_LENGTH,
        ),
    }


def load_sales_playbook(overrides: Any) -> Dict[str, Any]:
    """Read a playbook defensively so malformed legacy data fails closed to defaults."""
    raw: Any = None
    try:
        raw = overrides.get("sales_playbook") if overrides is not None else None
    except (AttributeError, TypeError):
        raw = None

    if raw is None:
        return default_sales_playbook()
    try:
        return validate_sales_playbook(raw)
    except SalesPlaybookValidationError:
        return default_sales_playbook()


def offering_terms(playbook: Dict[str, Any]) -> Tuple[str, str]:
    """Return the customer-facing singular and plural catalogue labels."""
    offering_type = str(playbook.get("offering_type") or "products").lower()
    if offering_type == "services":
        return "service", "services"
    if offering_type == "mixed":
        return "offering", "offerings"
    return "product", "products"
