"""Tenant-scoped OpenAI accounting. Stores metadata only, never chat or credentials."""
from __future__ import annotations

import logging
from contextlib import contextmanager, closing
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

from service import analytics_db

logger = logging.getLogger(__name__)
_context: ContextVar[tuple[str, str] | None] = ContextVar("api_usage_context", default=None)
PRICE_VERSION = "2026-09-11"
PRICE_SOURCE = "https://developers.openai.com/api/docs/models/gpt-4o-mini"
# USD nanodollars per token: exact integer arithmetic, standard text inference.
# Explicit snapshots only: older, fine-tuned and unknown models are not guessed.
RATES = {
    "gpt-4o-mini": (150, 75, 600),
    "gpt-4o-mini-2024-07-18": (150, 75, 600),
    "gpt-4o": (2500, 1250, 10000),
    "gpt-4o-2024-08-06": (2500, 1250, 10000),
    "gpt-4o-2024-11-20": (2500, 1250, 10000),
}


@contextmanager
def usage_context(tenant: str, channel: str):
    token = _context.set((tenant, channel))
    try:
        yield
    finally:
        _context.reset(token)


def _schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS api_usage (
        id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, tenant TEXT NOT NULL,
        channel TEXT NOT NULL, purpose TEXT NOT NULL, requested_model TEXT NOT NULL,
        model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER,
        cached_tokens INTEGER, output_tokens INTEGER, cost_nano_usd INTEGER,
        price_version TEXT NOT NULL
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_tenant_ts ON api_usage(tenant, ts_utc)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_ts ON api_usage(ts_utc)")


def _field(value: Any, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _count(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def _record(response, requested_model: str, purpose: str, status: str) -> None:
    context = _context.get()
    if context is None:
        logger.error("API usage not recorded: tenant context missing")
        return
    usage = _field(response, "usage")
    input_tokens = _count(_field(usage, "prompt_tokens"))
    output_tokens = _count(_field(usage, "completion_tokens"))
    cached = _count(_field(_field(usage, "prompt_tokens_details"), "cached_tokens", 0))
    model = _field(response, "model")
    model = model if isinstance(model, str) and model else "unknown"
    cost = None
    rates = RATES.get(model)
    tier = _field(response, "service_tier")
    if (rates and tier in (None, "default") and input_tokens is not None
            and output_tokens is not None and cached is not None and cached <= input_tokens):
        cost = (input_tokens - cached) * rates[0] + cached * rates[1] + output_tokens * rates[2]
    with closing(analytics_db._conn()) as con, con:
        _schema(con)
        con.execute("""INSERT INTO api_usage
            (ts_utc, tenant, channel, purpose, requested_model, model, status,
             input_tokens, cached_tokens, output_tokens, cost_nano_usd, price_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            datetime.now(timezone.utc).isoformat(), context[0].upper(), context[1], purpose, requested_model,
            model, status, input_tokens, cached, output_tokens, cost, PRICE_VERSION,
        ))


def tracked_completion(client, *, purpose: str, **kwargs):
    """Keep existing provider/fallback behavior, including failures and rejected rewrites."""
    response = None
    status = "failed"
    try:
        context = _context.get()
        if context:
            from service.model_settings import selected
            from flask import current_app, has_app_context
            storage = current_app.container.storage if has_app_context() and hasattr(current_app,'container') else None
            model = selected(context[0],storage)
            if model:
                kwargs['model'] = model
        response = client.chat.completions.create(**kwargs)
        status = "completed"
        return response
    finally:
        try:
            _record(response, kwargs["model"], purpose, status)
        except Exception as exc:
            # Accounting failure must not discard a paid reply or reveal its contents.
            logger.error("API usage recording failed (%s)", type(exc).__name__)


def summary(tenant: str | None, days: int) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    where = "ts_utc >= ?" + (" AND tenant = ?" if tenant else "")
    params = [since, tenant.upper()] if tenant else [since]
    totals_sql = """COUNT(*) AS calls,
        COALESCE(SUM(status = 'failed'), 0) AS failed_calls,
        COALESCE(SUM(input_tokens IS NULL OR output_tokens IS NULL), 0) AS missing_usage_calls,
        COALESCE(SUM(cost_nano_usd IS NULL), 0) AS unpriced_calls,
        COALESCE(SUM(input_tokens), 0) AS input_tokens,
        COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
        COALESCE(SUM(output_tokens), 0) AS output_tokens,
        SUM(cost_nano_usd) AS cost_nano_usd"""

    def convert(row):
        data = dict(row)
        cost = data.pop("cost_nano_usd")
        data["estimated_cost_usd"] = (cost / 1_000_000_000 if cost is not None
                                      else 0.0 if data["calls"] == 0 else None)
        data["total_tokens"] = data["input_tokens"] + data["output_tokens"]
        return data

    with closing(analytics_db._conn()) as con, con:
        _schema(con)
        totals = convert(con.execute(f"SELECT {totals_sql} FROM api_usage WHERE {where}", params).fetchone())
        # Grouping by company, model and channel keeps the breakdown compact and bounded.
        rows = con.execute(f"""SELECT tenant, model, requested_model, channel, purpose, {totals_sql}
            FROM api_usage WHERE {where} GROUP BY tenant, model, requested_model, channel, purpose
            ORDER BY COALESCE(SUM(cost_nano_usd), 0) DESC, tenant, model LIMIT 201""", params).fetchall()
        first = con.execute("SELECT MIN(ts_utc) FROM api_usage" + (" WHERE tenant = ?" if tenant else ""),
                            [tenant.upper()] if tenant else []).fetchone()[0]
    return {"totals": totals, "breakdown": [convert(row) for row in rows[:200]],
            "breakdown_truncated": len(rows) > 200, "first_recorded_at": first,
            "since": since, "days": days, "price_version": PRICE_VERSION,
            "price_source": PRICE_SOURCE, "currency": "USD"}
