# Public search pages

The homepage, `/about` brand page and eight `/solutions/<slug>` pages describe V7's public product
capabilities. The allowlist and page copy live in `service/public_site_content.py`;
`routes/public_seo_routes.py` renders the pages and discovery files.

Canonical, social-preview and sitemap URLs use validated `BASE_URL`, never the
request Host or query parameters. Production should set this to the preferred
HTTPS origin (`https://vertex-seven.com` for the current deployment).

`/sitemap.xml` includes only the homepage, `/about` and the eight allowlisted solution
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

## Optional public analytics

`GA4_MEASUREMENT_ID` configures the public GA4 web-stream identifier. It must
match `G-` followed by 6–20 uppercase letters or digits; missing or invalid values
disable analytics without preventing startup. The identifier is public, not a
credential. It is exposed only to the homepage and the eight allowlisted solution
pages. Account, console, API, chat, widget and tenant privacy pages receive no
analytics configuration and retain their original Content Security Policy.

Analytics uses a separate explicit opt-in. Existing language-only
`v7_preferences=all` cookies never grant analytics consent. Before opt-in, after
refusal, or after consent expires, Google tags and requests stay blocked by the
public loader. Use basic consent mode; advanced mode sends cookieless measurements
while consent is denied and is outside this implementation's scope. Withdrawal
stops later analytics events and clears analytics cookies without removing sign-in
or security cookies. Visitors can change their choice using Cookie preferences.

Collect only public page views with a safe public URL and referrer: omit query
strings and fragments, and never send account identifiers, form values, customer
messages or tenant information. Disable enhanced measurement, automatic extra
events, Google Signals, advertising features and ads personalization in the GA4
property. The operator selects and verifies the provider retention setting; the
intended event-data retention is two months. Cookie/privacy notices must describe
this optional processing and the actual selected retention setting. Controller
name, contact and lawful-basis settings remain business-supplied; do not invent
them from provider login details.

For configured public HTML only, CSP permits the Google tag script origin and
the exact tag/collection connection origins: `https://www.googletagmanager.com`,
`https://www.google-analytics.com` and `https://region1.google-analytics.com`.
No script `unsafe-inline`, `unsafe-eval`, wildcard or advertising origins are
added. See Google's [consent mode overview](https://developers.google.com/tag-platform/security/concepts/consent-mode)
and [CSP guidance](https://developers.google.com/tag-platform/security/guides/csp).

Relevant checks:

```sh
python -m pytest tests/test_public_analytics.py tests/test_public_seo.py tests/test_owner_console.py tests/test_platform_security.py::test_public_homepage_does_not_expose_business_data -q
```

The `/about` page uses public brand facts from `service/public_brand_content.py`,
including the online-only UK service model, product setup, limitations and prices.
It does not use tenant records or provider login details. It deliberately receives
no Analytics configuration; existing tracking remains limited to the original
nine marketing pages. The homepage title and social titles include Vertex Seven
to distinguish V7 Agents from unrelated products with similar names.


The public `/guides/getting-started` page supplies a setup checklist and clearly fictional retail, service and branch demonstrations. It uses the existing public page template and is linked from public footers. The sitemap now contains 11 URLs. It adds no customer claims or Analytics scope.

The homepage now offers a demo enquiry via the business email address, using a mailto link. It opens the visitor's email app and does not claim that an enquiry has been sent or create a server-side lead. Inbox delivery still requires an end-to-end mailbox test.
