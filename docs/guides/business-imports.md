# Importing a business's information

How to get a new client's products, prices, answers and locations into V7, and how to
keep them current. Everything goes through **My Business → Data Sources & Sync**.

## The safe way to use Claude or Codex

Use an AI tool to *prepare a file*, never to write into a live workspace.

1. Get the client's written authorisation and the material itself (their export, price
   list, documents, or the pages of their own website).
2. Give the tool only that material. Do not give it console passwords, API keys,
   database access or anything about other clients.
3. Ask it to produce the JSON bundle below. Ask it to copy facts exactly and to leave
   out anything it is unsure of rather than guess.
4. In the client's workspace choose **Upload a file**, pick the bundle, say where the
   information came from and which tool prepared it, and tick the authorisation.
5. Read the preview. Untick anything wrong, apply the rest. **Undo** is available from
   Recent changes while the information has not been edited since.

V7 validates every row again whatever produced the file, so a mistake by the tool shows
up in the preview instead of in a customer conversation.

## JSON bundle

Any of the three lists may be omitted.

```json
{
  "products": [
    {"id": "A-100", "name": "Oak desk", "price": 120.00, "category": "Furniture",
     "in_stock": true, "stock_quantity": 4, "unit": "each", "tags": ["desk", "oak"]}
  ],
  "faqs": [
    {"question": "Do you deliver?", "answer": "Yes, free over £50.", "tags": ["delivery"]}
  ],
  "locations": [
    {"name": "High Street", "address": "1 High Street", "postcode": "AB1 2CD",
     "phone": "01234 567890", "hours": {"mon": "09:00-17:00", "sat": "10:00-16:00"}}
  ]
}
```

- `name` and `price` are required for a product. `id` should be the client's own stable
  reference; without it the name is used, so renaming a product later creates a new one.
- `price` is a number, or text such as `£7.99` or `7,99`. Text that is not a price
  ("call us") is rejected and reported.
- `hours` uses `mon` `tue` `wed` `thu` `fri` `sat` `sun`.
- Services go in `products`. Policies go in `faqs` as a question and its answer.

## Spreadsheet (CSV)

Save Excel sheets as CSV first. The first row holds column names; these are recognised
(any capitalisation): **name** (or title, product, service), **price** (or regular
price, amount), **category** (or type), **sku**, **id**, **stock** / **in stock** /
**availability**, **quantity** (or stock quantity, qty), **unit**, **tags**. A file with
**question** and **answer** columns is read as FAQs. Comma, semicolon and tab
separators all work.

## What the preview tells you

| Label | Meaning |
|---|---|
| New product / answer / location | Will be added. |
| Update product | An existing item will change; old and new values are shown. |
| Matches a product you already have | Found by name or SKU. It will be updated, not duplicated. |
| Changed in both places | The client edited this in V7 and the file differs. Unticked: V7's version stays unless you tick it. |
| Unusual text | The text reads like an instruction to an AI. Left out unless you include it. |
| Cannot be imported | Missing name or price, or a repeated row. |

## Keeping it current

| The client has | Use | Result |
|---|---|---|
| WooCommerce | **WooCommerce**: store address and a *read-only* REST API key. | Checked on a schedule; optional webhooks for instant updates. |
| Shopify | **Shopify**: shop domain and an app with `read_products` only. | Same. |
| Another site or system with a developer | **Another website or system**: a URL returning the product list as JSON. | Checked on a schedule; optional signed push. |
| Anything else | **Upload a file**, then **Import updated file** on that source whenever it changes. | Manual. Do not promise automatic updates. |

The first import from a connected store is always shown for approval. After that, the
owner chooses whether routine updates apply by themselves. Unusual changes always wait.

### Custom feed format

`GET` the feed URL (optionally with `Authorization: Bearer <token>`) must return:

```json
{"currency": "GBP", "products": [
  {"id": "A-100", "name": "Oak desk", "price": 120.0, "category": "Furniture",
   "in_stock": true, "active": true, "updated_at": "2026-11-10T10:00:00Z"}
]}
```

The list must be complete: a product that disappears from it is proposed for removal.
`"active": false` means "do not offer this". To push changes immediately, `POST` to the
delivery address shown when connecting, with header
`X-V7-Signature: t=<unix time>,s=<hex HMAC-SHA256 of "<t>.<raw body>" using the secret>` and body
`{"event": "changed", "products": [...], "deleted_ids": ["A-100"]}`
(or `"event": "replace"` with the complete list).

### Instant updates from WooCommerce or Shopify

Optional. After connecting, V7 shows a delivery address (and, for WooCommerce, a
secret) once. In the store, add webhooks for product created, updated and deleted that
send to that address. Shopify signs with the app's own secret key, which was entered
when connecting with a client ID and secret.

## If something looks wrong

- **"Your store connection needs attention."** V7 could not reach the store after
  several tries, or the key was refused. Existing information is kept. Use Sync Now, or
  disconnect and connect again with a new key.
- **"Some product updates couldn't be imported."** Some products had no name or usable
  price in the store. Fix them there; the next check picks them up.
- **"This has not updated for a while."** Recent store changes may be missing. Ask the
  platform operator whether automatic updates are switched on.
