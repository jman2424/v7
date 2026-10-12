"""Server-configured, immutable price snapshots for one provider request."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class PriceSnapshot:
    version: str
    rates: Mapping[str, tuple[int, int, int]]
    cache_writes: Mapping[str, int]
    long_context_models: frozenset[str]
    audio_duration: Mapping[str, int]
    audio_tokens: Mapping[str, tuple[int, int]]


def _rate(value):
    if type(value) is not int or not 0 <= value <= 1_000_000_000:
        raise ValueError("invalid_model_pricing")
    return value


def _configured(name):
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    if len(raw) > 65536:
        raise ValueError("invalid_model_pricing")
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        raise ValueError("invalid_model_pricing") from None
    if not isinstance(value, dict) or len(value) > 100:
        raise ValueError("invalid_model_pricing")
    return value


def snapshot() -> PriceSnapshot:
    """Rates are integer USD nanodollars per token (or audio second).

    Environment overrides are operator configuration, never request parameters.
    The exact effective rates are copied before reservation and do not change
    between a provider call and settlement.
    """
    from service import api_usage
    rates = dict(api_usage.RATES)
    writes = dict(api_usage._CACHE_WRITE_RATES)
    long_context = set(api_usage._LONG_CONTEXT_MODELS)
    duration = dict(api_usage._AUDIO_DURATION_RATES)
    audio_tokens = dict(api_usage._AUDIO_TOKEN_RATES)
    for model, value in _configured("V7_MODEL_PRICING_JSON").items():
        if (not isinstance(model, str) or not model or len(model) > 120
                or not isinstance(value, dict)
                or set(value) - {"input", "cached", "output", "cache_write", "long_context"}
                or not {"input", "cached", "output"} <= set(value)):
            raise ValueError("invalid_model_pricing")
        rates[model] = tuple(_rate(value[key]) for key in ("input", "cached", "output"))
        writes[model] = _rate(value.get("cache_write", rates[model][0]))
        if "long_context" in value:
            if type(value["long_context"]) is not bool:
                raise ValueError("invalid_model_pricing")
            if value["long_context"]:
                long_context.add(model)
            else:
                long_context.discard(model)
    for model, value in _configured("V7_AUDIO_PRICING_JSON").items():
        if (not isinstance(model, str) or not model or len(model) > 120
                or not isinstance(value, dict) or not value
                or set(value) - {"second", "input", "output"}
                or ("input" in value) != ("output" in value)):
            raise ValueError("invalid_model_pricing")
        if "second" in value:
            duration[model] = _rate(value["second"])
        if "input" in value:
            audio_tokens[model] = (_rate(value["input"]), _rate(value["output"]))
    encoded = json.dumps({"rates": rates, "writes": writes, "long_context": sorted(long_context),
                          "audio_duration": duration, "audio_tokens": audio_tokens}, sort_keys=True)
    version = api_usage.PRICE_VERSION + ":" + hashlib.sha256(encoded.encode()).hexdigest()[:16]
    return PriceSnapshot(version, MappingProxyType(rates), MappingProxyType(writes),
                         frozenset(long_context), MappingProxyType(duration), MappingProxyType(audio_tokens))
