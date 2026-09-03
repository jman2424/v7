"""Tenant-bound management accounts for the V7 owner console."""

from __future__ import annotations

import json
import re
import secrets
from typing import Any, Dict, List

from retrieval.storage import Storage


ACCOUNT_FILE = "owner_accounts.json"
MANAGED_ROLES = {"business_owner", "business_staff"}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AccountService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def list_accounts(self, tenant: str) -> List[Dict[str, Any]]:
        return [self._public_account(account) for account in self._accounts(tenant)]

    def create_account(self, tenant: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "")
        roles = self._roles(payload.get("roles"))

        if not _EMAIL_RE.fullmatch(email) or len(email) > 320:
            raise ValueError("invalid_account_email")
        if len(password) < 12 or len(password) > 256:
            raise ValueError("password_must_be_at_least_12_characters")

        accounts = self._accounts(tenant)
        if any(secrets.compare_digest(str(account.get("email") or "").lower(), email) for account in accounts):
            raise ValueError("account_already_exists")

        from service.security import hash_password

        account = {
            "id": f"account:{secrets.token_urlsafe(12)}",
            "email": email,
            "password_hash": hash_password(password),
            "roles": roles,
            "active": True,
        }
        self.storage.write_json(tenant, ACCOUNT_FILE, [*accounts, account])
        return self._public_account(account)

    def _accounts(self, tenant: str) -> List[Dict[str, Any]]:
        try:
            raw = self.storage.read_json(tenant, ACCOUNT_FILE)
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError):
            return []
        return [dict(account) for account in raw if isinstance(account, dict)] if isinstance(raw, list) else []

    @staticmethod
    def _roles(value: Any) -> List[str]:
        roles = value if isinstance(value, list) else []
        normalized = sorted({str(role).strip().lower() for role in roles if str(role).strip()})
        if not normalized or not set(normalized).issubset(MANAGED_ROLES):
            raise ValueError("invalid_account_roles")
        return normalized

    @staticmethod
    def _public_account(account: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(account.get("id") or ""),
            "email": str(account.get("email") or ""),
            "roles": [str(role) for role in account.get("roles") or []],
            "active": account.get("active") is not False,
        }
