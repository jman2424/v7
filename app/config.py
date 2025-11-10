"""
Configuration loader.

- Reads env vars (.env supported by deploy)
- Provides strongly-typed Settings
- Holds feature flags & rate limit knobs
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional


def _get(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing required env: {name}")
    return v


@dataclass(frozen=True)
class Settings:
    MODE: str                    # V5 | V6 | V7
    BUSINESS_KEY: str            # tenant key e.g. "EXAMPLE"
    SECRET_KEY: str

    # External tokens/creds
    WHATSAPP_VERIFY_TOKEN: str
    WHATSAPP_APP_SECRET: str
    SHEETS_SERVICE_JSON: str | None  # path or JSON string

    # Rate limiting
    RATE_LIMIT_PER_MIN: int
    RATE_LIMIT_BURST: int

    # Feature flags (global defaults; per-tenant overrides via business/overrides.json)
    FF_REWRITER_ENABLED: bool
    FF_TOOL_USE_ENABLED: bool
    FF_ANALYTICS_TO_SHEETS: bool

    # Server
    BASE_URL: str
    HEALTH_PATH: str


def _to_bool(s: str | None, default: bool = False) -> bool:
    if s is None:
        return default
    return s.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(override: dict | None = None) -> Settings:
    o = override or {}
    return Settings(
        MODE=o.get("MODE", _get("MODE", "V6")),
        BUSINESS_KEY=o.get("BUSINESS_KEY", _get("BUSINESS_KEY", "EXAMPLE")),
        SECRET_KEY=o.get("SECRET_KEY", _get("SECRET_KEY", "change-me")),

        WHATSAPP_VERIFY_TOKEN=o.get("WHATSAPP_VERIFY_TOKEN", _get("WHATSAPP_VERIFY_TOKEN", "dev")),
        WHATSAPP_APP_SECRET=o.get("WHATSAPP_APP_SECRET", _get("WHATSAPP_APP_SECRET", "dev")),
        SHEETS_SERVICE_JSON=o.get("SHEETS_SERVICE_JSON", os.environ.get("SHEETS_SERVICE_JSON")),

        RATE_LIMIT_PER_MIN=int(o.get("RATE_LIMIT_PER_MIN", os.environ.get("RATE_LIMIT_PER_MIN", 120))),
        RATE_LIMIT_BURST=int(o.get("RATE_LIMIT_BURST", os.environ.get("RATE_LIMIT_BURST", 60))),

        FF_REWRITER_ENABLED=_to_bool(o.get("FF_REWRITER_ENABLED", os.environ.get("FF_REWRITER_ENABLED")), True),
        FF_TOOL_USE_ENABLED=_to_bool(o.get("FF_TOOL_USE_ENABLED", os.environ.get("FF_TOOL_USE_ENABLED")), False),
        FF_ANALYTICS_TO_SHEETS=_to_bool(o.get("FF_ANALYTICS_TO_SHEETS", os.environ.get("FF_ANALYTICS_TO_SHEETS")), False),

        BASE_URL=o.get("BASE_URL", os.environ.get("BASE_URL", "http://localhost:10000")),
        HEALTH_PATH=o.get("HEALTH_PATH", os.environ.get("HEALTH_PATH", "/health")),
    )
