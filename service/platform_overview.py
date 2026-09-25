"""Read-only inventory of configured businesses and their recorded analytics."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from service.analytics_db import get_errors, get_kpis

logger = logging.getLogger(__name__)
PAGE_SIZE = 50
KNOWLEDGE_FILES = ("catalog.json", "faq.json", "branches.json", "delivery.json",
                   "store_info.json", "branding.json", "overrides.json")


def get_platform_overview(container: Any, *, minutes: int = 1440, page: int = 1) -> dict:
    if container.storage._using_postgres():
        raise RuntimeError("PostgreSQL platform overview requires a scoped tenant inventory")
    root = Path(container.storage.business_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    tenants = sorted(
        (path for path in root.iterdir()
         if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", path.name)
         and path.name.lower() != "versions" and path.is_dir()
         and not path.is_symlink() and path.resolve().parent == root),
        key=lambda path: path.name.casefold(),
    )
    rows = []
    start = (page - 1) * PAGE_SIZE
    for path in tenants[start:start + PAGE_SIZE]:
        issues = []
        name = path.name
        mode = str(container.settings.MODE)
        valid_files = 0
        for filename in KNOWLEDGE_FILES:
            candidate = path / filename
            if candidate.is_symlink() or candidate.resolve().parent != path.resolve():
                issues.append(f"{filename}: inaccessible")
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
                if not isinstance(data, (dict, list)):
                    issues.append(f"{filename}: expected structured data")
                    continue
                valid_files += 1
                if filename == "overrides.json" and isinstance(data, dict) and isinstance(data.get("ai"), dict):
                    mode = str(data["ai"].get("mode") or mode)
                if filename == "store_info.json" and isinstance(data, dict):
                    name = str(data.get("name") or name)[:200]
            except FileNotFoundError:
                issues.append(f"{filename}: missing")
            except (OSError, ValueError):
                issues.append(f"{filename}: unreadable or invalid JSON")
        try:
            kpis = get_kpis(tenant=path.name, minutes=minutes)
            errors = get_errors(tenant=path.name, minutes=minutes, top=5)
            available = True
        except (OSError, sqlite3.Error) as error:
            logger.error("Platform analytics read failed (%s)", type(error).__name__)
            kpis, errors, available = None, [], False
            issues.append("Analytics temporarily unavailable")
        status = "needs_attention" if issues or (kpis and kpis.get("errors")) else (
            "activity_recorded" if kpis and kpis.get("total") else "no_recent_activity"
        )
        rows.append({
            "tenant": path.name, "name": name,
            "mode": mode,
            "status": status, "knowledge_files": valid_files,
            "knowledge_files_expected": len(KNOWLEDGE_FILES), "issues": issues,
            "analytics_available": available, "kpis": kpis, "errors": errors,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_minutes": minutes, "company_count": len(tenants), "page": page,
        "page_size": PAGE_SIZE, "has_next": start + PAGE_SIZE < len(tenants),
        "companies": rows,
    }
