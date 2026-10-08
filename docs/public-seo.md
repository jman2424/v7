# Public search pages

The homepage and eight `/solutions/<slug>` pages describe V7's public product
capabilities. The allowlist and page copy live in `service/public_site_content.py`;
`routes/public_seo_routes.py` renders the pages and discovery files.

Canonical, social-preview and sitemap URLs use validated `BASE_URL`, never the
request Host or query parameters. Production should set this to the preferred
HTTPS origin (`https://vertex-seven.com` for the current deployment).

`/sitemap.xml` includes only the homepage and the eight allowlisted solution
pages. `/robots.txt` permits public content and static assets, and excludes
operational, account and chat paths. Those paths also receive `X-Robots-Tag:
noindex, nofollow`. These search directives supplement authentication; they are
not access controls. No tenant data is used to render public product content.

Submit the public sitemap from the business's verified Google Search Console
and Bing Webmaster Tools properties. Account ownership and any required DNS
verification must be completed in those services. Discovery files and structured
data do not guarantee indexing, rich results or ranking.

The homepage product schema describes the public monthly platform plan. Its
unit price is £480 per month including VAT. Both the visible pricing section
and schema descriptions disclose separate £240 implementation, API usage and
optional WhatsApp charges. No reviews or ratings are fabricated. Search engines
may display only part of this information or choose not to show a rich result.

Relevant checks:

```sh
python -m pytest tests/test_public_seo.py tests/test_owner_console.py tests/test_platform_security.py::test_public_homepage_does_not_expose_business_data -q
```
