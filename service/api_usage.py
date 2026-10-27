"""Tenant-scoped OpenAI accounting. Stores metadata only, never chat or credentials."""
from __future__ import annotations

import logging
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from contextlib import contextmanager, closing
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any
from openai import APIStatusError

from service import analytics_db
from service import session_store

logger = logging.getLogger(__name__)
_context: ContextVar[tuple[str, str, str] | None] = ContextVar("api_usage_context", default=None)
_paused_for_turn: ContextVar[bool] = ContextVar("ai_paused_for_turn", default=False)


def pause_ai_for_turn():
    if _context.get() is not None:
        _paused_for_turn.set(True)
PRICE_VERSION = "2026-09-23"
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing"
AUDIO_PRICE_VERSION = "2026-09-25"
# Estimated USD nanodollars per second for duration-billed file transcription.
_AUDIO_DURATION_RATES = {
    "gpt-transcribe": 75_000,
    "gpt-4o-transcribe": 100_000,
    "gpt-4o-mini-transcribe": 50_000,
}
# USD nanodollars per billed token for token-billed transcription responses.
_AUDIO_TOKEN_RATES = {
    "gpt-4o-transcribe": (2_500, 10_000),
    "gpt-4o-mini-transcribe": (1_250, 5_000),
}
# USD nanodollars per token: exact integer arithmetic, standard text inference.
# Explicit snapshots only: older, fine-tuned and unknown models are not guessed.
RATES = {
    "gpt-4o-mini": (150, 75, 600),
    "gpt-4o-mini-2024-07-18": (150, 75, 600),
    "gpt-4o": (2500, 1250, 10000),
    "gpt-4o-2024-08-06": (2500, 1250, 10000),
    "gpt-4o-2024-11-20": (2500, 1250, 10000),
    "gpt-4.1-mini": (400, 100, 1600),
    "gpt-4.1-mini-2025-04-14": (400, 100, 1600),
    "gpt-4.1": (2000, 500, 8000),
    "gpt-4.1-2025-04-14": (2000, 500, 8000),
    "gpt-5.6-luna": (200, 20, 1200),
    "gpt-5.6-terra": (2000, 200, 12000),
    "gpt-5.6-sol": (4000, 400, 20000),
    "gpt-5.6": (4000, 400, 20000),
    "gpt-6-luna": (100, 10, 500),
    "gpt-6-sol": (2000, 200, 10000),
    "gpt-6-astra": (10000, 1000, 50000),
}
_CACHE_WRITE_RATES = {
    model: rates[0] * 5 // 4 for model, rates in RATES.items()
    if model == "gpt-5.6" or model.startswith(("gpt-5.6-", "gpt-6-"))
}
_LONG_CONTEXT_MODELS = set(_CACHE_WRITE_RATES)


@contextmanager
def usage_context(tenant: str, channel: str, mode: str = "unknown"):
    # Callers supply the server-authorized tenant: management assignment,
    # signed widget session, or verified channel recipient. Never accept a
    # provider billing exemption or tenant identity from conversation text.
    if (not isinstance(tenant, str) or not session_store._TENANT_KEY.fullmatch(tenant)
            or not isinstance(channel, str) or not channel or len(channel) > 64):
        from service.plan_usage import AllowancePaused
        raise AllowancePaused("invalid_usage_context")
    mode = mode.lower() if isinstance(mode, str) else "unknown"
    token = _context.set((tenant, channel, mode if mode in {"v5", "v6", "v7"} else "unknown"))
    paused_token = _paused_for_turn.set(False)
    try:
        yield
    finally:
        _paused_for_turn.reset(paused_token)
        _context.reset(token)


def _schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS api_usage (
        id INTEGER PRIMARY KEY, ts_utc TEXT NOT NULL, tenant TEXT NOT NULL,
        channel TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'unknown',
        purpose TEXT NOT NULL, requested_model TEXT NOT NULL,
        model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER,
        cached_tokens INTEGER, cache_write_tokens INTEGER,
        output_tokens INTEGER, audio_seconds REAL, cost_nano_usd INTEGER,
        price_version TEXT NOT NULL
    )""")
    columns = {row["name"] for row in con.execute("PRAGMA table_info(api_usage)")}
    if "mode" not in columns:
        con.execute("ALTER TABLE api_usage ADD COLUMN mode TEXT NOT NULL DEFAULT 'unknown'")
    if "cache_write_tokens" not in columns:
        con.execute("ALTER TABLE api_usage ADD COLUMN cache_write_tokens INTEGER")
    if "audio_seconds" not in columns:
        con.execute("ALTER TABLE api_usage ADD COLUMN audio_seconds REAL")
    con.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_tenant_ts ON api_usage(tenant, ts_utc)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_ts ON api_usage(ts_utc)")


def _field(value: Any, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _count(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def rejected_before_inference(error) -> bool:
    """Only explicit provider authentication/quota/model rejections prove no work.

    Generic failures, timeouts and server errors remain financially uncertain.
    Error text is deliberately neither inspected nor stored.
    """
    if not isinstance(error, APIStatusError):
        return False
    body = _field(error, "body")
    body = _field(body, "error", body)
    code = _field(body, "code") or _field(body, "type")
    return (code == "invalid_api_key" and error.status_code == 401
            or code == "insufficient_quota" and error.status_code == 429
            or code == "model_not_found" and error.status_code in {403, 404})


def rejected_usage(model):
    return {"model": model, "service_tier": "default", "usage": {"prompt_tokens": 0,
        "completion_tokens": 0, "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}}


_USAGE_COLUMNS = (
    "ts_utc", "tenant", "channel", "mode", "purpose", "requested_model", "model", "status",
    "input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens",
    "audio_seconds", "cost_nano_usd", "price_version",
)


def _write_usage(values: tuple) -> None:
    if session_store._using_postgres():
        with session_store.postgres_connection(values[1]) as con:
            con.execute(
                "INSERT INTO v7_private.api_usage (" + ", ".join(_USAGE_COLUMNS) + ") VALUES (" +
                ", ".join(["%s"] * len(values)) + ")", values,
            )
        return
    with closing(analytics_db._conn()) as con, con:
        _schema(con)
        con.execute(
            "INSERT INTO api_usage (" + ", ".join(_USAGE_COLUMNS) + ") VALUES (" +
            ", ".join(["?"] * len(values)) + ")", values,
        )


def rate_metadata(pricing, model):
    rates = pricing.rates.get(model)
    if rates is None:
        return {}
    long_context = model in pricing.long_context_models
    return {"input": rates[0], "cached": rates[1], "output": rates[2],
            "cache_write": pricing.cache_writes.get(model, rates[0]),
            "long_context_threshold": 272000 if long_context else 0,
            "long_input_multiplier": 2 if long_context else 1,
            "long_output_numerator": 3 if long_context else 1,
            "long_output_denominator": 2 if long_context else 1}


def completion_usage(response, requested_model: str, purpose: str, status: str, *, pricing=None) -> dict:
    """Compute financial metadata independently of the analytics write."""
    from service.usage_pricing import snapshot
    pricing = pricing or snapshot()
    usage = _field(response, "usage")
    input_tokens = _count(_field(usage, "prompt_tokens"))
    output_tokens = _count(_field(usage, "completion_tokens"))
    input_details = _field(usage, "prompt_tokens_details")
    cached = _count(_field(input_details, "cached_tokens", 0))
    cache_writes = _count(_field(input_details, "cache_write_tokens", 0))
    model = _field(response, "model")
    model = model if isinstance(model, str) and model else "unknown"
    cost = None
    rates = pricing.rates.get(model)
    tier = _field(response, "service_tier")
    if (rates and tier in (None, "default") and input_tokens is not None
            and output_tokens is not None and cached is not None and cache_writes is not None
            and cached + cache_writes <= input_tokens):
        ordinary_input = input_tokens - cached - cache_writes
        input_cost = (ordinary_input * rates[0] + cached * rates[1]
                      + cache_writes * pricing.cache_writes.get(model, rates[0]))
        output_cost = output_tokens * rates[2]
        if model in pricing.long_context_models and input_tokens > 272_000:
            input_cost *= 2
            output_cost = (output_cost * 3 + 1) // 2
        cost = input_cost + output_cost
    return {"model": model, "requested_model": requested_model, "purpose": purpose, "status": status,
            "input_tokens": input_tokens, "cached_tokens": cached, "cache_write_tokens": cache_writes,
            "output_tokens": output_tokens, "audio_seconds": None, "cost_nano_usd": cost,
            "price_version": pricing.version,
            "rate_snapshot": rate_metadata(pricing, model)}


def _write_details(details):
    context = _context.get()
    if context is None:
        raise ValueError("missing_usage_context")
    _write_usage((datetime.now(timezone.utc).isoformat(), analytics_db._norm_tenant(context[0]),
                  context[1], context[2], *(details[key] for key in (
                      "purpose", "requested_model", "model", "status", "input_tokens", "cached_tokens",
                      "cache_write_tokens", "output_tokens", "audio_seconds", "cost_nano_usd", "price_version"))))


def _record(response, requested_model: str, purpose: str, status: str, *, pricing=None) -> int | None:
    details = completion_usage(response, requested_model, purpose, status, pricing=pricing)
    _write_details(details)
    return details["cost_nano_usd"]


def transcription_usage(response, requested_model: str, status: str, *, pricing=None) -> dict:
    """Store provider usage for one transcript without storing audio or text."""
    from service.usage_pricing import snapshot
    pricing = pricing or snapshot()
    usage = _field(response, "usage")
    usage_type = _field(usage, "type")
    input_tokens = output_tokens = audio_seconds = cost = None
    if usage_type == "duration":
        try:
            seconds = Decimal(str(_field(usage, "seconds")))
            if seconds.is_finite() and 0 <= seconds <= 3600:
                audio_seconds = float(seconds)
                rate = pricing.audio_duration.get(requested_model)
                if rate is not None:
                    cost = int((seconds * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, TypeError, ValueError):
            pass
    elif usage_type == "tokens":
        input_tokens = _count(_field(usage, "input_tokens"))
        output_tokens = _count(_field(usage, "output_tokens"))
        rate = pricing.audio_tokens.get(requested_model)
        if rate and input_tokens is not None and output_tokens is not None:
            cost = input_tokens * rate[0] + output_tokens * rate[1]
    rate_snapshot = ({"audio_second": pricing.audio_duration[requested_model]}
                     if usage_type == "duration" and requested_model in pricing.audio_duration
                     else {"input": rate[0], "output": rate[1]} if usage_type == "tokens" and rate else {})
    return {"purpose": "transcription", "requested_model": requested_model, "model": requested_model,
            "status": status, "input_tokens": input_tokens, "cached_tokens": None,
            "cache_write_tokens": None, "output_tokens": output_tokens, "audio_seconds": audio_seconds,
            "cost_nano_usd": cost, "price_version": pricing.version, "rate_snapshot": rate_snapshot}


def record_transcription(response, requested_model: str, status: str, *, pricing=None) -> int | None:
    details = transcription_usage(response, requested_model, status, pricing=pricing)
    _write_details(details)
    return details["cost_nano_usd"]


def completion_ceiling(kwargs: dict, *, pricing=None) -> int | None:
    """Conservative standard-text ceiling without storing or tokenizing prompts."""
    model = kwargs.get("model")
    from service.usage_pricing import snapshot
    pricing = pricing or snapshot()
    rates = pricing.rates.get(model)
    output_limit = kwargs.get("max_tokens")
    if (rates is None or kwargs.get("service_tier") not in (None, "default")
            or type(output_limit) is not int or not 0 < output_limit <= 4096
            or kwargs.get("stream") not in (None, False)
            or type(kwargs.get("n", 1)) is not int or kwargs.get("n", 1) != 1):
        return None
    messages = kwargs.get("messages", [])
    if not isinstance(messages, list):
        return None
    # Images/audio have separate pricing and cannot enter the text budget gate.
    for message in messages:
        content = _field(message, "content")
        if content is not None and not isinstance(content, str):
            return None
    try:
        encoded = json.dumps({key: kwargs[key] for key in ("messages", "tools", "response_format") if key in kwargs},
                             ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return None
    input_limit = len(encoded) + 256 * len(messages) + 2048
    input_rate = max(rates[0], rates[1], pricing.cache_writes.get(model, rates[0]))
    input_cost, output_cost = input_limit * input_rate, output_limit * rates[2]
    if model in pricing.long_context_models and input_limit > 272_000:
        input_cost *= 2
        output_cost = (output_cost * 3 + 1) // 2
    return input_cost + output_cost


def tracked_completion(client, *, purpose: str, **kwargs):
    """Keep existing provider/fallback behavior, including failures and rejected rewrites."""
    response = None
    status = "failed"
    context = _context.get()
    from service.plan_usage import AllowancePaused
    if _paused_for_turn.get():
        raise AllowancePaused("saved_knowledge_only_for_turn")
    if context is None:
        raise AllowancePaused("missing_usage_context")
    configuration = None
    if context:
        from service.model_settings import document
        from flask import current_app, has_app_context
        storage = current_app.container.storage if has_app_context() and hasattr(current_app,'container') else None
        from retrieval.storage import Storage
        configuration = document(storage or Storage(context[0]), context[0])
    from service.model_settings import completion_options
    from service.openai_completion import create
    from service import usage_wallet, subscriptions
    from service.usage_pricing import snapshot
    kwargs = completion_options(kwargs, purpose=purpose, configuration=configuration)
    from service.chat_diagnostics import provider_timeout, provider_started, emit
    import time
    kwargs['timeout'] = provider_timeout(kwargs['timeout'])
    internal = subscriptions.internal_business(context[0])
    try:
        pricing = snapshot()
    except ValueError:
        emit('provider_skipped', outcome='pricing_unavailable')
        if not internal:
            try:
                usage_wallet.reserve_usage(context[0], None,
                    {"requested_model": kwargs["model"], "purpose": purpose, "channel": context[1]})
            except usage_wallet.UsagePaused:
                pass  # The wallet persists its pricing-unavailable notification.
        raise AllowancePaused("pricing_unavailable") from None
    try:
        reservation = None if internal else usage_wallet.reserve_usage(
            context[0], completion_ceiling(kwargs, pricing=pricing),
            {"requested_model": kwargs["model"], "purpose": purpose, "channel": context[1],
             "status": "pending", "price_version": pricing.version,
             "rate_snapshot": rate_metadata(pricing, kwargs["model"])})
    except (usage_wallet.UsagePaused, ValueError):
        emit('provider_skipped', outcome='ai_credit_paused')
        raise AllowancePaused("ai_credit_paused") from None
    provider_start = time.monotonic()
    try:
        try:
            kwargs['timeout'] = provider_timeout(kwargs['timeout'])
        except AllowancePaused:
            response = rejected_usage(kwargs['model'])  # Known local skip: no provider work took place.
            raise
        provider_started()
        emit('provider_started', purpose=purpose, model=kwargs['model'], timeout_seconds=kwargs['timeout'])
        response = create(client, kwargs)
        status = "completed"
        return response
    except APIStatusError as exc:
        emit('provider_failed', purpose=purpose, error_type=type(exc).__name__, status_code=exc.status_code)
        if rejected_before_inference(exc):
            response = rejected_usage(kwargs["model"])
        raise
    except Exception as exc:
        emit('provider_failed', purpose=purpose, error_type=type(exc).__name__)
        raise
    finally:
        details = completion_usage(response, kwargs["model"], purpose, status, pricing=pricing)
        emit('provider_finished', purpose=purpose, model=kwargs['model'], outcome=status,
             elapsed_ms=round((time.monotonic()-provider_start)*1000, 2),
             input_tokens=details.get('input_tokens'), output_tokens=details.get('output_tokens'),
             cached_tokens=details.get('cached_tokens'))
        details["channel"] = context[1]
        try:
            _record(response, kwargs["model"], purpose, status, pricing=pricing)
        except Exception as exc:
            # Accounting failure must not discard a paid reply or reveal its contents.
            logger.error("API usage recording failed (%s)", type(exc).__name__)
        try:
            usage_wallet.settle_usage(reservation, details["cost_nano_usd"], details)
        except Exception as exc:
            # An unsettled reservation stays held. Never discard a paid reply.
            logger.error("Prepaid usage settlement failed (%s)", type(exc).__name__)


def summary(tenant: str | None, days: int) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if session_store._using_postgres():
        return _postgres_summary(tenant, days, since)
    where = "ts_utc >= ?" + (" AND tenant = ?" if tenant else "")
    params = [since, tenant.upper()] if tenant else [since]
    totals_sql = """COUNT(*) AS calls,
        COALESCE(SUM(status = 'failed'), 0) AS failed_calls,
        COALESCE(SUM((input_tokens IS NULL OR output_tokens IS NULL)
                     AND audio_seconds IS NULL), 0) AS missing_usage_calls,
        COALESCE(SUM(cost_nano_usd IS NULL), 0) AS unpriced_calls,
        COALESCE(SUM(input_tokens), 0) AS input_tokens,
        COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
        COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
        COALESCE(SUM(output_tokens), 0) AS output_tokens,
        COALESCE(SUM(audio_seconds), 0) AS audio_seconds,
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
        mode_rows = con.execute(f"""SELECT mode, {totals_sql} FROM api_usage WHERE {where}
            GROUP BY mode ORDER BY mode""", params).fetchall()
        # Grouping by company, mode, model and channel keeps the breakdown compact and bounded.
        rows = con.execute(f"""SELECT tenant, mode, model, requested_model, channel, purpose, {totals_sql}
            FROM api_usage WHERE {where} GROUP BY tenant, mode, model, requested_model, channel, purpose
            ORDER BY COALESCE(SUM(cost_nano_usd), 0) DESC, tenant, mode, model LIMIT 201""", params).fetchall()
        first = con.execute("SELECT MIN(ts_utc) FROM api_usage" + (" WHERE tenant = ?" if tenant else ""),
                            [tenant.upper()] if tenant else []).fetchone()[0]
    return {"totals": totals, "mode_totals": [convert(row) for row in mode_rows],
            "breakdown": [convert(row) for row in rows[:200]],
            "breakdown_truncated": len(rows) > 200, "first_recorded_at": first,
            "since": since, "days": days, "price_version": PRICE_VERSION,
            "price_source": PRICE_SOURCE, "currency": "USD"}


def _postgres_summary(tenant: str | None, days: int, since: str) -> dict:
    if tenant is None:
        from flask import current_app
        # tenant_keys revalidates the platform session and invokes the bounded
        # inventory function. Every usage read still uses one tenant's RLS scope.
        keys = current_app.container.storage.tenant_keys()
    else:
        keys = [tenant]
    totals_sql = """COUNT(*) AS calls,
        COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),0) AS failed_calls,
        COALESCE(SUM(CASE WHEN (input_tokens IS NULL OR output_tokens IS NULL)
                     AND audio_seconds IS NULL THEN 1 ELSE 0 END),0) AS missing_usage_calls,
        COALESCE(SUM(CASE WHEN cost_nano_usd IS NULL THEN 1 ELSE 0 END),0) AS unpriced_calls,
        COALESCE(SUM(input_tokens),0) AS input_tokens,
        COALESCE(SUM(cached_tokens),0) AS cached_tokens,
        COALESCE(SUM(cache_write_tokens),0) AS cache_write_tokens,
        COALESCE(SUM(output_tokens),0) AS output_tokens,
        COALESCE(SUM(audio_seconds),0) AS audio_seconds,
        SUM(cost_nano_usd) AS cost_nano_usd"""
    aggregate_fields = ('calls', 'failed_calls', 'missing_usage_calls', 'unpriced_calls',
                        'input_tokens', 'cached_tokens', 'cache_write_tokens', 'output_tokens', 'audio_seconds')
    def empty():
        return {**dict.fromkeys(aggregate_fields, 0), 'cost_nano_usd': None}
    def accumulate(target, source):
        for field in aggregate_fields:
            target[field] += float(source[field]) if field == 'audio_seconds' else int(source[field])
        if source['cost_nano_usd'] is not None:
            target['cost_nano_usd'] = (target['cost_nano_usd'] or 0) + int(source['cost_nano_usd'])
    def convert(row):
        data = dict(row)
        cost = data.pop('cost_nano_usd')
        for field in aggregate_fields:
            data[field] = float(data[field]) if field == 'audio_seconds' else int(data[field])
        data['estimated_cost_usd'] = (int(cost) / 1_000_000_000 if cost is not None
                                      else 0.0 if data['calls'] == 0 else None)
        data['total_tokens'] = data['input_tokens'] + data['output_tokens']
        return data
    totals, modes, breakdown, first = empty(), {}, [], None
    for key in keys:
        with session_store.postgres_connection(key, repeatable_read=True) as con:
            values = (since, key)
            where = 'ts_utc >= %s AND tenant = %s'
            aggregate = analytics_db._pg_rows(con,
                f'SELECT {totals_sql} FROM v7_private.api_usage WHERE {where}', values)[0]
            accumulate(totals, aggregate)
            for row in analytics_db._pg_rows(con,
                    f'SELECT mode, {totals_sql} FROM v7_private.api_usage WHERE {where} GROUP BY mode', values):
                mode = modes.setdefault(row['mode'], {**empty(), 'mode': row['mode']})
                accumulate(mode, row)
            breakdown.extend(analytics_db._pg_rows(con, f'''SELECT tenant, mode, model, requested_model,
                channel, purpose, {totals_sql} FROM v7_private.api_usage WHERE {where}
                GROUP BY tenant, mode, model, requested_model, channel, purpose
                ORDER BY COALESCE(SUM(cost_nano_usd),0) DESC, tenant, mode, model LIMIT 201''', values))
            recorded = con.execute('SELECT MIN(ts_utc) FROM v7_private.api_usage WHERE tenant=%s', (key,)).fetchone()[0]
            if recorded is not None and (first is None or recorded < first):
                first = recorded
    breakdown.sort(key=lambda row: (-(row['cost_nano_usd'] or 0), row['tenant'], row['mode'], row['model']))
    return {'totals': convert(totals), 'mode_totals': [convert(modes[key]) for key in sorted(modes)],
            'breakdown': [convert(row) for row in breakdown[:200]],
            'breakdown_truncated': len(breakdown) > 200, 'first_recorded_at': first,
            'since': since, 'days': days, 'price_version': PRICE_VERSION,
            'price_source': PRICE_SOURCE, 'currency': 'USD'}
