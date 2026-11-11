"""Single source of truth for where file-backed runtime state lives.

Resolution order for every path:

1. Its explicit environment variable (``ANALYTICS_DB_PATH``, ``SECURITY_DB_PATH``,
   ``CRM_SNAPSHOT_PATH``, ``AUDIT_LOG_PATH``, ``LOG_DIR``).
2. ``<V7_DATA_DIR>/logs/<name>`` when a data directory is configured.
3. ``logs/<name>`` relative to the working directory.

Deployments created before this module existed stored the analytics database at
``/app/logs/analytics.db`` and the security database at ``logs/security.db``
regardless of ``V7_DATA_DIR``. When the preferred location does not exist yet
but the historical file does, the historical file keeps being used so an
upgrade never appears to lose accounts, sessions, leads or analytics.
"""
from __future__ import annotations

import os
from pathlib import Path

_LEGACY_ANALYTICS = Path("/app/logs/analytics.db")
_LEGACY_SECURITY = Path("logs/security.db")


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def data_root() -> Path | None:
    value = _env("V7_DATA_DIR")
    return Path(value) if value else None


def logs_dir() -> Path:
    configured = _env("LOG_DIR")
    if configured:
        return Path(configured)
    root = data_root()
    return root / "logs" if root else Path("logs")


def _state_dir() -> Path:
    """Durable state follows the data directory, not the optional LOG_DIR."""
    root = data_root()
    return root / "logs" if root else Path("logs")


def _resolve(variable: str, name: str, legacy: Path | None = None) -> Path:
    configured = _env(variable)
    if configured:
        return Path(configured)
    preferred = _state_dir() / name
    if legacy is not None and not preferred.exists() and legacy.is_file():
        return legacy
    return preferred


def analytics_db_path() -> Path:
    # The historical absolute path is only meaningful inside the POSIX container.
    legacy = _LEGACY_ANALYTICS if os.name == "posix" else None
    return _resolve("ANALYTICS_DB_PATH", "analytics.db", legacy)


def security_db_path() -> Path:
    return _resolve("SECURITY_DB_PATH", "security.db", _LEGACY_SECURITY)


def crm_snapshot_path() -> Path:
    return _resolve("CRM_SNAPSHOT_PATH", "crm_snapshot.json")


def audit_log_path() -> Path:
    return _resolve("AUDIT_LOG_PATH", "selfrepair.log")
