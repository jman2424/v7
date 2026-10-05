"""Business-model tailoring preserves legacy defaults and validated boundaries."""

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest

from service.business_validation import validate_settings
from service.sales_playbook import (
    BUSINESS_MODELS,
    CUSTOMER_TYPES,
    FULFILMENT_MODES,
    MAX_RESPONSE_GUIDANCE_LENGTH,
    PRIMARY_GOALS,
    SalesPlaybookValidationError,
    default_sales_playbook,
    load_sales_playbook,
    validate_sales_playbook,
)


def test_existing_playbook_keeps_its_values_and_gets_neutral_tailoring_defaults():
    legacy = {
        "business_focus": "Kitchen design",
        "offering_type": "services",
        "primary_goal": "book_consultation",
        "qualification_questions": ["Which room are you planning?"],
        "handoff_message": "Our team can help you plan the next step.",
    }
    result = validate_sales_playbook(legacy)

    assert all(result[key] == value for key, value in legacy.items())
    assert result["business_model"] == "general"
    assert result["fulfilment_mode"] == "auto"
    assert result["customer_type"] == "both"
    assert result["response_guidance"] == ""
    assert default_sales_playbook()["offering_type"] == "products"
    assert default_sales_playbook()["primary_goal"] == "drive_sales"


def test_default_playbooks_do_not_share_mutable_questions_or_benefits():
    first = default_sales_playbook()
    first["qualification_questions"].append("What do you need?")
    first["value_propositions"].append("Owner-configured benefit")

    assert default_sales_playbook()["qualification_questions"] == []
    assert default_sales_playbook()["value_propositions"] == []


@pytest.mark.parametrize("field,allowed", [
    ("business_model", BUSINESS_MODELS),
    ("fulfilment_mode", FULFILMENT_MODES),
    ("customer_type", CUSTOMER_TYPES),
    ("primary_goal", PRIMARY_GOALS),
])
def test_supported_tailoring_options_round_trip_through_both_validators(field, allowed):
    app = Flask(__name__)
    for choice in sorted(allowed):
        playbook = validate_sales_playbook({field: choice})
        assert playbook[field] == choice
        with app.app_context():
            validate_settings("overrides.json", {"sales_playbook": playbook})
        assert load_sales_playbook({"sales_playbook": playbook}) == playbook


@pytest.mark.parametrize("field", ["business_model", "fulfilment_mode", "customer_type", "primary_goal"])
@pytest.mark.parametrize("value", ["unsupported", True, {}, []])
def test_invalid_tailoring_values_are_rejected(field, value):
    with pytest.raises(SalesPlaybookValidationError):
        validate_sales_playbook({field: value})


def test_tailoring_input_is_normalized_without_changing_business_facts():
    result = validate_sales_playbook({
        "business_model": " PROFESSIONAL_SERVICES ",
        "fulfilment_mode": " REMOTE ",
        "customer_type": " BUSINESSES ",
        "primary_goal": " REQUEST_QUOTE ",
        "response_guidance": "  Use plain language.\n Ask one question at a time.  ",
    })

    assert result["business_model"] == "professional_services"
    assert result["fulfilment_mode"] == "remote"
    assert result["customer_type"] == "businesses"
    assert result["primary_goal"] == "request_quote"
    assert result["response_guidance"] == "Use plain language. Ask one question at a time."
    assert result["business_focus"] == ""
    assert result["value_propositions"] == []


def test_response_guidance_accepts_the_limit_and_rejects_longer_or_nontext_values():
    guidance = "x" * MAX_RESPONSE_GUIDANCE_LENGTH
    assert validate_sales_playbook({"response_guidance": guidance})["response_guidance"] == guidance
    with pytest.raises(SalesPlaybookValidationError, match="response_guidance_too_long"):
        validate_sales_playbook({"response_guidance": guidance + "x"})
    with pytest.raises(SalesPlaybookValidationError, match="response_guidance_must_be_string"):
        validate_sales_playbook({"response_guidance": ["Use plain language"]})


def test_unknown_fields_are_rejected_without_echoing_the_key_or_value():
    with pytest.raises(SalesPlaybookValidationError) as failure:
        validate_sales_playbook({"private_payload_marker": "secret-value-marker"})

    assert str(failure.value) == "unsupported_sales_playbook_fields"
    assert "private_payload_marker" not in str(failure.value)
    assert "secret-value-marker" not in str(failure.value)
    assert load_sales_playbook({"sales_playbook": {"unsupported": "value"}}) == default_sales_playbook()


@pytest.mark.parametrize("playbook", [
    {"business_model": "unknown"},
    {"fulfilment_mode": "unknown"},
    {"customer_type": "unknown"},
    {"response_guidance": "x" * (MAX_RESPONSE_GUIDANCE_LENGTH + 1)},
    {"unknown_field": "value"},
])
def test_raw_document_writes_enforce_the_same_tailoring_boundary(playbook):
    with Flask(__name__).app_context(), pytest.raises(BadRequest):
        validate_settings("overrides.json", {"sales_playbook": playbook})
