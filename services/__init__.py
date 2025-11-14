"""
Compatibility shim for `services.*` imports.

Real implementations live in the `service` package (singular).
This module re-exports them so `from services.x import Y` keeps working.
"""

from __future__ import annotations

import sys
from importlib import import_module

# Submodules that exist under `service/`
_SUBMODULES = [
    "analytics_service",
    "audit",
    "crm_service",
    "exporter",
    "memory",
    "message_handler",
    "rate_limit",
    "rewriter",
    "router",
    "sales_flow",
    "security",
    "self_repair",
    "validators",
]

for name in _SUBMODULES:
    try:
        real_mod = import_module(f"service.{name}")
        # make Python think `services.name` *is* `service.name`
        sys.modules[f"services.{name}"] = real_mod
    except ModuleNotFoundError:
        # If a module doesn't exist, skip it - app can still run.
        continue

# Optional: allow `import services` to behave like `import service`
try:
    from service import *  # noqa: F401,F403
except Exception:
    pass
