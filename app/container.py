"""
Container — creates and holds singletons.

Provides:
- Stores (retrieval/*)
- Services (service/*)
- Mode strategy (ai_modes/*) based on Settings.MODE
- MessageHandler orchestrator for V5/V6/V7 routing
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from threading import RLock
from typing import List, Optional

# AI modes (legacy strategy object, still required by HandlerDeps.mode)
from ai_modes.contracts import ModeStrategy
from ai_modes.v5_legacy import V5Legacy
from ai_modes.v6_hybrid import AIV6Hybrid
from ai_modes.v7_flagship import AIV7Flagship
from app.config import Settings
from retrieval.catalog_store import CatalogStore
from retrieval.faq_store import FAQStore
from retrieval.geo_store import GeoStore
from retrieval.overrides_store import OverridesStore
from retrieval.policy_store import PolicyStore

# Retrieval layer
from retrieval.storage import Storage
from retrieval.synonyms_store import SynonymsStore
from service import HandlerDeps  # dataclass used by MessageHandler

# Services
from service.analytics_service import AnalyticsService
from service.crm_service import CRMService
from service.memory import Memory

# Orchestrator
from service.message_handler import MessageHandler
from service.rewriter import Rewriter
from service.router import Router
from service.sales_flows import SalesFlows


@dataclass
class Container:
    settings: Settings
    # Filled during __post_init__
    mode: Optional[ModeStrategy] = None
    handler: Optional[MessageHandler] = None

    def __post_init__(self):
        self._tenants = {}
        self._tenant_lock = RLock()
        # ---------- Retrieval layer ----------
        self.storage = Storage(self.settings.BUSINESS_KEY)
        self.catalog = CatalogStore(self.storage)
        self.policy = PolicyStore(self.storage)
        self.geo = GeoStore(self.storage)
        self.faq = FAQStore(self.storage)
        self.synonyms = SynonymsStore(self.storage)
        self.overrides = OverridesStore(self.storage)

        # ---------- Services ----------
        self.analytics = AnalyticsService(self.settings)
        self.crm = CRMService()
        self.memory = Memory()
        self.rewriter = Rewriter(self.settings)
        self.sales = SalesFlows(self.catalog)

        # ---------- Router (with geo prefixes) ----------
        coverage_prefixes: List[str] = []

        # Try common attribute names on GeoStore so you don't hardcode anything
        for attr in ("coverage_prefixes", "prefixes", "all_prefixes"):
            if hasattr(self.geo, attr):
                val = getattr(self.geo, attr) or []
                if isinstance(val, list):
                    coverage_prefixes = val
                break

        self.router = Router(
            synonyms=self.synonyms,
            geo_prefixes=coverage_prefixes,
        )

        # ---------- Mode strategy (legacy, still required by HandlerDeps.mode) ----------
        # Settings.MODE should be "V5", "V6", or "V7"
        mode_name = (self.settings.MODE or "V7").upper().replace("AI", "")

        if mode_name == "V5":
            # V5Legacy takes no constructor args
            self.mode = V5Legacy()
        elif mode_name == "V6":
            # AIV6Hybrid takes no constructor args
            self.mode = AIV6Hybrid(self.router, self.rewriter, self.sales)
        else:
            # default: V7 flagship, also no constructor args
            self.mode = AIV7Flagship(catalog=self.catalog, policy=self.policy, geo=self.geo,
                                     faq=self.faq, overrides=self.overrides, crm=self.crm)

        # ---------- Message orchestrator ----------
        deps = HandlerDeps(
            mode=self.mode,
            rewriter=self.rewriter,
            analytics=self.analytics,
            crm=self.crm,
            memory=self.memory,
            router=self.router,
            catalog=self.catalog,
            policy=self.policy,
            geo=self.geo,
            faq=self.faq,
            synonyms=self.synonyms,
            overrides=self.overrides,
        )

        self.handler = MessageHandler(deps)

    def for_tenant(self, tenant: str):
        directory = self.storage.tenant_dir(tenant)
        if not directory.is_dir():
            raise FileNotFoundError("Tenant not found")
        # Rebuild retrieval stores after business data changes without sharing
        # catalog or memory between companies. Preserve conversation memory.
        stamp = tuple((p.name, p.stat().st_mtime_ns) for p in sorted(directory.glob("*.json")))
        with self._tenant_lock:
            cached = self._tenants.get(tenant)
            if cached and cached[0] == stamp:
                return cached[1]
            scoped = Container(replace(self.settings, BUSINESS_KEY=tenant))
            scoped.crm = self.crm
            scoped.handler.crm = self.crm
            scoped.handler.deps.crm = self.crm
            if cached:
                scoped.memory = cached[1].memory
                scoped.handler.deps.memory = scoped.memory
                scoped.handler.memory = scoped.memory
            self._tenants[tenant] = (stamp, scoped)
            return scoped
