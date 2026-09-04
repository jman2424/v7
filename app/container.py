"""
Container — creates and holds singletons.

Provides:
- Stores (retrieval/*)
- Services (service/*)
- Mode strategy (ai_modes/*) based on Settings.MODE
- MessageHandler orchestrator for V5/V6/V7 routing
"""

from __future__ import annotations
import os
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional

from app.config import Settings

# Retrieval layer
from retrieval.storage import Storage
from retrieval.catalog_store import CatalogStore
from retrieval.policy_store import PolicyStore
from retrieval.geo_store import GeoStore
from retrieval.faq_store import FAQStore
from retrieval.offer_store import OfferStore
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

# AI modes (legacy strategy object, still required by HandlerDeps.mode)
from ai_modes.contracts import ModeStrategy
from ai_modes.v5_legacy import V5Legacy
from ai_modes.v6_hybrid import AIV6Hybrid
from ai_modes.v7_flagship import AIV7Flagship


REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_persistent_business_data() -> None:
    """Seed an empty mounted data directory without overwriting tenant changes."""
    raw_data_root = (os.getenv("V7_DATA_DIR") or "").strip()
    if not raw_data_root:
        return

    data_root = Path(raw_data_root).expanduser().resolve()
    target = data_root / "business"
    marker = data_root / ".v7_data_initialized"
    if marker.exists():
        return

    data_root.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        source = REPO_ROOT / "business"
        if not source.is_dir():
            raise RuntimeError("Bundled tenant data is missing")
        staging = Path(tempfile.mkdtemp(prefix=".v7-business-", dir=data_root))
        try:
            shutil.copytree(source, staging / "business")
            os.replace(staging / "business", target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    marker.write_text("initialized\n", encoding="utf-8")


@dataclass
class Container:
    settings: Settings
    # Filled during __post_init__
    mode: Optional[ModeStrategy] = None
    handler: Optional[MessageHandler] = None
    _tenant_containers: Dict[str, "Container"] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        # ---------- Retrieval layer ----------
        _bootstrap_persistent_business_data()
        self.storage = Storage(self.settings.BUSINESS_KEY)
        self.catalog = CatalogStore(self.storage)
        self.policy = PolicyStore(self.storage)
        self.geo = GeoStore(self.storage)
        self.faq = FAQStore(self.storage)
        self.offers = OfferStore(self.storage)
        self.synonyms = SynonymsStore(self.storage)
        self.overrides = OverridesStore(self.storage)
        self.business_profile = self._load_business_profile()
        self.business_name = str(self.business_profile.get("name") or "").strip()

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
        mode_name = (self.settings.MODE or "V7").upper()

        if mode_name == "V5":
            # V5Legacy takes no constructor args
            self.mode = V5Legacy()
        elif mode_name == "V6":
            # AIV6Hybrid takes no constructor args
            self.mode = AIV6Hybrid()
        else:
            # default: V7 flagship, also no constructor args
            self.mode = AIV7Flagship()

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
            offers=self.offers,
            synonyms=self.synonyms,
            overrides=self.overrides,
            business_name=self.business_name,
            business_profile=self.business_profile,
        )

        self.handler = MessageHandler(deps)

    def for_tenant(self, tenant: str) -> "Container":
        """Return an isolated runtime whose stores are bound to one tenant."""
        tenant_key = Storage.validate_tenant_key(tenant)
        if tenant_key == self.settings.BUSINESS_KEY:
            return self

        if not self.storage.tenant_dir(tenant_key).is_dir():
            raise ValueError("unknown_tenant")

        cached = self._tenant_containers.get(tenant_key)
        if cached is not None:
            return cached

        tenant_container = Container(replace(self.settings, BUSINESS_KEY=tenant_key))
        self._tenant_containers[tenant_key] = tenant_container
        return tenant_container

    def invalidate_tenant(self, tenant: str) -> None:
        """Discard warmed retrieval state after an owner changes tenant data."""
        tenant_key = Storage.validate_tenant_key(tenant)
        if tenant_key == self.settings.BUSINESS_KEY:
            self._tenant_containers.clear()
            self.__post_init__()
            return
        self._tenant_containers.pop(tenant_key, None)

    def _load_business_profile(self) -> Dict[str, object]:
        try:
            profile = self.storage.read_json(self.settings.BUSINESS_KEY, "store_info.json")
        except (FileNotFoundError, ValueError):
            return {}
        if not isinstance(profile, dict):
            return {}
        return profile
