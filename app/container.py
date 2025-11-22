"""
Container — creates and holds singletons.

Provides:
- Stores (retrieval/*)
- Services (service/*)
- MessageHandler orchestrator for V5/V6/V7 routing
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from app.config import Settings

# Retrieval layer
from retrieval.storage import Storage
from retrieval.catalog_store import CatalogStore
from retrieval.policy_store import PolicyStore
from retrieval.geo_store import GeoStore
from retrieval.faq_store import FAQStore
from retrieval.synonyms_store import SynonymsStore
from retrieval.overrides_store import OverridesStore

# Services
from service.analytics_service import AnalyticsService
from service.crm_service import CRMService
from service.memory import Memory
from service.rewriter import Rewriter
from service.router import Router
from service.sales_flows import SalesFlows

# Orchestrator
from service.message_handler import MessageHandler
from service import HandlerDeps  # dataclass used by MessageHandler


@dataclass
class Container:
    settings: Settings

    # filled in during __post_init__
    handler: MessageHandler | None = None

    # you can keep these attrs accessible if other parts of the app use them
    storage: Storage | None = None
    catalog: CatalogStore | None = None
    policy: PolicyStore | None = None
    geo: GeoStore | None = None
    faq: FAQStore | None = None
    synonyms: SynonymsStore | None = None
    overrides: OverridesStore | None = None

    analytics: AnalyticsService | None = None
    crm: CRMService | None = None
    memory: Memory | None = None
    rewriter: Rewriter | None = None
    sales: SalesFlows | None = None
    router: Router | None = None

    def __post_init__(self):
        # ---------- Retrieval layer ----------
        #
        # Storage is keyed by BUSINESS_KEY (e.g. "TARIQ") and internally
        # looks under business/<BUSINESS_KEY>/catalog.json, faq.json, etc.
        #
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

        # ---------- Router (synonyms + geo prefixes) ----------
        coverage_prefixes: List[str] = []

        # Try common attribute names on GeoStore so we don't hardcode
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

        # ---------- HandlerDeps + master MessageHandler ----------
        deps = HandlerDeps(
            # core infra
            analytics=self.analytics,
            crm=self.crm,
            memory=self.memory,
            rewriter=self.rewriter,

            # routing + data
            router=self.router,
            catalog=self.catalog,
            policy=self.policy,
            geo=self.geo,
            faq=self.faq,
            synonyms=self.synonyms,
            overrides=self.overrides,
        )

        # Master dispatcher (V5/V6/V7) – this is what routes everything now
        self.handler = MessageHandler(deps)
