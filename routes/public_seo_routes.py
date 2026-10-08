"""Search discovery for public marketing pages only."""
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Blueprint, Response, abort, current_app, render_template

from app.middleware import NON_INDEXABLE_PREFIXES
from service.public_site_content import SOLUTIONS


bp = Blueprint("public_seo", __name__)


def _site_origin():
    # BASE_URL is validated configuration. Do not derive canonical URLs from Host.
    return current_app.container.settings.BASE_URL.rstrip("/")


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


@bp.get("/sitemap.xml")
def sitemap():
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    paths = ["/"] + ["/solutions/" + slug for slug in SOLUTIONS]
    for path in paths:
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = _site_origin() + path
    return Response(tostring(urlset, encoding="utf-8", xml_declaration=True),
                    mimetype="application/xml")
