"""
Container — creates and holds singletons.

Provides:
- Stores (retrieval/*)
- Services (service/*)
- Mode strategy (ai_modes/*) based on Settings.MODE
- MessageHandler orchestrator for V6/V7 routing
"""

from __future__ import annotations
from dataclasses import dataclass

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
from service import HandlerDeps  # provides the deps dataclass used by MessageHandler

# AI modes
from ai_modes.contracts import ModeStrategy
from ai_modes.v5_legacy import V5Legacy
from ai_modes.v6_hybrid import AIV6Hybrid
from ai_modes.v7_flagship import AIV7Flagship


@dataclass
class Container:
    settings: Settings
    # filled in during __post_init__
    mode: ModeStrategy | None = None
    handler: MessageHandler | None = None

    def __post_init__(self):
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

        # Core deterministic router used by all modes
        # Router.__init__ only takes 2 args (plus self), not 5
        self.router = Router(self.catalog, self.faq)

        # ---------- Mode strategy ----------
        if self.settings.MODE == "V5":
            self.mode = V5Legacy(self.router, self.rewriter, self.sales)
        elif self.settings.MODE == "V7":
            self.mode = AIV7Flagship(
                self.router,
                self.rewriter,
                self.sales,
                self.catalog,
                self.policy,
                self.geo,
            )
        else:
            # default: V6 hybrid
            self.mode = AIV6Hybrid(self.router, self.rewriter, self.sales)

        # ---------- Message orchestrator (AI Mode V6 pipeline) ----------
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
