"""
Service package exports & light factories.

Exposes:
- constants: DEFAULT_SESSION_TTL
- factories: make_message_handler(...)
- protocol types for DI hints
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

DEFAULT_SESSION_TTL = 15 * 60  # 15 minutes

# ---- Protocols (for type-hints / DI) ----


class CacheLike(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...


class ModeStrategy(Protocol):
    def name(self) -> str: ...
    def plan(self, user_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]: ...
    def rewrite(self, draft: str, ctx: Dict[str, Any]) -> str: ...


class RewriterLike(Protocol):
    def rewrite(self, text: str, *, style: Optional[str] = None) -> str: ...


class AnalyticsLike(Protocol):
    def log_event(self, tenant: str, event: Dict[str, Any]) -> None: ...
    def kpi_increment(self, tenant: str, key: str, n: int = 1) -> None: ...


class CRMLike(Protocol):
    def upsert_lead(
        self,
        tenant: str,
        *,
        name: Optional[str],
        phone: Optional[str],
        channel: str,
        session_id: str,
        tags: Optional[list[str]] = None,
    ) -> Dict[str, Any]: ...
    def append_conversation(self, tenant: str, lead_id: str, message: Dict[str, Any]) -> None: ...


class CatalogStoreLike(Protocol):
    def search(
        self,
        text: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ): ...
    def get_item_by_sku(self, sku: str): ...
    def price_of(self, sku: str) -> Optional[float]: ...
    def in_stock(self, sku: str) -> Optional[bool]: ...


class PolicyStoreLike(Protocol):
    def delivery_rule_for(self, postcode: str) -> Optional[Dict[str, Any]]: ...
    def delivery_summary(self, postcode: str) -> Optional[str]: ...
    def click_and_collect(self) -> bool: ...


class GeoStoreLike(Protocol):
    def nearest_for_postcode(self, postcode: str, geocoder=None) -> Optional[Dict[str, Any]]: ...


class FAQStoreLike(Protocol):
    def best_match(
        self,
        user_question: str,
        *,
        hint_tags: Optional[list[str]] = None,
        min_sim: float = 0.18,
        top_k: int = 1,
    ) -> list[Dict[str, Any]]: ...
    def render_answer(
        self,
        faq_entry: Dict[str, Any],
        placeholders: Optional[Dict[str, str]] = None,
    ) -> str: ...


class SynonymsStoreLike(Protocol):
    def canonical(self, term: str) -> str: ...
    def apply(self, tags: list[str]) -> list[str]: ...


class OverridesStoreLike(Protocol):
    def get(self, dotted_key: str, default=None): ...
    def get_bool(self, dotted_key: str, default: bool = False) -> bool: ...
    def get_float(self, dotted_key: str, default: float = 0.0) -> float: ...


class MemoryLike(Protocol):
    def get(self, session_id: str, key: str, default=None): ...
    def set(self, session_id: str, key: str, value: Any, ttl: Optional[int] = None) -> None: ...
    def clear(self, session_id: str) -> None: ...


class RouterLike(Protocol):
    def route(self, text: str, ctx: Dict[str, Any]) -> Dict[str, Any]: ...


# ---- Handler factory ----


@dataclass
class HandlerDeps:
    mode: ModeStrategy
    rewriter: RewriterLike
    analytics: AnalyticsLike
    crm: CRMLike
    memory: MemoryLike
    router: RouterLike
    catalog: CatalogStoreLike
    policy: PolicyStoreLike
    geo: GeoStoreLike
    faq: FAQStoreLike
    synonyms: SynonymsStoreLike
    overrides: OverridesStoreLike


def make_message_handler(deps: HandlerDeps):
    # local import to avoid circular import at module import time
    from .message_handler import MessageHandler

    return MessageHandler(deps)
