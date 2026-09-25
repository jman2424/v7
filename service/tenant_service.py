"""Platform-admin tenant onboarding for the JSON-backed V7 deployment."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from retrieval.storage import Storage
from service.sales_playbook import default_sales_playbook


class TenantService:
    """Creates clean tenant workspaces without copying another business's data."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def list_tenants(self) -> List[Dict[str, Any]]:
        if self.storage._using_postgres():
            raise RuntimeError("PostgreSQL tenant inventory requires a scoped design")
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
                    "activation": self.activation(key),
                }
            )
        return tenants

    @staticmethod
    def activation(key):
        from service.tenant_access import activation
        return activation(key)

    def create_tenant(self, key: str, name: str, owner=None, initial_account=None) -> Dict[str, Any]:
        tenant_key = Storage.validate_tenant_key(key)
        business_name = str(name or "").strip()
        if not business_name or len(business_name) > 120:
            raise ValueError("invalid_business_name")

        if self.storage._using_postgres():
            from service.postgres_business_documents import PostgresBusinessDocuments
            from service.tenant_access import owner_key
            documents = self._starter_documents(business_name)
            if initial_account is not None:
                from service.account_service import ACCOUNT_FILE
                documents[ACCOUNT_FILE] = [initial_account]
            PostgresBusinessDocuments(tenant_key).create_tenant(
                documents, owner_key=owner_key(owner) if owner else None
            )
            return {
                "key": tenant_key,
                "name": business_name,
                "widget_configured": False,
                "valid": self._is_valid(tenant_key),
                "activation": self.activation(tenant_key),
            }

        target = self.storage.tenant_dir(tenant_key)
        if target.exists():
            raise ValueError("tenant_exists")

        staging_parent = self.storage.business_root
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".tenant-", dir=staging_parent))
        registered = False
        try:
            self._write_starter_files(staging, business_name)
            if initial_account is not None:
                from service.account_service import ACCOUNT_FILE
                self._write_json(staging / ACCOUNT_FILE, [initial_account])
            from service.tenant_access import register
            register(tenant_key, owner)
            registered = True
            os.replace(staging, target)
        except Exception:
            if registered:
                from service.tenant_access import unregister
                unregister(tenant_key)
            shutil.rmtree(staging, ignore_errors=True)
            raise

        return {
            "key": tenant_key,
            "name": business_name,
            "widget_configured": False,
            "valid": self._is_valid(tenant_key),
            "activation": self.activation(tenant_key),
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
        for filename, payload in self._starter_documents(business_name).items():
            self._write_json(target / filename, payload)

    @staticmethod
    def _starter_documents(business_name: str) -> Dict[str, Any]:
        from service.business_core import empty_core
        from service.conversion_actions import DEFAULT_ACTIONS
        playbook = default_sales_playbook()
        playbook["offering_type"] = "mixed"
        playbook["primary_goal"] = "answer_questions"
        return {
            "catalog.json": {"version": 1, "categories": []},
            "business_core.json": empty_core(),
            "delivery.json": {"areas": [], "click_and_collect": False, "notes": "Delivery has not been configured."},
            "branches.json": [],
            "faq.json": [],
            "offers.json": [],
            "synonyms.json": {},
            "sales_actions.json": DEFAULT_ACTIONS,
            "overrides.json": {
                "tone": {"style": "friendly", "max_sentences": 2},
                "sales_playbook": playbook,
            },
            "branding.json": {
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
            "store_info.json": {
                "name": business_name,
                "about": "",
                "email": "",
                "phone": "",
                "website": "",
                "certifications": [],
                "social": {},
            },
        }
