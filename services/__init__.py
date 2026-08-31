"""Compatibility aliases for the historical ``services`` package name.

The application code now lives under ``service``. Some tests, scripts, and older
routes still import ``services.*``. Keep those imports working while the codebase
is migrated gradually.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Dict

_ALIASES = (
    "analytics_db",
    "analytics_service",
    "audit",
    "crm_service",
    "exporter",
    "memory",
    "message_handler",
    "rate_limit",
    "rewriter",
    "router",
    "sales_flows",
    "security",
    "self_repair",
    "validators",
)


def _load(name: str) -> ModuleType:
    if name not in _ALIASES:
        raise AttributeError(name)
    module = importlib.import_module(f"service.{name}")
    sys.modules[f"services.{name}"] = module
    globals()[name] = module
    return module


for _name in _ALIASES:
    _load(_name)


def __getattr__(name: str) -> ModuleType:
    return _load(name)


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_ALIASES))
