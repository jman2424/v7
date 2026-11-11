# Language support

The console language picker supports English, Spanish, French and Arabic.
Subscription, prepaid credit, model selection, WhatsApp setup and the agent test
screen use the shared dictionaries in `dashboard/static/i18n/`. Arabic uses
right-to-left layout; phone numbers, provider IDs and webhook URLs retain their
left-to-right technical representation. The WhatsApp number helper also accepts
Arabic-Indic and Eastern Arabic-Indic digits without guessing a country code.

The WhatsApp guide translates local readiness states, known blockers, copy
confirmations and setup summaries. It reports the server's audio-decoder
capability rather than assuming compressed recordings are unsupported. Opening
the guide in Subscription loads its configuration; closing or leaving it aborts
pending reads. Setup remains operator-assisted and provider billing remains
separate from prepaid AI credit.

Agent test starter questions are inserted in the selected interface language.
Voice controls use the browser's current document language. Microphone and
speech services still depend on browser support and the user's permission.
Customer text, business names, catalog facts and provider-generated replies are
not replaced with interface dictionary translations. Response language depends
on the configured knowledge and available AI provider; unfunded AI accounts do
not provide automatic translation of saved business content.

Unicode input reaches the business handler instead of being rejected by an
ASCII-only symbols check. Existing empty-input and punctuation-only guards,
tenant authorization, provider metering and credit checks remain enforced.

Checks:

```text
cd frontend
node --test tests/*.test.cjs
npm run check
npm run build
```

Run `pytest` from the repository root for backend checks. Local socket tests need
loopback networking on Windows; native PostgreSQL tests need a disposable test
database. Translation checks cover text, dynamic statuses and placeholders in
the billing and channel screens so missing entries fail automatically.
