# Website widget workspace

The **Website demo** appearance preset under **Appearance → Choose a style**
applies the same Studio layout and green/grey palette used on Vertex Seven's
website. It changes only the layout and five colours. The company's assistant
name, greeting, logos, website restrictions and business knowledge remain its
own. Review the preview, adjust any colours, then choose **Save widget** to apply
it to new customer widget loads. Studio's preview includes the live widget's
accent header line, avatar size and message corners.

The owner console's **Website widget** page combines appearance, private agent
testing and installation. Existing `/console/test` links still open the Test
conversation tab; `/console/website` opens Appearance. Entering or leaving these
pages reloads the document so its microphone policy is applied correctly.

## Appearance

Choose one of ten layouts: Midnight, Daylight, Minimal, Editorial, Neon, Warm,
Glass, Studio, Soft or Bold. Start with a named palette or set six-digit hex
colours for the accent, background, header surfaces, message text and customer
bubbles. Blank optional colours follow the selected style. Text uses a readable
dark or light alternative when the selected colour has insufficient contrast.
The preview updates before saving; saved changes apply to new customer widget
loads. Existing legacy theme colours and font stacks remain supported.

## Testing and voice

Test conversation uses saved business information in a separate private test
session. It does not create sales leads; provider calls still count toward API
usage. Website knowledge and customer next steps are available below the test.

The microphone fills the message field for review before sending. Browser speech
recognition is used when supported. Public widgets can use the existing server
transcription fallback when it is configured. Recording is user initiated and
limited to 30 seconds. Reply buttons offer Listen/Stop; reading new replies aloud
is optional and uses the browser's speech synthesis. Sending, restarting, leaving
the page or closing an embedded widget cancels active voice work. Device and
browser support varies; typing is always available.

Microphones require a secure context, customer permission and appropriate
permissions on the embedding website. V7 grants microphone permission to its
chat and widget console documents only; unrelated pages retain the denied policy.

## Installation and permissions

Save the exact approved website origins and copy the floating script, embedded
panel or direct chat link. Each company's code retains its tenant identifier.
Public widget tests count as customer activity. The Implementation guide remains
available for website builders and troubleshooting.

The platform's own marketing site can use the same floating widget by setting
`PUBLIC_WIDGET_TENANT` to an existing, configured and active company key. Blank
or invalid values disable this optional embed. Configure its approved website
origins, business knowledge, branding and normal subscription requirements before
enabling it. It appears only on the homepage, about page, setup guide and known
solution pages; account pages, management screens and tenant chat pages do not
embed it. Page query parameters cannot select a different company. Privacy
controls take priority while open. Typing and browser reply playback are available;
the marketing pages retain their existing denied microphone policy.

Without an AI provider, the widget can answer from saved business knowledge.
An exact pricing FAQ can describe a service's fees when no named catalogue item
supplies the answer. Named catalogue prices and availability remain authoritative;
a loosely matching FAQ does not replace an explicit product enquiry.

For the platform's own first-party marketing business, a deployment administrator
can explicitly set `PLATFORM_MARKETING_TENANT` to one exact existing company key.
The exemption applies only when that company was created by a platform admin and
has no business-owner assignment in `managed_businesses`. It returns activation
status `platform_internal`; it does not create paid invoices, change billing
totals, grant management permissions or exempt external AI/provider costs.
Business-owner-created companies and all other company keys retain verified
subscription and implementation-payment checks. There is no dashboard or tenant
document switch for this exemption. Leave it blank to disable, and do not use it
for a customer tenant. Removing it immediately restores normal activation checks.
Authentication, tenant isolation, approved origins, CSRF, rate limits and audit
logging still apply. `PUBLIC_WIDGET_TENANT` separately controls whether the site
embeds the widget; setting the fee exemption alone does not publish it.

Viewing requires `business_settings.read`; changes require
`business_settings.write`. Server authorization, CSRF checks, active-company
requirements, origin validation and audit logging still apply. A delayed save
cannot replace a newly selected company's editor data.

Main files: `Console.svelte`, `WidgetDesigner.svelte`, `widgetAppearance.ts`,
`AgentTest.svelte`, public widget JS/CSS/template, widget admin/public routes,
branding validation and application response headers. No new dependencies or
provider credentials are required for these interface changes.
