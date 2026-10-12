"""Server-priced prepaid AI credits, fulfilled only by verified Stripe callbacks.

Checkout redirects never grant money. Each signed callback re-reads Stripe's
payment objects and matches a durable, tenant-scoped checkout snapshot before
passing a cumulative payment/refund/dispute state to the wallet ledger.
"""
from __future__ import annotations

import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from service import session_store, subscriptions, usage_wallet
from service.plan_catalog import VAT_PERCENT

_PACKS = {"gbp_5": 500, "gbp_20": 2000, "gbp_50": 5000}
_KIND = "ai_credit"
_VERSION = "prepaid_v1"
_REQUEST = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
_REFERENCE = re.compile(r"[a-f0-9]{48}\Z")
_TYPES = {"checkout.session.completed", "checkout.session.async_payment_succeeded",
          "checkout.session.async_payment_failed", "checkout.session.expired",
          "invoice.paid", "invoice.payment_succeeded", "invoice.updated", "invoice.finalized",
          "invoice.payment_failed", "invoice.voided", "invoice.marked_uncollectible"}
_REVERSALS = {"charge.refunded", "refund.created", "refund.updated", "refund.failed",
              "charge.dispute.created", "charge.dispute.updated", "charge.dispute.closed",
              "charge.dispute.funds_withdrawn", "charge.dispute.funds_reinstated"}


def packs():
    return [{"id": key, "credit_pence": value, "subtotal_pence": value,
             "tax_pence": value * VAT_PERCENT // 100,
             "total_pence": value * (100 + VAT_PERCENT) // 100,
             "currency": "GBP", "vat_percent": VAT_PERCENT} for key, value in _PACKS.items()]


def _schema(db):
    if session_store._using_postgres():
        return
    db.execute("""CREATE TABLE IF NOT EXISTS usage_checkout_requests (
        tenant TEXT NOT NULL, reference TEXT PRIMARY KEY, request_id TEXT NOT NULL,
        pack_id TEXT NOT NULL, credit_pence BIGINT NOT NULL CHECK(credit_pence>0),
        subtotal_pence BIGINT NOT NULL CHECK(subtotal_pence>0),
        tax_pence BIGINT NOT NULL CHECK(tax_pence>=0), total_pence BIGINT NOT NULL CHECK(total_pence>0),
        vat_percent INTEGER NOT NULL, tax_rate TEXT NOT NULL,
        livemode INTEGER NOT NULL CHECK(livemode IN(0,1)), checkout TEXT UNIQUE,
        payment_id TEXT UNIQUE, invoice_id TEXT UNIQUE, checkout_url TEXT, expires_at BIGINT,
        status TEXT NOT NULL DEFAULT 'preparing', created BIGINT NOT NULL,
        UNIQUE(tenant,request_id), CHECK(total_pence=subtotal_pence+tax_pence))""")
    db.execute("CREATE INDEX IF NOT EXISTS usage_checkout_requests_tenant ON usage_checkout_requests(tenant,created)")


def _write_lock(db):
    if not session_store._using_postgres():
        db.execute('BEGIN IMMEDIATE')
    return ' FOR UPDATE' if session_store._using_postgres() else ''


def _id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[A-Za-z0-9_]+", value):
        raise ValueError("invalid_usage_payment_object")
    return value


def _integer(value, expected=None):
    if type(value) is not int or value < 0 or (expected is not None and value != expected):
        raise ValueError("usage_payment_amount_mismatch")
    return value


def _request_id(value):
    if not isinstance(value, str) or not _REQUEST.fullmatch(value):
        raise ValueError("invalid_usage_request_id")
    return value


def _snapshot(tenant, reference):
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise ValueError("invalid_usage_payment_reference")
    with subscriptions.connection(tenant) as db:
        _schema(db)
        row = db.execute("SELECT * FROM usage_checkout_requests WHERE tenant=? AND reference=?", (tenant, reference)).fetchone()
    if not row:
        raise ValueError("unknown_usage_payment_reference")
    return dict(row)


def _metadata(obj, row=None):
    data = obj.get("metadata")
    if not isinstance(data, dict) or data.get("kind") != _KIND:
        raise ValueError("invalid_usage_payment_metadata")
    from routes import get_container
    tenant = data.get("tenant")
    storage = get_container().storage
    if not isinstance(tenant, str) or storage.validate_tenant_key(tenant) != tenant or not storage.tenant_exists(tenant):
        raise ValueError("invalid_usage_payment_tenant")
    row = row or _snapshot(tenant, data.get("usage_ref"))
    expected = {"kind": _KIND, "tenant": row["tenant"], "usage_ref": row["reference"],
                "usage_version": _VERSION, "pack_id": row["pack_id"]}
    if any(data.get(key) != value for key, value in expected.items()):
        raise ValueError("usage_payment_metadata_mismatch")
    return row


def _common(obj, row, prefix, expected_id=None):
    identity = _id(obj.get("id"), prefix)
    if expected_id and identity != expected_id:
        raise ValueError("usage_payment_identity_mismatch")
    if obj.get("currency") != "gbp" or type(obj.get("livemode")) is not bool or obj["livemode"] != bool(row["livemode"]):
        raise ValueError("usage_payment_currency_or_mode_mismatch")
    return identity


def checkout_requests(tenant):
    with subscriptions.connection(tenant) as db:
        _schema(db)
        rows = db.execute("SELECT reference,request_id,pack_id,checkout,status,expires_at,credit_pence,total_pence "
                          "FROM usage_checkout_requests WHERE tenant=? ORDER BY created DESC,reference DESC LIMIT 20", (tenant,)).fetchall()
    return [{**dict(row), "checkout_id": row["checkout"]} for row in rows]


def checkout(tenant, email, pack_id, request_id, base_url):
    if subscriptions.internal_business(tenant):
        raise ValueError("internal_business_has_no_customer_usage_charge")
    from service.tenant_access import activation
    if not activation(tenant)["active"]:
        raise ValueError("business_awaiting_activation")
    request_id = _request_id(request_id)
    if not isinstance(pack_id, str) or pack_id not in _PACKS:
        raise ValueError("invalid_usage_pack")
    stripe = subscriptions.client()
    if not subscriptions.configured():
        raise ValueError("stripe_setup_required")
    # Persist the price and request binding before any Checkout network call.
    # Retrying the same request after a timeout reuses Stripe's idempotency key.
    with subscriptions.connection(tenant) as db:
        _schema(db)
        existing = db.execute("SELECT * FROM usage_checkout_requests WHERE tenant=? AND request_id=?", (tenant, request_id)).fetchone()
    if existing:
        row = dict(existing)
        if row["pack_id"] != pack_id:
            raise ValueError("usage_request_mismatch")
    else:
        tax_rate = subscriptions._tax()
        pack = next(item for item in packs() if item["id"] == pack_id)
        with subscriptions.connection(tenant) as db:
            _schema(db)
            db.execute("INSERT INTO usage_checkout_requests (tenant,reference,request_id,pack_id,credit_pence,subtotal_pence,"
                       "tax_pence,total_pence,vat_percent,tax_rate,livemode,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(tenant,request_id) DO NOTHING",
                       (tenant, secrets.token_hex(24), request_id, pack_id, pack["credit_pence"], pack["subtotal_pence"],
                        pack["tax_pence"], pack["total_pence"], VAT_PERCENT, tax_rate,
                        int(stripe.api_key.startswith(("sk_live_", "rk_live_"))), int(time.time())))
            row = dict(db.execute("SELECT * FROM usage_checkout_requests WHERE tenant=? AND request_id=?", (tenant, request_id)).fetchone())
        if row["pack_id"] != pack_id:
            raise ValueError("usage_request_mismatch")
    if row["checkout"]:
        return _checkout_result(_refresh_checkout(row))
    if row['created'] < time.time() - 23*3600:
        # Stripe may discard an idempotency key after 24 hours. Never create a
        # second unknown session by retrying an old ambiguous network failure.
        raise ValueError('usage_checkout_requires_review')
    metadata = {"tenant": tenant, "kind": _KIND, "usage_ref": row["reference"], "usage_version": _VERSION, "pack_id": pack_id}
    data = {"mode": "payment", "managed_payments[enabled]": "false",
            "client_reference_id": tenant, "invoice_creation[enabled]": "true",
            "success_url": base_url + "/console/subscription?" + urlencode({"tenant": tenant, "credit": "processing"}),
            "cancel_url": base_url + "/console/subscription?" + urlencode({"tenant": tenant}),
            "line_items[0][quantity]": 1, "line_items[0][price_data][currency]": "gbp",
            "line_items[0][price_data][unit_amount]": row["subtotal_pence"],
            "line_items[0][price_data][tax_behavior]": "exclusive",
            "line_items[0][price_data][product_data][name]": "V7 prepaid AI processing credit",
            "line_items[0][tax_rates][0]": row["tax_rate"]}
    with subscriptions.connection(tenant) as db:
        saved = db.execute("SELECT customer FROM billing_contracts WHERE tenant=? AND kind IN ('platform','implementation') "
                           "AND customer IS NOT NULL ORDER BY CASE WHEN kind='platform' THEN 0 ELSE 1 END LIMIT 1", (tenant,)).fetchone()
    if saved and saved['customer']:
        data['customer'] = _id(saved['customer'], 'cus')
    else:
        # Billing identity belongs to the company, never the platform operator
        # who opened this checkout. Stripe collects it on the hosted form.
        data['customer_creation'] = 'always'
    for prefix in ("metadata", "payment_intent_data[metadata]", "invoice_creation[invoice_data][metadata]"):
        data.update({prefix + "[" + key + "]": value for key, value in metadata.items()})
    result = stripe.stripe_request("POST", "/v1/checkout/sessions", data, idempotency_key="v7-ai-credit-" + row["reference"])
    checkout_id = _id(result.get("id"), "cs")
    url = subscriptions._safe_url(result.get("url"), "checkout.stripe.com")
    if not url or type(result.get("expires_at")) is not int or result["expires_at"] <= time.time():
        raise ValueError("stripe_response_invalid")
    with subscriptions.connection(tenant) as db:
        _schema(db)
        suffix = _write_lock(db)
        current = dict(db.execute("SELECT * FROM usage_checkout_requests WHERE tenant=? AND reference=?" + suffix, (tenant, row["reference"])).fetchone())
        if current["checkout"] and current["checkout"] != checkout_id:
            raise ValueError("usage_checkout_binding_mismatch")
        db.execute("UPDATE usage_checkout_requests SET checkout=?,checkout_url=?,expires_at=?,"
                   "status=CASE WHEN status='preparing' THEN 'pending' ELSE status END WHERE tenant=? AND reference=?",
                   (checkout_id, url, result["expires_at"], tenant, row["reference"]))
    return _checkout_result(_snapshot(tenant, row["reference"]))


def _checkout_result(row):
    return {"reference": row["reference"], "request_id": row["request_id"], "pack_id": row["pack_id"],
            "checkout_id": row["checkout"], "url": row["checkout_url"] if row["status"] == "pending" else None,
            "status": row["status"], "credit_pence": row["credit_pence"], "total_pence": row["total_pence"]}


def _refresh_checkout(row):
    """Confirm dead Checkout sessions without ever crediting a browser request."""
    if row['status'] in {'paid', 'expired', 'failed'}:
        return row
    stripe = subscriptions.client()
    checkout_id = _id(row['checkout'], 'cs')
    canonical = stripe.stripe_request('GET', '/v1/checkout/sessions/' + checkout_id)
    _metadata(canonical, row)
    _common(canonical, row, 'cs', checkout_id)
    if canonical.get('mode') != 'payment' or canonical.get('subscription') or canonical.get('client_reference_id') != row['tenant']:
        raise ValueError('usage_checkout_mode_mismatch')
    status = None
    if canonical.get('status') == 'expired' and canonical.get('payment_status') == 'unpaid':
        status = 'expired'
    elif canonical.get('status') == 'complete' and canonical.get('payment_status') == 'unpaid':
        payment_id = _id(canonical.get('payment_intent'), 'pi')
        payment = stripe.stripe_request('GET', '/v1/payment_intents/' + payment_id)
        _common(payment, row, 'pi', payment_id)
        _metadata(payment, row)
        _integer(payment.get('amount'), row['total_pence'])
        if payment.get('status') in {'canceled', 'requires_payment_method'}:
            status = 'failed'
    elif canonical.get('status') == 'complete' and canonical.get('payment_status') == 'paid':
        # Only the webhook may turn processing into available wallet credit.
        return {**row, 'status':'processing'}
    if status:
        with subscriptions.connection(row['tenant']) as db:
            _schema(db)
            suffix = _write_lock(db)
            current = dict(db.execute('SELECT * FROM usage_checkout_requests WHERE tenant=? AND reference=?' + suffix,
                                      (row['tenant'], row['reference'])).fetchone())
            if current['status'] != 'paid':
                db.execute('UPDATE usage_checkout_requests SET status=? WHERE tenant=? AND reference=?',
                           (status, row['tenant'], row['reference']))
                current['status'] = status
        return current
    return row


def _tax_verified(stripe, row):
    _id(row["tax_rate"], "txr")
    tax = stripe.stripe_request("GET", "/v1/tax_rates/" + row["tax_rate"])
    try:
        percentage = Decimal(str(tax.get("percentage")))
    except InvalidOperation as exc:
        raise ValueError("usage_payment_tax_mismatch") from exc
    # Archived rates remain valid snapshots for an already-created payment.
    if tax.get("inclusive") is not False or percentage != row["vat_percent"]:
        raise ValueError("usage_payment_tax_mismatch")


def _disputed(stripe, charge, row, canonical_dispute=None):
    if type(charge.get("disputed")) is not bool:
        raise ValueError("invalid_usage_dispute_state")
    listing = stripe.stripe_request("GET", "/v1/disputes?" + urlencode({"charge": charge["id"], "limit": 100}))
    if not isinstance(listing.get("data"), list) or type(listing.get("has_more")) is not bool:
        raise ValueError("invalid_usage_dispute_state")
    held = listing["has_more"]
    states = {}
    proofs = listing['data'] + ([canonical_dispute] if canonical_dispute else [])
    for dispute in proofs:
        _common(dispute, row, "dp")
        if dispute.get("charge") != charge["id"] or dispute.get("payment_intent") != charge["payment_intent"]:
            raise ValueError("usage_dispute_payment_mismatch")
        # Durable per-dispute proof keeps a stale empty listing from clearing
        # a newer hold, and a stale open event from reopening a won dispute.
        # warning_closed is a closed inquiry that can no longer escalate to a
        # chargeback, per Stripe's lifecycle documentation. Refunds still apply.
        states[dispute['id']] = 'won' if dispute.get('status') in {'won','warning_closed'} else 'lost' if dispute.get('status') == 'lost' else 'open'
    held = held or any(status != 'won' for status in states.values())
    return bool(held or (charge["disputed"] and not proofs)), states


def _fulfill(checkout_id, *, event_id="", canonical_dispute=None):
    stripe = subscriptions.client()
    checkout_id = _id(checkout_id, "cs")
    checkout = stripe.stripe_request("GET", "/v1/checkout/sessions/" + checkout_id)
    row = _metadata(checkout)
    _common(checkout, row, "cs", checkout_id)
    if row["checkout"] and row["checkout"] != checkout_id:
        raise ValueError("usage_checkout_binding_mismatch")
    if checkout.get("mode") != "payment" or checkout.get("subscription") or checkout.get("client_reference_id") != row["tenant"]:
        raise ValueError("usage_checkout_mode_mismatch")
    if checkout.get("status") != "complete" or checkout.get("payment_status") != "paid":
        if checkout.get("status") in {"open", "expired"} or checkout.get("payment_status") == "unpaid":
            return False
        raise ValueError("usage_checkout_not_paid")
    _integer(checkout.get("amount_subtotal"), row["subtotal_pence"])
    _integer(checkout.get("amount_total"), row["total_pence"])
    details = checkout.get("total_details") or {}
    _integer(details.get("amount_tax"), row["tax_pence"])
    _integer(details.get("amount_discount"), 0)
    _integer(details.get("amount_shipping"), 0)
    if checkout.get("discounts") or not (checkout.get("invoice_creation") or {}).get("enabled"):
        raise ValueError("usage_checkout_terms_mismatch")
    _tax_verified(stripe, row)
    listing = stripe.stripe_request("GET", "/v1/checkout/sessions/" + checkout_id + "/line_items")
    if listing.get("has_more") is not False or not isinstance(listing.get("data"), list) or len(listing["data"]) != 1:
        raise ValueError("usage_checkout_items_mismatch")
    item = listing["data"][0]
    if not isinstance(item, dict):
        raise ValueError("usage_checkout_items_mismatch")
    _integer(item.get("quantity"), 1)
    _integer(item.get("amount_subtotal"), row["subtotal_pence"])
    _integer(item.get("amount_total"), row["total_pence"])
    _integer(item.get("amount_tax"), row["tax_pence"])
    price = item.get("price") or {}
    if item.get("currency") != "gbp" or price.get("currency") != "gbp" or price.get("type") != "one_time" or price.get("recurring") or price.get("tax_behavior") != "exclusive":
        raise ValueError("usage_checkout_items_mismatch")
    _integer(price.get("unit_amount"), row["subtotal_pence"])
    payment_id = _id(checkout.get("payment_intent"), "pi")
    payment = stripe.stripe_request("GET", "/v1/payment_intents/" + payment_id)
    _common(payment, row, "pi", payment_id)
    _metadata(payment, row)
    if payment.get("status") != "succeeded":
        raise ValueError("usage_payment_not_succeeded")
    _integer(payment.get("amount"), row["total_pence"])
    _integer(payment.get("amount_received"), row["total_pence"])
    charge_id = _id(payment.get("latest_charge"), "ch")
    charge = stripe.stripe_request("GET", "/v1/charges/" + charge_id)
    _common(charge, row, "ch", charge_id)
    if charge.get("payment_intent") != payment_id or charge.get("paid") is not True or charge.get("captured") is not True or charge.get("status") != "succeeded":
        raise ValueError("usage_charge_mismatch")
    _integer(charge.get("amount"), row["total_pence"])
    _integer(charge.get("amount_captured"), row["total_pence"])
    refunded = _integer(charge.get("amount_refunded"))
    if refunded > row["total_pence"]:
        raise ValueError("usage_refund_amount_mismatch")
    invoice_id = _id(checkout.get("invoice"), "in")
    invoice = stripe.stripe_request("GET", "/v1/invoices/" + invoice_id)
    _common(invoice, row, "in", invoice_id)
    _metadata(invoice, row)
    if invoice.get("status") != "paid" or invoice.get("subscription") or (invoice.get("parent") or {}).get("subscription_details"):
        raise ValueError("usage_invoice_mismatch")
    _integer(invoice.get("total"), row["total_pence"])
    _integer(invoice.get("amount_paid"), row["total_pence"])
    _integer(invoice.get("amount_remaining"), 0)
    _integer(invoice.get("total_excluding_tax"), row["subtotal_pence"])
    disputed, dispute_states = _disputed(stripe, charge, row, canonical_dispute)
    receipt = (subscriptions._safe_url(invoice.get("hosted_invoice_url"), "invoice.stripe.com")
               or subscriptions._safe_url(charge.get("receipt_url"), "pay.stripe.com") or "")
    # Bind all canonical IDs before money moves. The wallet also uniquely binds
    # the actual PaymentIntent, so two sessions cannot credit it twice.
    with subscriptions.connection(row["tenant"]) as db:
        _schema(db)
        suffix = _write_lock(db)
        current = dict(db.execute("SELECT * FROM usage_checkout_requests WHERE tenant=? AND reference=?" + suffix,
                                  (row["tenant"], row["reference"])).fetchone())
        if any(current[key] and current[key] != value for key, value in (("checkout", checkout_id), ("payment_id", payment_id), ("invoice_id", invoice_id))):
            raise ValueError("usage_payment_binding_mismatch")
        db.execute("UPDATE usage_checkout_requests SET checkout=?,payment_id=?,invoice_id=? WHERE tenant=? AND reference=?",
                   (checkout_id, payment_id, invoice_id, row["tenant"], row["reference"]))
    usage_wallet.apply_payment(row["tenant"], row["reference"], payment_id, row["credit_pence"], row["total_pence"],
                               invoice_id=invoice_id, receipt_url=receipt, refunded_pence=refunded,
                               disputed=disputed, dispute_states=dispute_states, event_id=event_id)
    usage_wallet.reconcile_payment(row["tenant"], payment_id, refunded, disputed=disputed,
                                   dispute_states=dispute_states, event_id=event_id)
    with subscriptions.connection(row["tenant"]) as db:
        db.execute("UPDATE usage_checkout_requests SET status='paid' WHERE tenant=? AND reference=?", (row["tenant"], row["reference"]))
    return True


def handle_usage_event(event):
    """Called only after the shared Stripe webhook signature was verified."""
    event_type = event.get("type")
    obj = event["data"]["object"]
    event_id = event.get("id", "")
    if event_type in _TYPES:
        if not isinstance(obj.get("metadata"), dict) or obj["metadata"].get("kind") != _KIND:
            return False
        if str(event_type).startswith("checkout.session."):
            checkout_id = _id(obj.get("id"), "cs")
            if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
                _fulfill(checkout_id, event_id=event_id)
            else:
                canonical = subscriptions.client().stripe_request("GET", "/v1/checkout/sessions/" + checkout_id)
                row = _metadata(canonical)
                _common(canonical, row, "cs", checkout_id)
                if row["checkout"] and row["checkout"] != checkout_id:
                    raise ValueError("usage_checkout_binding_mismatch")
                if canonical.get("status") == "complete" and canonical.get("payment_status") == "paid":
                    _fulfill(checkout_id, event_id=event_id)
                else:
                    _refresh_checkout({**row, 'checkout':checkout_id})
            return True
        invoice = subscriptions.client().stripe_request("GET", "/v1/invoices/" + _id(obj.get("id"), "in"))
        row = _metadata(invoice)
        if invoice.get('status') != 'paid':
            return True
        if not row["checkout"]:
            raise ValueError("usage_checkout_binding_pending")
        _fulfill(row["checkout"], event_id=event_id)
        return True
    if event_type not in _REVERSALS:
        return False
    stripe = subscriptions.client()
    canonical_dispute = None
    if str(event_type).startswith("charge.dispute."):
        dispute = stripe.stripe_request("GET", "/v1/disputes/" + _id(obj.get("id"), "dp"))
        canonical_dispute = dispute
        charge_id = _id(dispute.get("charge"), "ch")
    elif str(event_type).startswith("refund."):
        refund = stripe.stripe_request("GET", "/v1/refunds/" + _id(obj.get("id"), "re"))
        charge_id = _id(refund.get("charge"), "ch")
    else:
        charge_id = _id(obj.get("id"), "ch")
    charge = stripe.stripe_request("GET", "/v1/charges/" + charge_id)
    payment = stripe.stripe_request("GET", "/v1/payment_intents/" + _id(charge.get("payment_intent"), "pi"))
    if not isinstance(payment.get("metadata"), dict) or payment["metadata"].get("kind") != _KIND:
        return False
    row = _metadata(payment)
    if not row["checkout"]:
        raise ValueError("usage_checkout_binding_pending")
    _fulfill(row["checkout"], event_id=event_id, canonical_dispute=canonical_dispute)
    return True
