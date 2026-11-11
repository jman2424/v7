# Conversation memory and website navigation

## Owner controls

The API section includes AI memory controls for an active business owner or
platform administrator. Memory is scoped to the tenant and the current signed
conversation identity. It does not recognize a returning customer across new
conversations.

Defaults are enabled, 12 individual recent messages, a 2,048-token transcript
budget and a 60-minute lifetime. Supported limits are 2–40 messages, 256–16,384
transcript tokens and 5–10,080 minutes. The transcript uses a conservative UTF-8
byte budget, including JSON and framing overhead. Whole oversized messages are
omitted; recent messages that fit are preferred. Verified task facts are stored
separately, so this is not a cap on the complete model request.

Owners use authenticated GET, PUT and DELETE `/admin/api/ai-model/memory` with
their authorized `tenant`. PUT accepts `settings` and the current `revision`;
DELETE accepts the revision. Mutations require CSRF and the existing settings
permission. Concurrent configuration edits return 409. Disabling or clearing
rotates the namespace so old in-flight turns cannot restore forgotten context.
Clearing affects subsequent turns and does not erase saved conversation records,
leads, audit entries or financial data. Disabled memory stores no new context.

SQLite shares state across workers on the same persistent filesystem. PostgreSQL
shares it across hosts through the existing restricted tenant connection and a
private FORCE-RLS table. Each turn batches reads/writes, limits payload size and
merges distinct-key updates under a transaction lock. Expiry is checked on every
read; expired database rows are cleaned in bounded batches during later activity.
Use PostgreSQL when deploying multiple hosts. Apply migration
`20261017192010_conversation_memory_and_plan_changes.sql` first.

## Cost

Remembered text is sent as input on later replies. Longer history can improve
follow-up recall and also increase provider input charges and latency. Shorter
history costs less but may omit older details. No extra summarization model call
is introduced. Storage and database operations still have infrastructure cost.

The API screen estimates transcript-only uncached input cost per 1,000 replies:

`history_tokens × configured input USD per million tokens ÷ 1,000`

For example, a 2,048-token budget at $2 per million input tokens gives a maximum
transcript estimate of $4.096 per 1,000 replies for one grounded-answer call per
reply. At 8,192 tokens it is $16.384. Most short conversations use less. The screen
uses the selected model's server-configured rate, not these illustrative numbers.
This is not the total request cost: new user messages, business facts, verified
task facts, output/reasoning and additional provider calls add cost. Provider
caching, exchange rates and wallet pricing affect actual charges. The existing
usage ledger remains the source of actual billed usage.

OpenAI's [conversation state guide](https://developers.openai.com/api/docs/guides/conversation-state)
explains how conversation context contributes to input usage.

## Navigation activity

Approved website buttons receive a signed click proof bound to tenant,
conversation, message, label and validated destination. The widget preserves
normal anchor navigation, adds a visible **Clicked** indicator and a local
activity bubble, and sends a keepalive request to POST `/chat/navigation-click`.
The endpoint checks the signed conversation token, expiring click proof, allowed
origin, rate limit and current destination validation. Arbitrary client URLs and
labels cannot create an event.

Stored events are deduplicated per issued button and appear in the owner's
conversation timeline as customer activity. They do not increment message,
booking, purchase or conversion totals and do not trigger an OpenAI call.
A reported click does not establish that the destination loaded or an action
completed. Navigation still works if tracking fails; a later click can retry
recording. Private Agent Test buttons show local clicked state only.

## Answer coverage and formatting

The grounded assistant is instructed to address each part of a mixed business
question. The source renderer preserves full policy conditions alongside requested
product comparisons, includes requested public product options, and omits
inactive/private options. Support questions do not automatically turn into sales
shortlists. Real navigation buttons replace redundant generic button instructions.
Answers and actions remain limited to configured facts and supported integrations;
missing business information must not be invented.

Clear requests for unrelated coding or homework are rejected before a provider
call. Questions about the business's technical services and documented widget/API
integration remain eligible for grounded help. Simple social check-ins and short
customer definitions such as `amber = ready` are handled without a model call.
Recall searches only this conversation's bounded customer messages and uses the
latest definition. It never promotes those definitions to public business facts.
Disabling memory, expiry and the configured history budget also apply to this
recall. Unknown business terms still reach business knowledge retrieval.

The final web-chat response converts exact approved URLs into navigation actions,
including URLs introduced by full policy/FAQ rendering after the model's answer.
Disabled and unknown destinations cannot become buttons. WhatsApp retains text
links. The widget's existing signed click reporting and visible Clicked state
apply to the resulting buttons.

The evaluation suite includes a customer-transcript regression scenario alongside
the retail and service quality scenarios. It uses the production default memory
budget and distinguishes local turns from paid provider completions. Run
`python -m evals.agent_eval` for offline validation; the explicit `--live` flag
and an authorized test credential are required for paid model checks.
