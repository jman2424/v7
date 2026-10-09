"""Optional marketing analytics must not relax or expose private application pages."""
from dataclasses import replace

import pytest
from flask import template_rendered

from app.config import load_settings
from service import privacy_settings
from service.public_site_content import SOLUTIONS


MEASUREMENT_ID = "G-TEST123456"
GOOGLE_TAG = "https://www.googletagmanager.com"
COLLECTION_ORIGINS = {GOOGLE_TAG, "https://www.google-analytics.com", "https://region1.google-analytics.com"}


def csp_sources(response):
    directives = {}
    for directive in response.headers["Content-Security-Policy"].split(";"):
        parts = directive.strip().split()
        if parts:
            directives[parts[0]] = set(parts[1:])
    return directives


@pytest.fixture
def analytics_client(app):
    app.container.settings = replace(app.container.settings, GA4_MEASUREMENT_ID=MEASUREMENT_ID)
    return app.test_client()


@pytest.mark.parametrize("value", [None, "", False, 123, [], "g-TEST123456", "G-abc123456",
    "G-12345", "G-" + "A" * 21, " G-TEST123456", "G-TEST123456\n",
    "G-TEST123456'; script-src *", "https://example.test"])
def test_invalid_optional_measurement_ids_disable_without_configuration_failure(value):
    settings = load_settings({"TESTING": True, "GA4_MEASUREMENT_ID": value})
    assert settings.GA4_MEASUREMENT_ID == ""


@pytest.mark.parametrize("value", ["G-ABC123", MEASUREMENT_ID, "G-" + "A" * 20])
def test_measurement_id_validation_accepts_only_the_public_identifier(value):
    settings = load_settings({"TESTING": True, "GA4_MEASUREMENT_ID": value})
    assert settings.GA4_MEASUREMENT_ID == value


@pytest.mark.parametrize("path", ["/"] + ["/solutions/" + slug for slug in SOLUTIONS])
def test_only_allowlisted_public_templates_receive_analytics_configuration(analytics_client, path):
    contexts = []

    def rendered(sender, template, context, **extra):
        contexts.append(context)

    with template_rendered.connected_to(rendered, analytics_client.application):
        response = analytics_client.get(path)
    assert response.status_code == 200
    assert len(contexts) == 1
    assert contexts[0]["ga4_measurement_id"] == MEASUREMENT_ID
    directives = csp_sources(response)
    assert directives["connect-src"] == {"'self'"} | COLLECTION_ORIGINS
    assert GOOGLE_TAG in directives["script-src"]
    assert any(source.startswith("'nonce-") for source in directives["script-src"])
    assert "'unsafe-inline'" not in directives["script-src"]
    assert "'unsafe-eval'" not in directives["script-src"]
    assert not any("*" in source for source in directives["script-src"] | directives["connect-src"])


@pytest.mark.parametrize("path", ["/console/", "/auth/session", "/admin/api/conversations",
    "/chat_ui?tenant=EXAMPLE", "/widget.js?tenant=EXAMPLE", "/privacy", "/privacy?tenant=EXAMPLE",
    "/about", "/cookies", "/robots.txt", "/sitemap.xml", "/static/css/home.css", "/solutions/missing"])
def test_non_marketing_routes_keep_configuration_empty_and_original_csp(analytics_client, path):
    app = analytics_client.application
    with app.test_request_context(path):
        context = {}
        app.update_template_context(context)
        assert context["ga4_measurement_id"] == ""
    response = analytics_client.get(path)
    assert MEASUREMENT_ID not in response.text
    directives = csp_sources(response)
    assert directives["connect-src"] == {"'self'"}
    assert GOOGLE_TAG not in directives["script-src"]
    assert len(directives["script-src"]) == 2
    assert "'self'" in directives["script-src"]
    assert any(source.startswith("'nonce-") for source in directives["script-src"])
    assert directives["object-src"] == {"'none'"}
    assert directives["form-action"] == {"'self'"}


def test_disabled_analytics_does_not_add_google_csp_permissions(client, app):
    app.container.settings = replace(app.container.settings, GA4_MEASUREMENT_ID="")
    response = client.get("/")
    directives = csp_sources(response)
    assert directives["connect-src"] == {"'self'"}
    assert GOOGLE_TAG not in directives["script-src"]


def test_unknown_solution_and_errors_never_get_analytics_permissions(analytics_client):
    response = analytics_client.get("/solutions/missing")
    assert response.status_code == 404
    assert csp_sources(response)["connect-src"] == {"'self'"}
    denied = analytics_client.post("/")
    assert denied.status_code == 405
    assert csp_sources(denied)["connect-src"] == {"'self'"}


def test_management_authorization_and_security_headers_remain_intact(analytics_client):
    response = analytics_client.get("/admin/api/conversations")
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert csp_sources(response)["frame-ancestors"] == {"'none'"}


def test_privacy_discloses_configured_analytics_only_at_platform_scope(analytics_client):
    app = analytics_client.application
    with app.app_context():
        platform_processors = privacy_settings.processors(app.container, None)
        analytics = [item for item in platform_processors if item["name"] == "Google Analytics"]
        assert len(analytics) == 1
        assert "after analytics opt-in" in analytics[0]["purpose"]
        assert "no chat or account data" in analytics[0]["purpose"]
        assert not any(item["name"] == "Google Analytics" for item in privacy_settings.processors(app.container, "EXAMPLE"))
        app.container.settings = replace(app.container.settings, GA4_MEASUREMENT_ID="invalid")
        assert not any(item["name"] == "Google Analytics" for item in privacy_settings.processors(app.container, None))
    assert privacy_settings.DEFAULTS["controller_name"] == ""
    assert privacy_settings.DEFAULTS["contact_email"] == ""
    assert privacy_settings.DEFAULTS["lawful_basis"] == ""
