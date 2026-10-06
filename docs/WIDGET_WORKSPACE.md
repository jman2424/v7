# Website widget workspace

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

Viewing requires `business_settings.read`; changes require
`business_settings.write`. Server authorization, CSRF checks, active-company
requirements, origin validation and audit logging still apply. A delayed save
cannot replace a newly selected company's editor data.

Main files: `Console.svelte`, `WidgetDesigner.svelte`, `widgetAppearance.ts`,
`AgentTest.svelte`, public widget JS/CSS/template, widget admin/public routes,
branding validation and application response headers. No new dependencies or
provider credentials are required for these interface changes.
