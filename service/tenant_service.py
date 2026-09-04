"""Platform-admin tenant onboarding for the JSON-backed V7 deployment."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from retrieval.storage import Storage


class TenantService:
    """Creates clean tenant workspaces without copying another business's data."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def list_tenants(self) -> List[Dict[str, Any]]:
        tenants: List[Dict[str, Any]] = []
        if not self.storage.business_root.exists():
            return tenants

        for directory in sorted(self.storage.business_root.iterdir(), key=lambda item: item.name.lower()):
            if not directory.is_dir() or directory.name == "versions":
                continue
            try:
                key = Storage.validate_tenant_key(directory.name)
            except ValueError:
                continue

            store_info = self._read_optional(directory / "store_info.json")
            branding = self._read_optional(directory / "branding.json")
            widget = branding.get("widget") if isinstance(branding, dict) else {}
            widget = widget if isinstance(widget, dict) else {}
            tenants.append(
                {
                    "key": key,
                    "name": str(store_info.get("name") or key) if isinstance(store_info, dict) else key,
                    "widget_configured": bool(widget.get("allowed_origins")),
                    "valid": self._is_valid(key),
                }
            )
        return tenants

    def create_tenant(self, key: str, name: str) -> Dict[str, Any]:
        tenant_key = Storage.validate_tenant_key(key)
        business_name = str(name or "").strip()
        if not business_name or len(business_name) > 120:
            raise ValueError("invalid_business_name")

        target = self.storage.tenant_dir(tenant_key)
        if target.exists():
            raise ValueError("tenant_exists")

        staging_parent = self.storage.business_root
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".tenant-", dir=staging_parent))
        try:
            self._write_starter_files(staging, business_name)
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        return {
            "key": tenant_key,
            "name": business_name,
            "widget_configured": False,
            "valid": self._is_valid(tenant_key),
        }

    def _is_valid(self, tenant: str) -> bool:
        report = self.storage.validate_tenant(tenant)
        return all(
            entry.get("valid") is not False
            for entry in (report.get("files") or {}).values()
            if entry.get("exists")
        )

    @staticmethod
    def _read_optional(path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def _write_starter_files(self, target: Path, business_name: str) -> None:
        self._write_json(
            target / "catalog.json",
            {
                "version": 1,
                "categories": [
                    {
                        "id": "setup",
                        "name": "Setup required",
                        "items": [
                            {
                                "sku": "REPLACE_BEFORE_LAUNCH",
                                "name": "Replace this starter item before launch",
                                "price": 0,
                                "unit": "each",
                                "tags": ["setup"],
                                "in_stock": False,
                            }
                        ],
                    }
                ],
            },
        )
        self._write_json(target / "delivery.json", {"areas": [], "click_and_collect": False, "notes": "Delivery has not been configured."})
        self._write_json(target / "branches.json", [])
        self._write_json(target / "faq.json", [])
        self._write_json(target / "offers.json", [])
        self._write_json(target / "synonyms.json", {})
        self._write_json(target / "overrides.json", {})
        self._write_json(
            target / "branding.json",
            {
                "theme": {
                    "primary_color": "#0f9d58",
                    "secondary_color": "#ffffff",
                    "accent_color": "#d92d20",
                    "text_color": "#172033",
                    "font_family": "Inter, sans-serif",
                },
                "logo": {"light": "", "dark": ""},
                "favicon": "",
                "widget": {
                    "avatar": "",
                    "greeting": f"Hi, welcome to {business_name}. How can I help?",
                    "chat_title": f"{business_name} sales assistant",
                    "allowed_origins": [],
                },
            },
        )
        self._write_json(
            target / "store_info.json",
            {
                "name": business_name,
                "about": "Complete this company profile before launching the sales assistant.",
                "email": "",
                "phone": "",
                "website": "",
                "certifications": [],
                "social": {},
            },
        )
