"""Operator-owned switches for new platform offer claims; accepted terms persist."""
from __future__ import annotations

import logging
import os
from typing import Any

from flask import current_app, has_app_context, has_request_context, request

FILENAME = 'platform_promotions.json'
DEFAULTS = {'setup_enabled': True, 'highstreet_enabled': True}
logger = logging.getLogger(__name__)


def validate(value: Any) -> dict[str, bool]:
    if (not isinstance(value, dict) or set(value) != set(DEFAULTS)
            or any(type(enabled) is not bool for enabled in value.values())):
        raise ValueError('invalid_platform_promotions')
    return value.copy()


def document(storage: Any, tenant: str) -> Any:
    try:
        return storage.read_json(tenant, FILENAME)
    except FileNotFoundError:
        return None


def _load_flags() -> dict[str, bool]:
    """Read only fixed public switches, never a caller-selected tenant/document.

    This document deliberately stays outside the business-knowledge cache: a
    successful pause must apply to the next redemption and marketing request.
    """
    try:
        if has_app_context():
            container: Any = getattr(current_app, 'container')
            tenant = container.settings.PLATFORM_MARKETING_TENANT
            storage = container.storage
        else:
            from retrieval.storage import Storage
            tenant = os.getenv('PLATFORM_MARKETING_TENANT', '')
            storage = Storage(tenant) if tenant else None
        if not tenant:
            return DEFAULTS.copy()  # Preserve pre-control deployments.
        raw = document(storage, tenant)
        return validate(raw) if raw is not None else DEFAULTS.copy()
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.warning('Platform promotion policy unavailable error_type=%s', type(exc).__name__)
        return dict.fromkeys(DEFAULTS, False)


def public_flags() -> dict[str, bool]:
    # Share a single read inside this HTTP request, never between requests or
    # background jobs. A new claim always observes a fresh policy read.
    if has_request_context():
        cached = request.environ.get('v7.platform_promotions')
        if cached is not None:
            return validate(cached)
    flags = _load_flags()
    if has_request_context():
        request.environ['v7.platform_promotions'] = flags.copy()
    return flags


def enabled(campaign: str) -> bool:
    from service.billing_promotions import HIGHSTREET, SETUP
    key = {SETUP: 'setup_enabled', HIGHSTREET: 'highstreet_enabled'}.get(campaign)
    return bool(key and public_flags()[key])
