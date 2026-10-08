"""Public search metadata must never enumerate tenant or management content."""
import json
from decimal import Decimal
from html.parser import HTMLParser
from xml.etree import ElementTree

import pytest

from service.public_site_content import SOLUTIONS


ORIGIN = "https://vertex-seven.com"
SOLUTION_SLUGS = {
    "website-chatbot", "ai-chatbot-software", "sales-chatbot", "customer-support-chatbot",
    "ai-lead-generation-software", "conversational-ai-platform",
    "branded-website-chat-widget", "ai-product-recommendation-chatbot",
}


class HeadLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonicals = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonicals.append(attributes.get("href"))


class HomeStructuredData(HeadLinks):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.visible_text = []
        self._in_body = False
        self._jsonld = None

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attributes = dict(attrs)
        if tag == "body":
            self._in_body = True
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self._jsonld = {"nonce": attributes.get("nonce"), "text": ""}

    def handle_data(self, data):
        if self._jsonld is not None:
            self._jsonld["text"] += data
        elif self._in_body:
            self.visible_text.append(data)

    def handle_endtag(self, tag):
        if tag == "body":
            self._in_body = False
        if tag == "script" and self._jsonld is not None:
            self.scripts.append(self._jsonld)
            self._jsonld = None


@pytest.fixture
def seo_client(monkeypatch, request):
    monkeypatch.setenv("BASE_URL", ORIGIN)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("RENDER", raising=False)
    # Construct the regular isolated app after configuring its public origin.
    return request.getfixturevalue("app").test_client()


@pytest.mark.parametrize("path", ["/", "/solutions/website-chatbot", "/solutions/ai-chatbot-software"])
def test_public_canonical_uses_configuration_not_request_host(seo_client, path):
    response = seo_client.get(path + "?tenant=EXAMPLE&utm_source=example",
                              base_url="https://untrusted.example")
    assert response.status_code == 200
    links = HeadLinks()
    links.feed(response.text)
    assert links.canonicals == [ORIGIN + path]
    assert "untrusted.example" not in response.text
    assert "X-Robots-Tag" not in response.headers


def test_home_plan_schema_matches_visible_monthly_pricing_and_extra_charges(seo_client):
    from service.subscriptions import PRICES, VAT_PERCENT

    response = seo_client.get("/", base_url="https://untrusted.example")
    assert response.status_code == 200
    page = HomeStructuredData()
    page.feed(response.text)
    assert len(page.scripts) == 1
    script = page.scripts[0]
    assert script["nonce"]
    assert "'nonce-" + script["nonce"] + "'" in response.headers["Content-Security-Policy"]
    metadata = json.loads(script["text"])
    assert metadata["@context"] == "https://schema.org"
    products = [item for item in metadata["@graph"] if item["@type"] == "Product"]
    assert len(products) == 1
    product = products[0]
    offer = product["offers"]
    specification = offer["priceSpecification"]
    vat_multiplier = Decimal(1) + Decimal(VAT_PERCENT) / 100
    monthly_total = Decimal(PRICES["platform"]) / 100 * vat_multiplier
    setup_total = Decimal(PRICES["implementation"]) / 100 * vat_multiplier
    assert monthly_total == Decimal("480")
    assert setup_total == Decimal("240")
    assert specification["@type"] == "UnitPriceSpecification"
    assert Decimal(specification["price"]) == monthly_total
    assert specification["priceCurrency"] == "GBP"
    assert specification["valueAddedTaxIncluded"] is True
    assert specification["unitCode"] == "MON"
    assert specification["unitText"] == "month"
    assert "referenceQuantity" not in specification
    visible = " ".join(" ".join(page.visible_text).split())
    assert "£80 VAT · £480/month total" in visible
    assert "£40 VAT · £240 total" in visible
    assert "one-time implementation separately" in visible
    assert "API costs are separate" in visible
    assert "OPTIONAL WHATSAPP ADD-ON" in visible
    description = product["description"]
    assert "£480 per month including VAT" in description
    assert "Required one-time implementation is £240 including VAT" in description
    assert "API usage is additional" in description
    assert "optional WhatsApp is charged separately" in description
    assert "Required implementation, API usage and optional WhatsApp are charged separately" in offer["description"]
    assert product["url"] == offer["url"] == ORIGIN + "/#pricing"
    assert product["@id"] == ORIGIN + "/#monthly-plan"
    assert offer["seller"]["@id"] == ORIGIN + "/#organization"
    assert "untrusted.example" not in json.dumps(metadata)
    pending = [metadata]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            assert not {"aggregateRating", "review", "ratingValue", "reviewRating"}.intersection(item)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def test_sitemap_lists_only_known_public_pages(seo_client):
    response = seo_client.get("/sitemap.xml?tenant=EXAMPLE", base_url="https://untrusted.example")
    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    tree = ElementTree.fromstring(response.data)
    locations = [element.text for element in tree.findall("{*}url/{*}loc")]
    assert set(SOLUTIONS) == SOLUTION_SLUGS
    assert locations == [ORIGIN + "/"] + [ORIGIN + "/solutions/" + slug for slug in SOLUTIONS]
    assert len(locations) == 9
    assert all("?" not in location for location in locations)
    assert "EXAMPLE" not in response.text
    assert "untrusted.example" not in response.text
    assert "X-Robots-Tag" not in response.headers


def test_robots_keeps_public_assets_crawlable_and_points_to_configured_sitemap(seo_client):
    response = seo_client.get("/robots.txt", base_url="https://untrusted.example")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    directives = response.text.splitlines()
    assert "User-agent: *" in directives
    assert "Allow: /" in directives
    assert "Allow: /static/" in directives
    for path in ("/console", "/auth", "/admin", "/api/", "/chat_ui", "/files"):
        assert "Disallow: " + path in directives
    assert "Disallow: /privacy?tenant=" in directives
    assert "Sitemap: " + ORIGIN + "/sitemap.xml" in directives
    assert "untrusted.example" not in response.text


@pytest.mark.parametrize("path", ["/robots.txt", "/sitemap.xml"])
def test_discovery_responses_do_not_make_session_cookies_publicly_cacheable(seo_client, path):
    response = seo_client.get(path)
    assert response.status_code == 200
    assert "Set-Cookie" in response.headers
    assert "public" not in response.headers.get("Cache-Control", "").lower()


@pytest.mark.parametrize("slug", sorted(SOLUTION_SLUGS))
def test_solution_pages_are_public_and_allowlisted(seo_client, slug):
    response = seo_client.get("/solutions/" + slug)
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert SOLUTIONS[slug]["h1"] in response.text
    assert "X-Robots-Tag" not in response.headers


@pytest.mark.parametrize("path", ["/solutions/missing", "/solutions/EXAMPLE", "/solutions/website-chatbot/extra"])
def test_unknown_solution_pages_return_not_found(seo_client, path):
    assert seo_client.get(path).status_code == 404


@pytest.mark.parametrize("path", [
    "/auth/session", "/admin/api/conversations", "/console/", "/api/v1/tenants",
    "/chat_ui?tenant=EXAMPLE", "/widget.js?tenant=EXAMPLE", "/health",
    "/privacy?tenant=EXAMPLE",
])
def test_management_and_tenant_routes_are_not_search_content(seo_client, path):
    assert seo_client.get(path).headers["X-Robots-Tag"] == "noindex, nofollow"


def test_indexing_controls_preserve_authorization_and_public_asset_access(seo_client):
    private = seo_client.get("/admin/api/conversations")
    assert private.status_code == 401
    assert private.headers["Cache-Control"] == "no-store"
    assert private.headers["X-Frame-Options"] == "DENY"
    public = seo_client.get("/static/css/home.css")
    assert public.status_code == 200
    assert "X-Robots-Tag" not in public.headers
