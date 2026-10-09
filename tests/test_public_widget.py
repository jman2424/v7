"""The platform website's optional widget cannot bleed into private screens."""
from dataclasses import replace
from html.parser import HTMLParser

import pytest

from app.config import load_settings
from service.public_site_content import SOLUTIONS


class WidgetScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("data-target") == "#public-site-widget":
            self.scripts.append(attributes)


@pytest.fixture
def widget_client(app):
    app.container.settings = replace(app.container.settings, PUBLIC_WIDGET_TENANT="EXAMPLE")
    return app.test_client()


@pytest.mark.parametrize("value", [None, "", False, 123, [], " EXAMPLE", "EXAMPLE\n",
    "../EXAMPLE", "EXAMPLE&tenant=OTHER", 'EXAMPLE\" onload=\"alert(1)', "A" * 65])
def test_invalid_optional_widget_tenant_disables_without_startup_failure(value):
    assert load_settings({"TESTING": True, "PUBLIC_WIDGET_TENANT": value}).PUBLIC_WIDGET_TENANT == ""


@pytest.mark.parametrize("value", ["EXAMPLE", "company-7", "company_7", "A" * 64])
def test_optional_widget_tenant_accepts_bounded_keys(value):
    assert load_settings({"TESTING": True, "PUBLIC_WIDGET_TENANT": value}).PUBLIC_WIDGET_TENANT == value


@pytest.mark.parametrize("path", ["/", "/about", "/guides/getting-started"] +
    ["/solutions/" + slug for slug in SOLUTIONS])
def test_public_marketing_pages_embed_only_configured_tenant(widget_client, path):
    response = widget_client.get(path + "?tenant=OTHER", base_url="https://untrusted.example")
    assert response.status_code == 200
    scripts = WidgetScripts()
    scripts.feed(response.text)
    assert len(scripts.scripts) == 1
    script = scripts.scripts[0]
    assert script["src"] == "/widget.js?tenant=EXAMPLE"
    assert "defer" in script
    assert 'id="public-site-widget"' in response.text
    assert "tenant=OTHER" not in response.text
    assert "untrusted.example" not in script["src"]
    # Integration does not expand public microphone or network permissions.
    assert "microphone=()" in response.headers["Permissions-Policy"]
    assert "connect-src 'self';" in response.headers["Content-Security-Policy"]


@pytest.mark.parametrize("path", ["/", "/about", "/guides/getting-started", "/solutions/website-chatbot"])
def test_disabled_marketing_widget_does_not_make_widget_requests(app, path):
    app.container.settings = replace(app.container.settings, PUBLIC_WIDGET_TENANT="")
    response = app.test_client().get(path)
    assert response.status_code == 200
    assert 'id="public-site-widget"' not in response.text
    assert "/widget.js?tenant=" not in response.text


@pytest.mark.parametrize("path", ["/console/", "/auth/session", "/admin/api/conversations",
    "/chat_ui?tenant=EXAMPLE", "/widget.js?tenant=EXAMPLE", "/privacy", "/privacy?tenant=EXAMPLE",
    "/cookies", "/robots.txt", "/sitemap.xml", "/static/css/home.css", "/solutions/missing"])
def test_non_marketing_routes_never_receive_marketing_widget(widget_client, path):
    app = widget_client.application
    with app.test_request_context(path):
        context = {}
        app.update_template_context(context)
        assert context["public_widget_tenant"] == ""
    response = widget_client.get(path)
    assert 'id="public-site-widget"' not in response.text
    assert 'data-target="#public-site-widget"' not in response.text


def test_public_widget_preserves_management_authorization(widget_client):
    response = widget_client.get("/admin/api/conversations")
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_invalid_mutated_configuration_does_not_reach_public_html(widget_client):
    app = widget_client.application
    app.container.settings = replace(app.container.settings, PUBLIC_WIDGET_TENANT='EXAMPLE\" onload=\"alert(1)')
    response = widget_client.get("/")
    assert 'id="public-site-widget"' not in response.text
    assert "alert(1)" not in response.text
