"""Public search metadata must never enumerate tenant or management content."""
import json
import struct
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
        self.icons = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonicals.append(attributes.get("href"))
        if tag == "link" and attributes.get("rel") in {"icon", "shortcut icon", "apple-touch-icon"}:
            self.icons.append(attributes)


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


@pytest.mark.parametrize("path", ["/", "/about", "/guides/getting-started", "/solutions/website-chatbot", "/solutions/ai-chatbot-software"])
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


@pytest.mark.parametrize("path", ["/", "/about", "/guides/getting-started"] + ["/solutions/" + slug for slug in SOLUTIONS])
def test_public_pages_identify_same_brand_and_product_without_private_contacts(seo_client, path):
    response = seo_client.get(path, base_url="https://untrusted.example")
    page = HomeStructuredData()
    page.feed(response.text)
    metadata = json.loads(page.scripts[0]["text"])
    if path == "/":
        application = next(item for item in metadata["@graph"] if item["@type"] == "SoftwareApplication")
        visible = " ".join(page.visible_text)
        assert "V7 Agents is the product; Vertex Seven is the brand behind it." in visible
        assert "vertex-seven.com" in visible
    else:
        application = metadata["about"]
    assert application["@id"] == ORIGIN + "/#v7-agents"
    assert application["name"] == "V7 Agents"
    assert application["publisher"]["@id"] == ORIGIN + "/#organization"
    assert "raja.jamalkhan24@gmail.com" not in response.text.lower()
    assert "untrusted.example" not in json.dumps(metadata)


def test_sitemap_lists_only_known_public_pages(seo_client):
    response = seo_client.get("/sitemap.xml?tenant=EXAMPLE", base_url="https://untrusted.example")
    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    tree = ElementTree.fromstring(response.data)
    locations = [element.text for element in tree.findall("{*}url/{*}loc")]
    assert set(SOLUTIONS) == SOLUTION_SLUGS
    assert locations == [ORIGIN + "/", ORIGIN + "/about", ORIGIN + "/guides/getting-started"] + [ORIGIN + "/solutions/" + slug for slug in SOLUTIONS]
    assert len(locations) == 11

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


def test_setup_guide_labels_examples_and_avoids_fabricated_customer_evidence(seo_client):
    response = seo_client.get("/guides/getting-started")
    assert response.status_code == 200
    assert "fictional demonstrations" in response.text
    assert "not customer testimonials or measured results" in response.text
    assert "confirmed booking" in response.text
    assert "aggregateRating" not in response.text


@pytest.mark.parametrize("path", ["/", "/about", "/guides/getting-started"] + ["/solutions/" + slug for slug in SOLUTIONS])
def test_public_pages_advertise_shared_crawlable_brand_icons(seo_client, path):
    page = HeadLinks()
    page.feed(seo_client.get(path).text)
    icons = {item["href"]: item for item in page.icons}
    assert icons["/static/img/favicon-96.png"]["sizes"] == "96x96"
    assert icons["/static/img/favicon-192.png"]["sizes"] == "192x192"
    assert icons["/static/img/apple-touch-icon.png"]["rel"] == "apple-touch-icon"
    assert icons["/favicon.ico"]["rel"] == "shortcut icon"
    assert any(item["type"] == "image/svg+xml" and item["sizes"] == "any" for item in page.icons)


@pytest.mark.parametrize("filename,size", [
    ("favicon-96.png", 96), ("favicon-192.png", 192), ("apple-touch-icon.png", 180),
])
def test_brand_raster_icons_are_square_public_pngs(seo_client, filename, size):
    response = seo_client.get("/static/img/" + filename)
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", response.data[16:24]) == (size, size)
    assert "X-Robots-Tag" not in response.headers


def test_root_favicon_is_the_same_public_ico_asset_without_public_session_caching(seo_client):
    response = seo_client.get("/favicon.ico")
    asset = seo_client.get("/static/img/favicon.ico")
    assert response.status_code == asset.status_code == 200
    assert response.data == asset.data
    assert response.mimetype == "image/vnd.microsoft.icon"
    reserved, image_type, image_count = struct.unpack("<HHH", response.data[:6])
    assert reserved == 0 and image_type == 1 and image_count >= 1
    assert "X-Robots-Tag" not in response.headers
    assert "public" not in response.headers.get("Cache-Control", "").lower()
