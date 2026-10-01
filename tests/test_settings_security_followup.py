"""Settings retain current widget/playbook fields and reject unsafe extensions."""
import copy
import json
from pathlib import Path

import pytest
import test_platform_security
from flask import Flask
from jsonschema import Draft202012Validator
from werkzeug.exceptions import BadRequest

from service.business_validation import validate_settings
from service.sales_playbook import default_sales_playbook

platform = test_platform_security.platform
ROOT = Path(__file__).resolve().parents[1]


def _validate(filename, payload):
    with Flask(__name__).app_context():
        validate_settings(filename, payload)


@pytest.mark.parametrize("payload", [
    {"role": "platform_admin"}, {"private_key": "test-placeholder"},
    {"widget": {"unknown_field": True}}, {"widget": {"greeting": 42}},
    {"widget": {"assistant_name": "x" * 81}}, {"widget": {"greeting": "x" * 241}},
    {"widget": {"style": "unsupported"}}, {"widget": {"accent_color": "url(https://example.test)"}},
    {"theme": {"unknown_field": True}}, {"theme": {"primary_color": "red"}},
    {"theme": {"font_family": []}}, {"allowed_origins": "https://example.test"},
    {"widget": {"allowed_origins": [42]}}, {"widget": {"allowed_origins": ["https://example.test"] * 2}},
    {"logo": {"extra": "https://example.test/logo.png"}},
])
def test_branding_rejects_unknown_fields_wrong_types_and_unbounded_values(payload):
    with pytest.raises(BadRequest):
        _validate("branding.json", payload)


@pytest.mark.parametrize("origin", [
    "https://example.test/path", "https://example.test?query=1", "https://example.test#fragment",
    "https://example.test:invalid", "https://example.test:99999", "https://[invalid",
    "https://example.test\n/path", "https://example.test\\other.test", "null",
    "https://" + ":".join(("example-user", "example-password")) + "@example.test",
    "https://@example.test", "http://example.test", "http://localhost.evil.test",
    "http://127.0.0.1.evil.test",
])
def test_nested_widget_origins_are_exact_secure_urls(origin):
    with pytest.raises(BadRequest):
        _validate("branding.json", {"widget": {"allowed_origins": [origin]}})


@pytest.mark.parametrize("section,field", [
    ("widget", "avatar"), ("widget", "company_logo_url"), ("logo", "light"), ("logo", "dark"), (None, "favicon"),
])
@pytest.mark.parametrize("url", ["//other.test/logo.png", "/\\other.test/logo.png", "javascript:alert(1)",
    "https://[invalid", "https://example.test:invalid/logo.png"])
def test_all_brand_image_fields_reject_protocol_relative_and_malformed_urls(section, field, url):
    payload = {section: {field: url}} if section else {field: url}
    with pytest.raises(BadRequest):
        _validate("branding.json", payload)


def test_current_widget_and_sales_playbook_fields_are_preserved():
    branding = {
        "theme": {"primary_color": "#274060", "secondary_color": "#FFFFFF", "accent_color": "#3EEA8C",
                  "text_color": "#172033", "font_family": "Inter, sans-serif"},
        "widget": {"chat_title": "Sales assistant", "assistant_name": "Example team",
                   "greeting": "Hello, how can we help?", "avatar": "/static/img/avatar.svg",
                   "company_logo_url": "https://assets.example.test/logo.svg", "style": "glass",
                   "accent_color": "#3EEA8C", "allowed_origins": [
                       "https://www.example.test", "http://localhost:5173", "http://[::1]:8000",
                   ]},
        "allowed_origins": ["https://legacy.example.test"],
        "logo": {"light": "/static/img/light.svg", "dark": "https://assets.example.test/dark.png"},
        "favicon": "/static/img/favicon.ico",
    }
    playbook = {**default_sales_playbook(), "offering_type": "mixed", "primary_goal": "book_consultation",
                "business_focus": "Design and installation", "ideal_customer": "Local business owners",
                "value_propositions": ["One team for design and installation"],
                "qualification_questions": ["When would you like to start?"],
                "handoff_message": "Our team can arrange a consultation."}
    overrides = {"ai": {"mode": "v7"}, "tone": {"style": "professional", "max_sentences": 2},
                 "sales_playbook": playbook}
    before = copy.deepcopy((branding, overrides))
    _validate("branding.json", branding)
    _validate("overrides.json", overrides)
    assert (branding, overrides) == before


@pytest.mark.parametrize("folder", ["business/EXAMPLE", "business/TARIQ", "tests/fixtures/retail_business"])
@pytest.mark.parametrize("filename", ["branding.json", "overrides.json", "store_info.json", "synonyms.json"])
def test_existing_business_settings_remain_accepted(folder, filename):
    _validate(filename, json.loads((ROOT / folder / filename).read_text()))


@pytest.mark.parametrize("payload", [
    {"ai": {"mode": "v7", "api_key": "test-placeholder"}},
    {"tone": {"unknown_field": "data"}}, {"tone": {"max_sentences": True}},
    {"thresholds": {"search_confidence": 1.1}}, {"thresholds": {"geo_radius_km": -1}},
    {"recommendations": {"related_count": 101}}, {"self_repair": {"log_issues_only": "true"}},
    {"sales_playbook": {"unknown_field": "value"}}, {"sales_playbook": {"offering_type": "unknown"}},
    {"sales_playbook": {"business_focus": "x" * 241}},
    {"sales_playbook": {"value_propositions": ["A", "B", "C", "D", "E", "F"]}},
])
def test_overrides_reject_unknown_fields_and_invalid_playbook_or_numeric_bounds(payload):
    with pytest.raises(BadRequest):
        _validate("overrides.json", payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), float("1e999")])
def test_nonfinite_settings_never_reach_storage(value):
    with pytest.raises(BadRequest):
        _validate("overrides.json", {"thresholds": {"geo_radius_km": value}})


@pytest.mark.parametrize("filename,payload", [
    ("catalog.json", {"version": 1, "categories": []}), ("faq.json", []), ("offers.json", []),
    ("delivery.json", {}), ("branches.json", []), ("business_core.json", {}),
])
def test_schema_handled_documents_do_not_raise_settings_key_errors(filename, payload):
    _validate(filename, payload)


def _sheet_catalog(version=1):
    return {"version": version, "currency": "GBP", "product_catalog": [
        {"name": "Services", "items": [{"name": "Installation", "price_str": "£40 / hour",
                                        "stock": "Available", "subcategory": "On-site"}]},
    ]}


@pytest.mark.parametrize("version", [1, "1.0"])
def test_sheet_catalog_version_currency_and_format_remain_supported(version):
    schema = json.loads((ROOT / "schemas/catalog-sheet.schema.json").read_text())
    Draft202012Validator(schema).validate(_sheet_catalog(version))


@pytest.mark.parametrize("level", ["document", "category", "item"])
def test_sheet_catalog_rejects_unknown_fields_at_every_level(level):
    schema = json.loads((ROOT / "schemas/catalog-sheet.schema.json").read_text())
    payload = _sheet_catalog()
    selected = payload if level == "document" else payload["product_catalog"][0]
    if level == "item":
        selected = selected["items"][0]
    selected["tenant"] = "OTHER"
    assert not Draft202012Validator(schema).is_valid(payload)


@pytest.mark.parametrize("raw", [
    b'{"thresholds":{"geo_radius_km":NaN}}', b'{"thresholds":{"geo_radius_km":1e999}}',
])
def test_nonfinite_raw_settings_request_is_rejected_without_mutation(platform, raw):
    app = platform[0]
    client = app.test_client()
    csrf = test_platform_security.login(client)
    before = app.container.storage.read_json("ALPHA", "overrides.json")
    response = client.put("/files/raw/overrides.json", data=raw, content_type="application/json",
                          headers={"X-CSRF-Token": csrf})
    assert response.status_code == 400
    assert app.container.storage.read_json("ALPHA", "overrides.json") == before


def test_raw_branding_updates_reject_nested_unsafe_origin_without_mutation(platform):
    app = platform[0]
    client = app.test_client()
    csrf = test_platform_security.login(client)
    before = app.container.storage.read_json("ALPHA", "branding.json")
    response = client.put("/files/raw/branding.json", json={"widget": {"allowed_origins": ["https://example.test:invalid"]}},
                          headers={"X-CSRF-Token": csrf})
    assert response.status_code == 400
    assert app.container.storage.read_json("ALPHA", "branding.json") == before
