"""Atomic monthly plan allowances. Usage identities are hashes, never chat text."""
from __future__ import annotations

import hashlib
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from service import session_store

_RESOURCES = {
    "website_conversations": ("website_conversations", "website_paused"),
    "whatsapp_messages": ("whatsapp_messages", "whatsapp_paused"),
}
_NANO_PER_PENNY = 10_000_000


class AllowancePaused(RuntimeError):
    """Provider callers use their existing saved-knowledge fallback."""


@dataclass(frozen=True)
class Reservation:
    tenant: str
    month: str
    ref: str
    rate: Decimal


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _plan(tenant):
    from service.subscriptions import configured_plan
    return configured_plan(tenant)


def _schema(db):
    if session_store._using_postgres():
        return
    db.execute("""CREATE TABLE IF NOT EXISTS billing_plan_usage (
        tenant TEXT NOT NULL, month TEXT NOT NULL,
        website_conversations INTEGER NOT NULL DEFAULT 0,
        whatsapp_messages INTEGER NOT NULL DEFAULT 0,
        ai_used_nano_gbp INTEGER NOT NULL DEFAULT 0,
        ai_reserved_nano_gbp INTEGER NOT NULL DEFAULT 0,
        ai_unknown INTEGER NOT NULL DEFAULT 0,
        website_paused INTEGER NOT NULL DEFAULT 0,
        whatsapp_paused INTEGER NOT NULL DEFAULT 0,
        ai_paused INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(tenant,month))""")
    db.execute("""CREATE TABLE IF NOT EXISTS billing_plan_events (
        tenant TEXT NOT NULL, month TEXT NOT NULL, resource TEXT NOT NULL,
        event_hash TEXT NOT NULL, PRIMARY KEY(tenant,month,resource,event_hash))""")
    db.execute("""CREATE TABLE IF NOT EXISTS billing_plan_reservations (
        tenant TEXT NOT NULL, month TEXT NOT NULL, ref TEXT NOT NULL,
        amount_nano_gbp INTEGER NOT NULL, PRIMARY KEY(tenant,month,ref))""")


@contextmanager
def _connection(tenant, *, write=False):
    # This adapter supplies the same tenant-scoped RLS transaction as billing.
    from service.subscriptions import connection
    with connection(tenant) as db:
        if write and not session_store._using_postgres():
            db.execute("BEGIN IMMEDIATE")
        _schema(db)
        yield db


def _locked_row(db, tenant, month):
    db.execute("INSERT INTO billing_plan_usage (tenant,month) VALUES (?,?) ON CONFLICT DO NOTHING",
               (tenant, month))
    suffix = " FOR UPDATE" if session_store._using_postgres() else ""
    return db.execute("SELECT * FROM billing_plan_usage WHERE tenant=? AND month=?" + suffix,
                      (tenant, month)).fetchone()


def use_resource(tenant: str, resource: str, identity: str) -> bool:
    """Count a signed website session or authenticated inbound WhatsApp message once."""
    if resource not in _RESOURCES or not isinstance(identity, str) or not identity or len(identity) > 4096:
        raise ValueError("invalid_usage_identity")
    plan = _plan(tenant)
    if plan is None:
        return True
    month = _month()
    field, pause = _RESOURCES[resource]
    limit = plan[field]
    digest = hashlib.sha256(f"{tenant}\0{month}\0{resource}\0{identity}".encode()).hexdigest()
    with _connection(tenant, write=True) as db:
        row = _locked_row(db, tenant, month)
        if db.execute("SELECT 1 FROM billing_plan_events WHERE tenant=? AND month=? AND resource=? AND event_hash=?",
                      (tenant, month, resource, digest)).fetchone():
            return True
        if row[field] >= limit:
            db.execute(f"UPDATE billing_plan_usage SET {pause}=1 WHERE tenant=? AND month=?", (tenant, month))
            return False
        db.execute("INSERT INTO billing_plan_events (tenant,month,resource,event_hash) VALUES (?,?,?,?)",
                   (tenant, month, resource, digest))
        db.execute(f"UPDATE billing_plan_usage SET {field}={field}+1,{pause}=0 WHERE tenant=? AND month=?", (tenant, month))
    return True


def _nano_gbp(cost_nano_usd: int, rate: Decimal) -> int:
    return int((Decimal(cost_nano_usd) * rate).quantize(Decimal("1"), rounding=ROUND_CEILING))


def reserve_ai(tenant: str, maximum_nano_usd: int | None) -> Reservation | None:
    """Reserve a conservative request ceiling before any provider side effect."""
    plan = _plan(tenant)
    if plan is None:
        return None
    from service.usage_currency import gbp_rate
    reference = gbp_rate() if type(maximum_nano_usd) is int and maximum_nano_usd >= 0 else None
    rate = None
    try:
        if reference and not reference.get("stale"):
            candidate = Decimal(str(reference["rate"]))
            if candidate.is_finite() and 0 < candidate < 10:
                rate = candidate
    except (InvalidOperation, KeyError, TypeError, ValueError):
        pass
    month, ref = _month(), secrets.token_hex(16)
    denied = False
    with _connection(tenant, write=True) as db:
        row = _locked_row(db, tenant, month)
        amount = _nano_gbp(maximum_nano_usd, rate) if rate is not None else None
        limit = plan["ai_budget_pence"] * _NANO_PER_PENNY
        if (amount is None or row["ai_unknown"]
                or row["ai_used_nano_gbp"] + row["ai_reserved_nano_gbp"] + amount > limit):
            db.execute("UPDATE billing_plan_usage SET ai_paused=1 WHERE tenant=? AND month=?", (tenant, month))
            denied = True
        else:
            db.execute("INSERT INTO billing_plan_reservations (tenant,month,ref,amount_nano_gbp) VALUES (?,?,?,?)",
                       (tenant, month, ref, amount))
            db.execute("UPDATE billing_plan_usage SET ai_reserved_nano_gbp=ai_reserved_nano_gbp+?,ai_paused=0 WHERE tenant=? AND month=?",
                       (amount, tenant, month))
    if denied:
        raise AllowancePaused("ai_allowance_paused")
    return Reservation(tenant, month, ref, rate)


def settle_ai(reservation: Reservation | None, cost_nano_usd: int | None) -> None:
    """Release only known spend; uncertain paid calls retain their full reservation."""
    if reservation is None:
        return
    tenant, month = reservation.tenant, reservation.month
    with _connection(tenant, write=True) as db:
        _locked_row(db, tenant, month)
        row = db.execute("SELECT amount_nano_gbp FROM billing_plan_reservations WHERE tenant=? AND month=? AND ref=?",
                         (tenant, month, reservation.ref)).fetchone()
        if row is None:
            return
        db.execute("DELETE FROM billing_plan_reservations WHERE tenant=? AND month=? AND ref=?",
                   (tenant, month, reservation.ref))
        if type(cost_nano_usd) is not int or cost_nano_usd < 0:
            db.execute("UPDATE billing_plan_usage SET ai_unknown=ai_unknown+1,ai_paused=1 WHERE tenant=? AND month=?",
                       (tenant, month))
        else:
            amount = _nano_gbp(cost_nano_usd, reservation.rate)
            db.execute("UPDATE billing_plan_usage SET ai_reserved_nano_gbp=ai_reserved_nano_gbp-?,ai_used_nano_gbp=ai_used_nano_gbp+? WHERE tenant=? AND month=?",
                       (row["amount_nano_gbp"], amount, tenant, month))
            # Provider metadata outside the known reservation ceiling is never
            # silently treated as free or allowed to repeat.
            if amount > row["amount_nano_gbp"]:
                db.execute("UPDATE billing_plan_usage SET ai_unknown=ai_unknown+1,ai_paused=1 WHERE tenant=? AND month=?", (tenant, month))


def pause_ai(tenant: str) -> None:
    """Persist an admin alert when a paid request cannot be bounded safely."""
    if _plan(tenant) is None:
        return
    month = _month()
    with _connection(tenant, write=True) as db:
        _locked_row(db, tenant, month)
        db.execute("UPDATE billing_plan_usage SET ai_paused=1 WHERE tenant=? AND month=?", (tenant, month))


def report(tenant: str, include_costs=True) -> dict | None:
    plan = _plan(tenant)
    if plan is None:
        return None
    month = _month()
    with _connection(tenant) as db:
        row = db.execute("SELECT * FROM billing_plan_usage WHERE tenant=? AND month=?", (tenant, month)).fetchone()
    row = dict(row) if row is not None else {}
    result = {"month": month, "mode": "pause", "alerts": []}
    for resource, (field, pause) in _RESOURCES.items():
        used, limit = row.get(field, 0), plan[field]
        paused = used >= limit
        result[resource] = {"used": used, "limit": limit, "paused": paused}
        if paused:
            message = ("New website conversations are paused until the next monthly allowance. Existing conversations can continue."
                       if resource == "website_conversations" else
                       "WhatsApp's monthly inbound-message allowance is exhausted. New messages are paused.")
            result["alerts"].append({"resource": resource, "message": message})
    used, reserved = row.get("ai_used_nano_gbp", 0), row.get("ai_reserved_nano_gbp", 0)
    paused = bool(row.get("ai_paused") or row.get("ai_unknown")) or used + reserved >= plan["ai_budget_pence"] * _NANO_PER_PENNY
    result["ai_budget"] = {"limit_pence": plan["ai_budget_pence"], "paused": paused}
    if include_costs:
        result["ai_budget"].update(used_pence=(used + _NANO_PER_PENNY - 1) // _NANO_PER_PENNY,
                                   reserved_pence=(reserved + _NANO_PER_PENNY - 1) // _NANO_PER_PENNY,
                                   unknown_calls=row.get("ai_unknown", 0))
    if paused:
        result["alerts"].append({"resource": "ai_budget", "message": "Paid AI requests are paused because the remaining allowance cannot safely cover the request or its cost is unknown. Saved business knowledge remains available."})
    return result
