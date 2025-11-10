"""
Analytics package initializer.

Exports:
- compute_kpis(events)                -> dict
- compute_rollups(events, by="day")   -> dict
- summarize_tenant(events, tenant)    -> dict
- export_csv(rows, path)              -> str
- export_to_sheets(rows, sheets_ctx)  -> dict

Connections:
- services/analytics_service.py calls compute_* to build chart payloads.
- routes/analytics_routes.py uses exporters for CSV/Sheets.
"""

from .metrics import compute_kpis, compute_rollups, summarize_tenant
from .exporters import export_csv, export_to_sheets

__all__ = [
    "compute_kpis",
    "compute_rollups",
    "summarize_tenant",
    "export_csv",
    "export_to_sheets",
]
