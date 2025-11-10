"""
Container — creates and holds singletons.

Provides:
- Stores (retrieval/*)
- Services (services/*)
- Mode strategy (ai_modes/*) based on Settings.MODE
"""

from __future__ import annotations
from dataclasses import dataclass

from app.config import Settings
from retrieval.storage import Storage
from retrieval.catalog_store import CatalogStore
from retrieval.policy_store import PolicyStore
from retrieval.geo_store import GeoStore
from retrieval.faq_store import FAQStore
from retrieval.synonyms_store import SynonymsStore
from retrieval.overrides_store import OverridesStore

from services.analytics_service import AnalyticsService
from services.crm_service import CRMService
from services.memory import Memory
from services.rewriter import Rewriter
from services.router import Router
from services.sales_flows import SalesFlows

from ai_modes.contracts import ModeContracts
from ai_modes.v5_legacy import LegacyMode
from ai_modes.v6_hybrid import HybridMode
from ai_modes.v7_flagship import FlagshipMode


@dataclass
class Container:
    settings: Settings

    def __post_init__(self):
        # Retrieval layer
        self.storage = Storage(self.settings.BUSINESS_KEY)
        self.catalog = CatalogStore(self.storage)
        self.policy = PolicyStore(self.storage)
        self.geo = GeoStore(self.storage)
        self.faq = FAQStore(self.storage)
        self.synonyms = SynonymsStore(self.storage)
        self.overrides = OverridesStore(self.storage)

        # Services
        self.analytics = AnalyticsService(self.settings)
        self.crm = CRMService(self.settings)
        self.memory = Memory()
        self.rewriter = Rewriter(self.settings)
        self.sales = SalesFlows(self.catalog)

        # Router is deterministic core used by all modes
        self.router = Router(self.catalog, self.faq, self.synonyms, self.geo, self.policy)

        # Mode strategy
        self.mode: ModeContracts
        if self.settings.MODE == "V5":
            self.mode = LegacyMode(self.router, self.rewriter, self.sales)
        elif self.settings.MODE == "V7":
            self.mode = FlagshipMode(self.router, self.rewriter, self.sales, self.catalog, self.policy, self.geo)
        else:
            self.mode = HybridMode(self.router, self.rewriter, self.sales)
