"""Adapters for external providers: billing, business email, WhatsApp and the web widget."""
from __future__ import annotations

from .web_widget import WidgetBridge


def get_widget_bridge() -> WidgetBridge:
    """Stateless bridge helper for the iframe/web SDK contract."""
    return WidgetBridge()
