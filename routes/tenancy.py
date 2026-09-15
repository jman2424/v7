"""Tenant selection and role-aware tenant access for HTTP routes."""

from __future__ import annotations

from typing import Any, Iterable

from flask import abort, session

from retrieval.storage import Storage


PLATFORM_ROLES = {"admin", "platform_admin"}
TENANT_ROLES = {"business_owner", "business_staff"}


def user_roles(user: dict[str, Any] | None = None) -> set[str]:
    """Normalize legacy `role` and current `roles` session fields."""
    current = user if user is not None else session.get("user") or {}
    if not isinstance(current, dict):
        return set()

    roles = current.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if current.get("role"):
        roles = [*roles, current["role"]]
    return {str(role).strip().lower() for role in roles if str(role).strip()}


def is_platform_operator(user: dict[str, Any] | None = None) -> bool:
    return bool(user_roles(user).intersection(PLATFORM_ROLES))


def resolve_admin_tenant(requested: str, default_tenant: str) -> str:
    """Resolve an admin tenant while preventing owner/staff tenant hopping."""
    from service.security import authorized_tenant
    return authorized_tenant(requested, default_tenant)


def require_admin_role() -> None:
    roles = user_roles()
    if not roles.intersection(PLATFORM_ROLES | TENANT_ROLES):
        abort(403, description="forbidden")


def require_platform_operator() -> None:
    if not is_platform_operator():
        abort(403, description="platform_operator_required")
