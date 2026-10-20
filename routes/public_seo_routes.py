"""Search discovery for public marketing pages only."""
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Blueprint, Response, abort, current_app, render_template, request, send_from_directory

from app.middleware import NON_INDEXABLE_PREFIXES
from service.public_site_content import SOLUTIONS
from service.public_brand_content import ABOUT, SETUP_GUIDE
from service.public_faq_content import public_faq
from service.public_buying_content import BUYING_GUIDE, public_pricing
from service.public_resource_content import RESOURCE_PAGES
from service.plan_catalog import public_plans, vat_percent


bp = Blueprint("public_seo", __name__)


def _site_origin():
    # BASE_URL is validated configuration. Do not derive canonical URLs from Host.
    return current_app.container.settings.BASE_URL.rstrip("/")


@bp.get("/favicon.ico")
def favicon():
    # A fixed public asset, never a tenant file or a caller-supplied path.
    return send_from_directory(current_app.static_folder, "img/favicon.ico",
                               mimetype="image/vnd.microsoft.icon")


@bp.get("/solutions/<slug>")
def solution_page(slug):
    if slug not in SOLUTIONS:
        abort(404)
    site_origin = _site_origin()
    return render_template("solution.html", solution=SOLUTIONS[slug],
                           solutions=SOLUTIONS, slug=slug, site_origin=site_origin,
                           canonical_url=site_origin + "/solutions/" + slug)


@bp.get("/robots.txt")
def robots():
    lines = ["User-agent: *", "Allow: /", "Allow: /static/"]
    lines.extend("Disallow: " + path for path in NON_INDEXABLE_PREFIXES)
    lines.extend(["Disallow: /privacy?tenant=", "", "Sitemap: " + _site_origin() + "/sitemap.xml", ""])
    return Response("\n".join(lines), mimetype="text/plain")


@bp.get("/about")
def about_page():
    site_origin = _site_origin()
    return render_template("solution.html", solution=ABOUT, solutions=SOLUTIONS,
                           slug=None, brand_page=True, site_origin=site_origin,
                           canonical_url=site_origin + "/about")


@bp.get("/sitemap.xml")
def sitemap():
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    paths = ["/", "/about", "/faqs", "/guides/getting-started", "/pricing", "/guides/choosing-a-website-chatbot"] + ["/solutions/" + slug for slug in SOLUTIONS] + list(RESOURCE_PAGES)
    for path in paths:
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = _site_origin() + path
    return Response(tostring(urlset, encoding="utf-8", xml_declaration=True),
                    mimetype="application/xml")


@bp.get("/guides/getting-started")
def setup_guide():
    site_origin = _site_origin()
    return render_template("solution.html", solution=SETUP_GUIDE, solutions=SOLUTIONS,
                           slug=None, brand_page=True, site_origin=site_origin,
                           canonical_url=site_origin + "/guides/getting-started")


@bp.get("/faqs")
def faq_page():
    site_origin = _site_origin()
    return render_template("solution.html", solution=public_faq(), solutions=SOLUTIONS,
                           slug=None, brand_page=True, faq_page=True, site_origin=site_origin,
                           canonical_url=site_origin + "/faqs")


@bp.get("/pricing")
def pricing_page():
    site_origin = _site_origin()
    return render_template("solution.html", solution=public_pricing(), solutions=SOLUTIONS,
                           slug=None, brand_page=True, pricing_page=True, site_origin=site_origin,
                           subscription_plans=public_plans(), subscription_vat_percent=vat_percent(),
                           canonical_url=site_origin + "/pricing")


@bp.get("/guides/choosing-a-website-chatbot")
def buying_guide():
    site_origin = _site_origin()
    return render_template("solution.html", solution=BUYING_GUIDE, solutions=SOLUTIONS,
                           slug=None, brand_page=True, site_origin=site_origin,
                           canonical_url=site_origin + "/guides/choosing-a-website-chatbot")


@bp.get('/integrations')
@bp.get('/security')
@bp.get('/guides/business-knowledge')
@bp.get('/guides/business-use-cases')
def resource_page():
    site_origin = _site_origin()
    return render_template('solution.html', solution=RESOURCE_PAGES[request.path],
                           solutions=SOLUTIONS, slug=None, brand_page=True,
                           resource_page=True, site_origin=site_origin,
                           canonical_url=site_origin + request.path)
