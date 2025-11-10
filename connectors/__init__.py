"""
Connectors package exports.

Factories:
- make_emailer(settings) -> Emailer
- make_maps_client(settings) -> MapsClient
- get_widget_bridge() -> WidgetBridge

These are thin adapters; heavy logic lives in each module.
"""

from __future__ import annotations
from typing import Optional

from app.config import Settings
from .emailer import Emailer
from .maps import MapsClient
from .web_widget import WidgetBridge


def make_emailer(settings: Settings, *, force_smtp: bool | None = None) -> Emailer:
    """
    Build an Emailer using SMTP or HTTP API depending on env.
    Env (optional):
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
      MAIL_API_URL, MAIL_API_KEY, MAIL_FROM
    """
    return Emailer.from_env(force_smtp=force_smtp)


def make_maps_client(settings: Settings, *, cache_ttl_seconds: int = 86_400) -> MapsClient:
    """
    Build a MapsClient with in-proc cache.
    Optional env:
      MAPS_API_URL, MAPS_API_KEY
    """
    return MapsClient.from_env(cache_ttl_seconds=cache_ttl_seconds)


def get_widget_bridge() -> WidgetBridge:
    """Stateless bridge helper for iframe/web SDK contract."""
    return WidgetBridge()
