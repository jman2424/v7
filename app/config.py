"""
Configuration loader.

- Reads env vars (.env supported by deploy)
- Provides strongly-typed Settings
- Holds feature flags & rate limit knobs
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import Dict, Optional


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
    WHATSAPP_TOKEN: str
    WHATSAPP_PHONE_ID: str
    WHATSAPP_API_URL: str
    WHATSAPP_TENANT_MAP: Dict[str, str]
    TWILIO_AUTH_TOKEN: str
    SHEETS_SERVICE_JSON: str | None  # path or JSON string

    # Rate limiting
    RATE_LIMIT_PER_MIN: int
    RATE_LIMIT_BURST: int

    # Feature flags (global defaults; per-tenant overrides via business/overrides.json)
    FF_REWRITER_ENABLED: bool
    FF_TOOL_USE_ENABLED: bool
    FF_ANALYTICS_TO_SHEETS: bool

    # Server
    ENVIRONMENT: str
    BASE_URL: str
    HEALTH_PATH: str


def _to_bool(s: str | None, default: bool = False) -> bool:
    if s is None:
        return default
    return s.strip().lower() in {"1", "true", "yes", "on"}


def _whatsapp_tenant_map(value: object) -> Dict[str, str]:
    """Parse the server-only inbound business number to tenant mapping."""
    raw = str(value or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("WHATSAPP_TENANT_MAP_JSON must be a JSON object") from exc
    if not isinstance(data, dict):
        raise RuntimeError("WHATSAPP_TENANT_MAP_JSON must be a JSON object")

    mapping: Dict[str, str] = {}
    for raw_number, raw_tenant in data.items():
        number = str(raw_number or "").strip().removeprefix("whatsapp:").lstrip("+")
        tenant = str(raw_tenant or "").strip()
        if not number or not tenant:
            raise RuntimeError("WHATSAPP_TENANT_MAP_JSON contains an empty mapping")
        mapping[number] = tenant
    return mapping


def load_settings(override: dict | None = None) -> Settings:
    o = override or {}
    secret_key = o.get("SECRET_KEY", _get("SECRET_KEY", "change-me"))
    environment = str(o.get("ENVIRONMENT", os.environ.get("ENVIRONMENT", "development"))).strip().lower()
    if environment in {"production", "prod"} and secret_key in {"", "change-me", "change_me"}:
        raise RuntimeError("SECRET_KEY must be set to a strong value in production")

    return Settings(
        MODE=o.get("MODE", _get("MODE", "V6")),
        BUSINESS_KEY=o.get("BUSINESS_KEY", _get("BUSINESS_KEY", "EXAMPLE")),
        SECRET_KEY=secret_key,

        WHATSAPP_VERIFY_TOKEN=o.get("WHATSAPP_VERIFY_TOKEN", _get("WHATSAPP_VERIFY_TOKEN", "dev")),
        WHATSAPP_APP_SECRET=o.get("WHATSAPP_APP_SECRET", _get("WHATSAPP_APP_SECRET", "dev")),
        WHATSAPP_TOKEN=o.get("WHATSAPP_TOKEN", _get("WHATSAPP_TOKEN", "")),
        WHATSAPP_PHONE_ID=o.get("WHATSAPP_PHONE_ID", _get("WHATSAPP_PHONE_ID", "")),
        WHATSAPP_API_URL=o.get("WHATSAPP_API_URL", _get("WHATSAPP_API_URL", "https://graph.facebook.com/v21.0")),
        WHATSAPP_TENANT_MAP=_whatsapp_tenant_map(
            o.get("WHATSAPP_TENANT_MAP_JSON", _get("WHATSAPP_TENANT_MAP_JSON", ""))
        ),
        TWILIO_AUTH_TOKEN=o.get("TWILIO_AUTH_TOKEN", _get("TWILIO_AUTH_TOKEN", "")),
        SHEETS_SERVICE_JSON=o.get("SHEETS_SERVICE_JSON", os.environ.get("SHEETS_SERVICE_JSON")),

        RATE_LIMIT_PER_MIN=int(o.get("RATE_LIMIT_PER_MIN", os.environ.get("RATE_LIMIT_PER_MIN", 120))),
        RATE_LIMIT_BURST=int(o.get("RATE_LIMIT_BURST", os.environ.get("RATE_LIMIT_BURST", 60))),

        FF_REWRITER_ENABLED=_to_bool(o.get("FF_REWRITER_ENABLED", os.environ.get("FF_REWRITER_ENABLED")), True),
        FF_TOOL_USE_ENABLED=_to_bool(o.get("FF_TOOL_USE_ENABLED", os.environ.get("FF_TOOL_USE_ENABLED")), False),
        FF_ANALYTICS_TO_SHEETS=_to_bool(o.get("FF_ANALYTICS_TO_SHEETS", os.environ.get("FF_ANALYTICS_TO_SHEETS")), False),

        ENVIRONMENT=environment,
        BASE_URL=o.get("BASE_URL", os.environ.get("BASE_URL", "http://localhost:10000")),
        HEALTH_PATH=o.get("HEALTH_PATH", os.environ.get("HEALTH_PATH", "/health")),
    )
