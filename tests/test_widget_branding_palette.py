"""Custom widget palettes stay tenant scoped and cannot inject styles or scripts."""
from __future__ import annotations

import copy
import json
import re

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest

from routes.admin_api_routes import _clean_widget_accent, _clean_widget_custom_color, _clean_widget_style, _widget_preview_theme
from routes.webchat_routes import _embed_javascript, _public_widget_branding, _widget_foreground
from service.business_validation import validate_settings
from tests.conftest import set_test_identity


COLORS = {
    "accent_color": "#ba3068", "background_color": "#f8f2ef", "surface_color": "#fffefd",
    "text_color": "#3c222d", "bubble_color": "#8b2761",
}
CUSTOM_COLORS = tuple(field for field in COLORS if field != "accent_color")


def _operator(client):
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "palette-operator", "roles": ["platform_admin"], "tenant": "EXAMPLE"})


@pytest.mark.parametrize("style", ["midnight", "daylight", "minimal", "editorial", "neon", "warm", "glass", "studio", "soft", "bold"])
def test_all_widget_styles_accept_custom_brand_colours_without_changing_raw_payload(style):
    payload = {"widget": {"style": style, **COLORS}}
    before = copy.deepcopy(payload)
    with Flask(__name__).app_context():
        assert _clean_widget_style(style) == style
        validate_settings("branding.json", payload)
    assert payload == before


def test_new_widget_palette_roundtrips_and_renders_only_for_its_tenant(client, app):
    _operator(client)
    branding = app.container.storage.read_json("EXAMPLE", "branding.json")
    app.container.storage.write_json("ALT", "branding.json", branding, snapshot=False)
    payload = {"chat_title": "Brand assistant", "style": "studio", **COLORS,
               "allowed_origins": ["https://shop.example.test"]}
    saved = client.put("/admin/api/widget?tenant=EXAMPLE", json=payload)
    assert saved.status_code == 200
    expected = {field: color.upper() for field, color in COLORS.items()}
    assert {field: saved.json["widget"][field] for field in COLORS} == expected
    assert saved.json["widget"]["style"] == "studio"
    assert 'border-radius:12px' in saved.json["embed"]["iframe_snippet"]
    assert 'allow="microphone"' in saved.json["embed"]["iframe_snippet"]
    assert app.container.storage.read_json("ALT", "branding.json") == branding
    read = client.get("/admin/api/widget?tenant=EXAMPLE")
    assert {field: read.json["widget"][field] for field in COLORS} == expected
    script = client.get("/widget.js?tenant=EXAMPLE")
    assert script.status_code == 200
    config = json.loads(re.search(r"var config = (.*);", script.text).group(1))
    assert config["style"] == "studio"
    assert config["primary"] == expected["accent_color"]
    assert config["background"] == expected["background_color"]
    assert config["launcherBackground"] == expected["surface_color"]
    assert config["launcherText"] == expected["text_color"]
    assert client.get("/chat_ui?tenant=EXAMPLE").status_code == 200


def test_optional_widget_colours_can_reset_or_be_preserved_during_an_older_client_update(client):
    _operator(client)
    assert client.put("/admin/api/widget", json={"style": "soft", **COLORS}).status_code == 200
    preserved = client.put("/admin/api/widget", json={"greeting": "Updated greeting"})
    assert preserved.status_code == 200
    assert preserved.json["widget"]["background_color"] == COLORS["background_color"].upper()
    assert preserved.json["widget"]["style"] == "soft"
    reset = client.put("/admin/api/widget", json={field: "" for field in CUSTOM_COLORS})
    assert reset.status_code == 200
    assert all(reset.json["widget"][field] == "" for field in CUSTOM_COLORS)
    with Flask(__name__).app_context():
        validate_settings("branding.json", {"widget": reset.json["widget"]})


@pytest.mark.parametrize("field,value", [
    ("accent_color", "red"), ("accent_color", False), ("accent_color", 0),
    ("background_color", "#fff"), ("surface_color", "#ffffff;display:none"),
    ("text_color", None), ("bubble_color", "url(https://other.example.test)"),
    ("background_color", {"value": "#FFFFFF"}), ("surface_color", "#ffffff\n<script>"),
])
def test_widget_palette_rejects_unsafe_values_without_storage_mutation(client, app, field, value):
    _operator(client)
    before = app.container.storage.read_json("EXAMPLE", "branding.json")
    response = client.put("/admin/api/widget", json={field: value})
    assert response.status_code == 400
    assert app.container.storage.read_json("EXAMPLE", "branding.json") == before
    with Flask(__name__).app_context(), pytest.raises(BadRequest):
        validate_settings("branding.json", {"widget": {field: value}})


def test_custom_colour_helpers_normalize_valid_hex_and_bound_invalid_public_branding():
    with Flask(__name__).app_context():
        assert _clean_widget_accent(" #a1b2c3 ") == "#A1B2C3"
        assert _clean_widget_custom_color(" #1122ee ", "text_color") == "#1122EE"
        assert _clean_widget_accent(None) == "#3EEA8C"
    branding = {"widget": {"style": "unknown", "accent_color": "red", "background_color": "#fff;display:none",
                           "surface_color": [], "text_color": "</style><script>", "bubble_color": "#a123ef"}}
    before = copy.deepcopy(branding)
    public = _public_widget_branding(branding)
    assert public["widget"]["style"] == "midnight"
    assert public["widget"]["accent_color"] == "#3EEA8C"
    assert public["widget"]["background_color"] == public["widget"]["surface_color"] == public["widget"]["text_color"] == ""
    assert public["widget"]["bubble_color"] == "#A123EF"
    assert branding == before


def test_raw_widget_colour_requires_exact_hex_without_a_trailing_newline():
    with Flask(__name__).app_context(), pytest.raises(BadRequest):
        validate_settings("branding.json", {"widget": {"bubble_color": "#FFFFFF\n"}})


@pytest.mark.parametrize("background,preferred,expected", [
    ("#FFFFFF", "#FFFFFF", "#000000"), ("#000000", "#000000", "#FFFFFF"),
    ("#FFFFFF", "#333333", "#333333"), ("#D8A4FF", "#FFFFFF", "#000000"),
    ("#087F5B", "", "#FFFFFF"), ("#808080", "", "#000000"),
])
def test_launcher_text_uses_readable_foreground_for_custom_colours(background, preferred, expected):
    assert _widget_foreground(background, preferred) == expected


def test_launcher_keeps_legacy_theme_primary_default_without_a_widget_accent():
    script = _embed_javascript("EXAMPLE", {"theme": {"primary_color": "#274060"}})
    config = json.loads(re.search(r"var config = (.*);", script).group(1))
    assert config["primary"] == "#274060"


def test_palette_customization_requires_write_permission_and_denies_foreign_tenant(client, app):
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "palette-reader", "roles": ["business_staff"], "tenant": "EXAMPLE",
                                          "permissions": ["business_settings.read"]})
    before = app.container.storage.read_json("EXAMPLE", "branding.json")
    assert client.get("/admin/api/widget").status_code == 200
    assert client.put("/admin/api/widget", json=COLORS).status_code == 403
    assert client.put("/admin/api/widget?tenant=ALT", json=COLORS).status_code == 403
    assert app.container.storage.read_json("EXAMPLE", "branding.json") == before


def test_widget_preview_theme_exposes_only_safe_legacy_colours_and_font_stack(client, app):
    _operator(client)
    branding = app.container.storage.read_json("EXAMPLE", "branding.json")
    branding["theme"] = {"primary_color": "#a2c", "secondary_color": "#274060", "text_color": "#fff",
                         "accent_color": "#ed3", "font_family": "Inter, 'Segoe UI', sans-serif",
                         "private_note": "Internal fixture value", "unrelated_config": {"detail": "Keep private"}}
    app.container.storage.write_json("EXAMPLE", "branding.json", branding, snapshot=False)
    expected = {"primary_color": "#AA22CC", "secondary_color": "#274060", "text_color": "#FFFFFF",
                "accent_color": "#EEDD33", "font_family": "Inter, 'Segoe UI', sans-serif"}
    response = client.get("/admin/api/widget")
    assert response.status_code == 200
    assert response.json["preview_theme"] == expected
    assert "preview_theme" not in response.json["widget"]
    assert "Internal fixture value" not in response.text
    updated = client.put("/admin/api/widget", json={"greeting": "Hello from our team"})
    assert updated.status_code == 200
    assert updated.json["preview_theme"] == expected
    assert app.container.storage.read_json("EXAMPLE", "branding.json")["theme"] == branding["theme"]


@pytest.mark.parametrize("theme", [None, [], {},
    {"primary_color": "red", "secondary_color": "#fff;display:none", "text_color": 123,
     "accent_color": "#ffffff\n", "font_family": "Inter; background:url(https://other.example.test)"},
    {"font_family": "F" * 121}, {"font_family": ""},
])
def test_widget_preview_theme_omits_malformed_colours_fonts_and_nonobjects(theme):
    assert _widget_preview_theme({"theme": theme}) == {}
