"""Private prepaid GBP accounting. Provider callers authorize the tenant first."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from urllib.parse import urlsplit

from service import session_store, usage_currency

NANO_PER_PENNY = 10_000_000
_MAX_PENCE = 1_000_000
_MAX_NANO = _MAX_PENCE * NANO_PER_PENNY
_METADATA_TEXT = {"model", "requested_model", "channel", "purpose", "status", "price_version"}
_METADATA_COUNTS = {"input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens"}


class UsagePaused(RuntimeError):
    """Paid work cannot proceed; existing saved-knowledge fallback remains safe."""


@dataclass(frozen=True)
class Reservation:
    tenant: str
    ref: str
    rate: Decimal
    markup_percent: Decimal


_SQLITE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS usage_wallets (
        tenant TEXT PRIMARY KEY, balance_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK(balance_nano_gbp>=0),
        reserved_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK(reserved_nano_gbp>=0),
        debt_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK(debt_nano_gbp>=0),
        reconciliation_hold INTEGER NOT NULL DEFAULT 0 CHECK(reconciliation_hold IN(0,1)),
        pause_reason TEXT NOT NULL DEFAULT '', updated_utc TEXT NOT NULL,
        CHECK(reserved_nano_gbp<=balance_nano_gbp))""",
    """CREATE TABLE IF NOT EXISTS usage_wallet_payments (
        tenant TEXT NOT NULL, reference TEXT PRIMARY KEY, payment_id TEXT UNIQUE NOT NULL,
        credit_nano_gbp BIGINT NOT NULL CHECK(credit_nano_gbp>0), paid_pence BIGINT NOT NULL CHECK(paid_pence>0),
        refunded_pence BIGINT NOT NULL DEFAULT 0 CHECK(refunded_pence>=0),
        reversed_nano_gbp BIGINT NOT NULL DEFAULT 0 CHECK(reversed_nano_gbp>=0),
        disputed INTEGER NOT NULL DEFAULT 0 CHECK(disputed IN(0,1)),
        dispute_open INTEGER NOT NULL DEFAULT 0 CHECK(dispute_open IN(0,1)),
        dispute_states_json TEXT NOT NULL DEFAULT '{}',
        invoice_id TEXT NOT NULL DEFAULT '', receipt_url TEXT NOT NULL DEFAULT '', created_utc TEXT NOT NULL,
        FOREIGN KEY(tenant) REFERENCES usage_wallets(tenant), CHECK(reversed_nano_gbp<=credit_nano_gbp),
        CHECK(refunded_pence<=paid_pence))""",
    """CREATE TABLE IF NOT EXISTS usage_wallet_reservations (
        tenant TEXT NOT NULL, ref TEXT PRIMARY KEY, amount_nano_gbp BIGINT NOT NULL CHECK(amount_nano_gbp>=0),
        maximum_nano_usd BIGINT NOT NULL CHECK(maximum_nano_usd>=0), fx_rate TEXT NOT NULL,
        fx_date TEXT NOT NULL, markup_percent TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN('pending','unknown','overrun','settled')),
        cost_nano_usd BIGINT, charged_nano_gbp BIGINT, metadata_json TEXT NOT NULL, created_utc TEXT NOT NULL,
        FOREIGN KEY(tenant) REFERENCES usage_wallets(tenant))""",
    """CREATE TABLE IF NOT EXISTS usage_wallet_entries (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL, created_utc TEXT NOT NULL,
        amount_nano_gbp BIGINT NOT NULL, balance_delta_nano_gbp BIGINT NOT NULL,
        debt_delta_nano_gbp BIGINT NOT NULL, reserved_delta_nano_gbp BIGINT NOT NULL,
        payment_ref TEXT NOT NULL DEFAULT '', reservation_ref TEXT NOT NULL DEFAULT '',
        invoice_id TEXT NOT NULL DEFAULT '', receipt_url TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT '',
        idempotency_key TEXT NOT NULL, metadata_json TEXT NOT NULL,
        FOREIGN KEY(tenant) REFERENCES usage_wallets(tenant), UNIQUE(tenant,idempotency_key))""",
    "CREATE INDEX IF NOT EXISTS usage_wallet_payments_tenant ON usage_wallet_payments(tenant,created_utc)",
    "CREATE INDEX IF NOT EXISTS usage_wallet_reservations_tenant ON usage_wallet_reservations(tenant,status)",
    "CREATE INDEX IF NOT EXISTS usage_wallet_entries_tenant ON usage_wallet_entries(tenant,created_utc,id)",
    """CREATE TRIGGER IF NOT EXISTS usage_wallet_entries_no_update BEFORE UPDATE ON usage_wallet_entries
        BEGIN SELECT RAISE(ABORT,'immutable_wallet_ledger'); END""",
    """CREATE TRIGGER IF NOT EXISTS usage_wallet_entries_no_delete BEFORE DELETE ON usage_wallet_entries
        BEGIN SELECT RAISE(ABORT,'immutable_wallet_ledger'); END""",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _pending_cutoff():
    return (datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat()


def _text(value, *, maximum=200, empty=False):
    if (not isinstance(value, str) or len(value)>maximum or (not value and not empty)
            or any(ord(char)<32 or ord(char)==127 for char in value)):
        raise ValueError("invalid_wallet_reference")
    return value


def _amount(value, *, signed=False):
    lower = -_MAX_PENCE if signed else 1
    if type(value) is not int or not lower<=value<=_MAX_PENCE or value==0:
        raise ValueError("invalid_credit_amount")
    return value


def _safe_metadata(metadata):
    result = {}
    if not isinstance(metadata, dict):
        return result
    for name in _METADATA_TEXT:
        value = metadata.get(name)
        if isinstance(value, str) and len(value)<=120 and not any(ord(char)<32 or ord(char)==127 for char in value):
            result[name] = value
    for name in _METADATA_COUNTS:
        value = metadata.get(name)
        if type(value) is int and 0<=value<=1_000_000_000:
            result[name] = value
    audio = metadata.get("audio_seconds")
    if type(audio) in (int, float) and 0<=audio<=86400:
        result["audio_seconds"] = audio
    for name in ("model_rate", "rate_snapshot"):
        value = metadata.get(name)
        if isinstance(value, dict) and len(value)<=12:
            rates = {key: amount for key, amount in value.items()
                     if key in {"input", "cached", "cache_write", "output", "audio_second",
                                "input_nano_usd", "cached_nano_usd", "cache_write_nano_usd", "output_nano_usd",
                                "long_context_threshold", "long_input_multiplier", "long_output_numerator",
                                "long_output_denominator"}
                     and type(amount) is int and 0<=amount<=1_000_000_000}
            if rates:
                result[name] = rates
    return result


def _receipt(value):
    if not value:
        return ""
    try:
        parsed = urlsplit(_text(value, maximum=2000))
        if (parsed.scheme=="https" and parsed.hostname in {"invoice.stripe.com", "pay.stripe.com", "receipt.stripe.com"}
                and not(parsed.username or parsed.password) and parsed.port in {None,443}):
            return value
    except ValueError:
        pass
    raise ValueError("invalid_credit_receipt")


@contextmanager
def _connection(tenant, *, write=False):
    if not isinstance(tenant, str) or not session_store._TENANT_KEY.fullmatch(tenant):
        raise ValueError("invalid_tenant")
    from service.subscriptions import connection
    with connection(tenant) as db:
        if not session_store._using_postgres():
            if write:
                db.execute("BEGIN IMMEDIATE")
            for statement in _SQLITE_SCHEMA:
                db.execute(statement)
        yield db


def _locked_wallet(db, tenant):
    db.execute("INSERT INTO usage_wallets(tenant,updated_utc) VALUES (?,?) ON CONFLICT DO NOTHING", (tenant,_now()))
    suffix = " FOR UPDATE" if session_store._using_postgres() else ""
    return dict(db.execute("SELECT * FROM usage_wallets WHERE tenant=?"+suffix,(tenant,)).fetchone())


def _save(db, wallet):
    db.execute("UPDATE usage_wallets SET balance_nano_gbp=?,reserved_nano_gbp=?,debt_nano_gbp=?,"
               "reconciliation_hold=?,pause_reason=?,updated_utc=? WHERE tenant=?",
               tuple(wallet[key] for key in ("balance_nano_gbp","reserved_nano_gbp","debt_nano_gbp",
                                             "reconciliation_hold","pause_reason"))+(_now(),wallet["tenant"]))


def _entry(db, before, wallet, kind, amount, key, *, metadata=None, payment_ref='', reservation_ref='',
           invoice_id='', receipt_url='', reason='', actor=''):
    db.execute("INSERT INTO usage_wallet_entries (id,tenant,kind,created_utc,amount_nano_gbp,"
               "balance_delta_nano_gbp,debt_delta_nano_gbp,reserved_delta_nano_gbp,payment_ref,reservation_ref,"
               "invoice_id,receipt_url,reason,actor,idempotency_key,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (secrets.token_hex(16),wallet["tenant"],kind,_now(),amount,
                wallet["balance_nano_gbp"]-before["balance_nano_gbp"],
                wallet["debt_nano_gbp"]-before["debt_nano_gbp"],
                wallet["reserved_nano_gbp"]-before["reserved_nano_gbp"],payment_ref,reservation_ref,
                invoice_id,receipt_url,reason,actor,key,json.dumps(metadata or {},sort_keys=True)))


def _repay_debt(wallet):
    available = wallet["balance_nano_gbp"]-wallet["reserved_nano_gbp"]
    repaid = min(available,wallet["debt_nano_gbp"])
    wallet["balance_nano_gbp"] -= repaid
    wallet["debt_nano_gbp"] -= repaid


def _refresh_pause(db,wallet):
    if wallet["pause_reason"]=="insufficient_credit" and wallet["balance_nano_gbp"]>wallet["reserved_nano_gbp"]:
        wallet["pause_reason"] = ''
    elif (wallet["pause_reason"]=="financial_review_required" and not wallet["debt_nano_gbp"]
          and not wallet["reconciliation_hold"]):
        disputed = db.execute("SELECT 1 FROM usage_wallet_payments WHERE tenant=? AND dispute_open=1 LIMIT 1",
                              (wallet["tenant"],)).fetchone()
        unknown = db.execute("SELECT 1 FROM usage_wallet_reservations WHERE tenant=? AND status IN('unknown','overrun') LIMIT 1",
                             (wallet["tenant"],)).fetchone()
        if not disputed and not unknown:
            wallet["pause_reason"] = ''


def _merge_disputes(payment, disputed, incoming):
    """Canonical per-dispute terminal proof survives stale concurrent snapshots."""
    if incoming is None:
        incoming = {}
    if (not isinstance(incoming, dict) or len(incoming)>100
            or any(not isinstance(key,str) or not key.startswith("dp_") or len(key)>128
                   or any(not (char.isascii() and (char.isalnum() or char in "_-")) for char in key)
                   or not isinstance(value,str) or value not in {"open","won","lost"} for key,value in incoming.items())):
        raise ValueError("invalid_dispute_snapshot")
    states = json.loads(payment["dispute_states_json"])
    for key,status in incoming.items():
        previous = states.get(key)
        if previous == "lost" or status == "lost":
            states[key] = "lost"
        elif previous != "won":
            states[key] = status
    # Incomplete provider pagination or a legacy boolean-only hold is not
    # sufficient evidence for restoration. Preserve an explicit review hold.
    if disputed and not any(status in {"open","lost"} for status in incoming.values()):
        states["unresolved"] = "open"
    return (any(status != "won" for status in states.values()),
            any(status == "open" for status in states.values()),json.dumps(states,sort_keys=True))


def _reverse(db, wallet, payment, refunded_pence, disputed, event_id, dispute_states=None):
    if type(refunded_pence) is not int or not 0<=refunded_pence<=payment["paid_pence"] or type(disputed) is not bool:
        raise ValueError("invalid_payment_reversal")
    # Refund totals only grow; per-ID dispute outcomes merge under the same
    # wallet lock so an older false/open snapshot cannot restore or re-hold credit.
    refunded = max(refunded_pence,payment["refunded_pence"])
    disputed,dispute_open,states_json = _merge_disputes(payment,disputed,dispute_states)
    target = payment["credit_nano_gbp"] if disputed else (
        (payment["credit_nano_gbp"]*refunded+payment["paid_pence"]-1)//payment["paid_pence"])
    difference = target-payment["reversed_nano_gbp"]
    before = dict(wallet)
    if difference>0:
        take = min(difference,wallet["balance_nano_gbp"]-wallet["reserved_nano_gbp"])
        wallet["balance_nano_gbp"] -= take
        wallet["debt_nano_gbp"] += difference-take
    elif difference<0:
        wallet["balance_nano_gbp"] -= difference
        _repay_debt(wallet)
    changed = (difference or payment["disputed"]!=int(disputed) or payment["dispute_open"]!=int(dispute_open)
               or payment["refunded_pence"]!=refunded
               or payment["dispute_states_json"]!=states_json)
    if changed:
        db.execute("UPDATE usage_wallet_payments SET refunded_pence=?,reversed_nano_gbp=?,disputed=?,dispute_open=?,dispute_states_json=? WHERE tenant=? AND payment_id=?",
                   (refunded,target,int(disputed),int(dispute_open),states_json,wallet["tenant"],payment["payment_id"]))
        _entry(db,before,wallet,"refund" if difference>=0 else "refund_restored",-difference,
               "reverse:"+payment["payment_id"]+":"+secrets.token_hex(12),payment_ref=payment["reference"],
               invoice_id=payment["invoice_id"],receipt_url=payment["receipt_url"],
               metadata={"refunded_pence":refunded,"disputed":disputed,"event_id":event_id})


def apply_payment(tenant,reference,payment_id,credit_pence,paid_pence,invoice_id='',receipt_url='',metadata=None,
                  *,refunded_pence=0,disputed=False,event_id='',dispute_states=None):
    """Only the canonical paid Stripe verifier may call this server-only function."""
    reference,payment_id = _text(reference),_text(payment_id)
    credit,paid = _amount(credit_pence)*NANO_PER_PENNY,_amount(paid_pence)
    invoice_id,receipt_url,event_id = _text(invoice_id,empty=True),_receipt(receipt_url),_text(event_id,empty=True)
    with _connection(tenant,write=True) as db:
        wallet = _locked_wallet(db,tenant)
        row = db.execute("SELECT * FROM usage_wallet_payments WHERE tenant=? AND (payment_id=? OR reference=?)",
                         (tenant,payment_id,reference)).fetchone()
        if row:
            payment = dict(row)
            if (payment["payment_id"]!=payment_id or payment["reference"]!=reference
                    or payment["credit_nano_gbp"]!=credit or payment["paid_pence"]!=paid):
                raise ValueError("payment_credit_mismatch")
        else:
            db.execute("INSERT INTO usage_wallet_payments (tenant,reference,payment_id,credit_nano_gbp,paid_pence,"
                       "invoice_id,receipt_url,created_utc) VALUES (?,?,?,?,?,?,?,?)",
                       (tenant,reference,payment_id,credit,paid,invoice_id,receipt_url,_now()))
            payment = dict(db.execute("SELECT * FROM usage_wallet_payments WHERE tenant=? AND payment_id=?",
                                      (tenant,payment_id)).fetchone())
            before = dict(wallet)
            wallet["balance_nano_gbp"] += credit
            _repay_debt(wallet)
            _entry(db,before,wallet,"topup",credit,"payment:"+payment_id,payment_ref=reference,
                   invoice_id=invoice_id,receipt_url=receipt_url,metadata={"paid_pence":paid,"credit_pence":credit_pence})
        _reverse(db,wallet,payment,refunded_pence,disputed,event_id,dispute_states)
        _refresh_pause(db,wallet)
        _save(db,wallet)
    return {"ok":True,"credited_pence":credit_pence,"payment_id":payment_id}


def reconcile_payment(tenant,payment_id,refunded_pence,disputed=False,event_id='',*,dispute_states=None):
    payment_id,event_id = _text(payment_id),_text(event_id,empty=True)
    with _connection(tenant,write=True) as db:
        wallet = _locked_wallet(db,tenant)
        row = db.execute("SELECT * FROM usage_wallet_payments WHERE tenant=? AND payment_id=?",(tenant,payment_id)).fetchone()
        if not row:
            raise ValueError("unknown_credit_payment")
        _reverse(db,wallet,dict(row),refunded_pence,disputed,event_id,dispute_states)
        _refresh_pause(db,wallet)
        _save(db,wallet)
    return {"ok":True}


def markup_percent():
    try:
        value = Decimal(os.getenv("V7_USAGE_MARKUP_PERCENT","0"))
        if not value.is_finite() or not 0<=value<=200:
            raise ValueError
        return value
    except (InvalidOperation,ValueError):
        raise UsagePaused("pricing_unavailable") from None


def _charge(nano_usd,rate,markup):
    return int((Decimal(nano_usd)*rate*(Decimal(1)+markup/100)).quantize(Decimal(1),rounding=ROUND_CEILING))


def _expire_pending(db,wallet):
    rows = db.execute("SELECT * FROM usage_wallet_reservations WHERE tenant=? AND status='pending' AND created_utc<?",
                      (wallet["tenant"],_pending_cutoff())).fetchall()
    for row in rows:
        row = dict(row)
        details = json.loads(row["metadata_json"])
        details.update(status="unknown",fx_rate=row["fx_rate"],fx_date=row["fx_date"],markup_percent=row["markup_percent"])
        db.execute("UPDATE usage_wallet_reservations SET status='unknown',metadata_json=? WHERE tenant=? AND ref=?",
                   (json.dumps(details,sort_keys=True),wallet["tenant"],row["ref"]))
        # A crash cannot prove that inference was free. Keep the entire ceiling
        # reserved until verified provider usage settles this exact reference.
        _entry(db,dict(wallet),wallet,"usage_unknown",0,"unknown:"+row["ref"],
               reservation_ref=row["ref"],metadata=details)
    if rows:
        wallet["reconciliation_hold"] = 1
        wallet["pause_reason"] = "financial_review_required"


def reserve_usage(tenant,ceiling_nano_usd,metadata=None):
    rate_data = usage_currency.gbp_rate() if type(ceiling_nano_usd) is int and 0<=ceiling_nano_usd<=_MAX_NANO else None
    rate = None
    try:
        if rate_data and not rate_data.get("stale"):
            candidate = Decimal(str(rate_data["rate"]))
            if candidate.is_finite() and 0<candidate<10:
                rate = candidate
        markup = markup_percent()
    except (InvalidOperation,ValueError,KeyError,TypeError,UsagePaused):
        markup = Decimal(0)
        rate = None
    amount = _charge(ceiling_nano_usd,rate,markup) if rate is not None else None
    reason = ''
    ref = secrets.token_hex(16)
    with _connection(tenant,write=True) as db:
        wallet = _locked_wallet(db,tenant)
        _expire_pending(db,wallet)
        unknown = db.execute("SELECT COUNT(*) count FROM usage_wallet_reservations WHERE tenant=? AND status IN('unknown','overrun')",(tenant,)).fetchone()["count"]
        disputed = db.execute("SELECT COUNT(*) count FROM usage_wallet_payments WHERE tenant=? AND dispute_open=1",(tenant,)).fetchone()["count"]
        if amount is None:
            reason = "pricing_unavailable"
        elif wallet["debt_nano_gbp"] or wallet["reconciliation_hold"] or unknown or disputed:
            reason = "financial_review_required"
        elif amount>wallet["balance_nano_gbp"]-wallet["reserved_nano_gbp"]:
            reason = "insufficient_credit"
        if reason:
            wallet["pause_reason"] = reason
        else:
            before = dict(wallet)
            wallet["reserved_nano_gbp"] += amount
            wallet["pause_reason"] = ''
            db.execute("INSERT INTO usage_wallet_reservations (tenant,ref,amount_nano_gbp,maximum_nano_usd,fx_rate,"
                       "fx_date,markup_percent,status,metadata_json,created_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (tenant,ref,amount,ceiling_nano_usd,str(rate),str(rate_data.get("date",'')),str(markup),
                        "pending",json.dumps(_safe_metadata(metadata),sort_keys=True),_now()))
            _entry(db,before,wallet,"reservation",0,"reserve:"+ref,reservation_ref=ref,metadata=_safe_metadata(metadata))
        _save(db,wallet)
    if reason:
        raise UsagePaused(reason)
    return Reservation(tenant,ref,rate,markup)


def settle_usage(reservation,cost_nano_usd,metadata=None):
    if reservation is None:
        return
    with _connection(reservation.tenant,write=True) as db:
        wallet = _locked_wallet(db,reservation.tenant)
        row = db.execute("SELECT * FROM usage_wallet_reservations WHERE tenant=? AND ref=?",(reservation.tenant,reservation.ref)).fetchone()
        if not row:
            raise ValueError("unknown_usage_reservation")
        row = dict(row)
        if row["status"]=="settled":
            return
        details = {**json.loads(row["metadata_json"]),**_safe_metadata(metadata)}
        rate,markup = Decimal(row["fx_rate"]),Decimal(row["markup_percent"])
        details.update(fx_rate=str(rate),fx_date=row["fx_date"],markup_percent=str(markup))
        valid = type(cost_nano_usd) is int and 0<=cost_nano_usd<=_MAX_NANO
        charged = _charge(cost_nano_usd,rate,markup) if valid else None
        before = dict(wallet)
        if charged is None or charged>row["amount_nano_gbp"]:
            status = "unknown" if charged is None else "overrun"
            wallet["reconciliation_hold"] = 1
            wallet["pause_reason"] = "financial_review_required"
            if valid:
                details.update(provider_cost_nano_usd=cost_nano_usd,provider_cost_usd=cost_nano_usd/1_000_000_000)
            existing = db.execute("SELECT 1 FROM usage_wallet_entries WHERE tenant=? AND idempotency_key=?",
                                  (reservation.tenant,status+":"+reservation.ref)).fetchone()
            if not existing:
                _entry(db,before,wallet,"usage_unknown" if charged is None else "usage_overrun",0,
                       status+":"+reservation.ref,reservation_ref=reservation.ref,metadata=details)
            db.execute("UPDATE usage_wallet_reservations SET status=?,cost_nano_usd=?,charged_nano_gbp=?,metadata_json=? WHERE tenant=? AND ref=?",
                       (status,cost_nano_usd if valid else None,charged,json.dumps(details,sort_keys=True),reservation.tenant,reservation.ref))
        else:
            wallet["reserved_nano_gbp"] -= row["amount_nano_gbp"]
            wallet["balance_nano_gbp"] -= charged
            _repay_debt(wallet)
            details.update(provider_cost_nano_usd=cost_nano_usd,provider_cost_usd=cost_nano_usd/1_000_000_000)
            db.execute("UPDATE usage_wallet_reservations SET status='settled',cost_nano_usd=?,charged_nano_gbp=?,metadata_json=? WHERE tenant=? AND ref=?",
                       (cost_nano_usd,charged,json.dumps(details,sort_keys=True),reservation.tenant,reservation.ref))
            if row["status"] in {"unknown","overrun"}:
                outstanding = db.execute("SELECT COUNT(*) count FROM usage_wallet_reservations WHERE tenant=? AND status IN('unknown','overrun')",(reservation.tenant,)).fetchone()["count"]
                if not outstanding:
                    wallet["reconciliation_hold"] = 0
                    wallet["pause_reason"] = ''
            _entry(db,before,wallet,"usage",-charged,"settle:"+reservation.ref,reservation_ref=reservation.ref,metadata=details)
        _refresh_pause(db,wallet)
        _save(db,wallet)


def adjust(tenant,amount_pence,reason,actor,request_id):
    amount = _amount(amount_pence,signed=True)*NANO_PER_PENNY
    reason,actor,request_id = _text(reason,maximum=500),_text(actor,maximum=254),_text(request_id,maximum=100)
    if len(reason.strip())<5:
        raise ValueError("adjustment_reason_required")
    key = "adjust:"+hashlib.sha256(request_id.encode()).hexdigest()
    with _connection(tenant,write=True) as db:
        wallet = _locked_wallet(db,tenant)
        existing = db.execute("SELECT amount_nano_gbp,reason,actor FROM usage_wallet_entries WHERE tenant=? AND idempotency_key=?",(tenant,key)).fetchone()
        if existing:
            if existing["amount_nano_gbp"]!=amount or existing["reason"]!=reason or existing["actor"]!=actor:
                raise ValueError("adjustment_request_mismatch")
            return {"ok":True,"duplicate":True}
        before = dict(wallet)
        if amount>0:
            wallet["balance_nano_gbp"] += amount
            _repay_debt(wallet)
        else:
            available = wallet["balance_nano_gbp"]-wallet["reserved_nano_gbp"]
            if -amount>available:
                raise ValueError("adjustment_exceeds_available_credit")
            wallet["balance_nano_gbp"] += amount
        _refresh_pause(db,wallet)
        _entry(db,before,wallet,"adjustment",amount,key,reason=reason,actor=actor)
        _save(db,wallet)
    return {"ok":True,"duplicate":False}


def report(tenant,include_costs=True,offset=0,limit=20):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError("invalid_wallet_page")
    with _connection(tenant) as db:
        row = db.execute("SELECT * FROM usage_wallets WHERE tenant=?",(tenant,)).fetchone()
        wallet = dict(row) if row else {"balance_nano_gbp":0,"reserved_nano_gbp":0,"debt_nano_gbp":0,"reconciliation_hold":0,"pause_reason":''}
        unknown = db.execute("SELECT COUNT(*) count FROM usage_wallet_reservations WHERE tenant=? AND "
                             "(status IN('unknown','overrun') OR (status='pending' AND created_utc<?))",
                             (tenant,_pending_cutoff())).fetchone()["count"]
        disputed = db.execute("SELECT COUNT(*) count FROM usage_wallet_payments WHERE tenant=? AND dispute_open=1",(tenant,)).fetchone()["count"]
        available = wallet["balance_nano_gbp"]-wallet["reserved_nano_gbp"]
        paused = bool(available<=0 or wallet["debt_nano_gbp"] or wallet["reconciliation_hold"] or unknown or disputed or wallet["pause_reason"])
        alerts = []
        if wallet["debt_nano_gbp"] or wallet["reconciliation_hold"] or unknown or disputed:
            alerts.append({"code":"financial_review_required","message":"Paid AI is paused pending a credit or usage review. Saved business knowledge remains available."})
        elif wallet["pause_reason"]=="pricing_unavailable":
            alerts.append({"code":"pricing_unavailable","message":"Paid AI is paused because its cost cannot be verified safely."})
        elif available<=0 or wallet["pause_reason"]=="insufficient_credit":
            alerts.append({"code":"insufficient_credit","message":"Paid AI needs available prepaid credit. No automatic charge is made."})
        threshold = 200
        try:
            threshold = int(os.getenv("V7_USAGE_LOW_BALANCE_PENCE","200"))
        except ValueError:
            pass
        if 0<available<=max(0,min(threshold,_MAX_PENCE))*NANO_PER_PENNY:
            alerts.append({"code":"low_credit","message":"The prepaid AI balance is running low."})
        result = {"tenant":tenant,"currency":"gbp","paused":paused,"alerts":alerts,
                  "reconciliation_hold":bool(wallet["reconciliation_hold"]),"unknown_reservations":unknown}
        if not include_costs:
            return result
        for name,value in {"balance":wallet["balance_nano_gbp"],"available":available,
                           "reserved":wallet["reserved_nano_gbp"],"debt":wallet["debt_nano_gbp"]}.items():
            result[name+"_nano_gbp"] = value
            result[name+"_pence"] = value/NANO_PER_PENNY
        spent = int(db.execute("SELECT COALESCE(SUM(charged_nano_gbp),0) spent FROM usage_wallet_reservations WHERE tenant=? AND status='settled'",(tenant,)).fetchone()["spent"])
        result.update(spent_nano_gbp=spent,spent_pence=spent/NANO_PER_PENNY)
        total = db.execute("SELECT COUNT(*) count FROM usage_wallet_entries WHERE tenant=?",(tenant,)).fetchone()["count"]
        rows = db.execute("SELECT * FROM usage_wallet_entries WHERE tenant=? ORDER BY created_utc DESC,id DESC LIMIT ? OFFSET ?",(tenant,limit,offset)).fetchall()
        transactions = []
        for item in rows:
            item = dict(item)
            details = json.loads(item.pop("metadata_json"))
            for field in ("amount","balance_delta","debt_delta","reserved_delta"):
                item[field+"_pence"] = item[field+"_nano_gbp"]/NANO_PER_PENNY
            item.pop("idempotency_key")
            # Privileged actor identity stays in the internal immutable audit
            # record; company billing viewers do not need operator email addresses.
            item.pop("actor")
            item["usage"] = details if item["reservation_ref"] else None
            item["metadata"] = details if not item["reservation_ref"] else None
            transactions.append(item)
        try:
            markup = str(markup_percent())
        except UsagePaused:
            markup = None
        result.update(transactions=transactions,total=total,offset=offset,limit=limit,has_next=offset+limit<total,
                      markup_percent=markup,exchange_rate=usage_currency.cached_gbp_rate())
        return result
