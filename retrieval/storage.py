"""
Versioned JSON storage for tenant (business) data.

Features
- Read/write JSON under business/{TENANT}/*
- Atomic writes via temp files + os.replace
- JSON Schema validation (schemas/*.schema.json) when provided
- Daily snapshots under business/versions/YYYY-MM-DD/{TENANT}/
  * First write each day mirrors the *entire* tenant folder for that date
  * Every write saves the target file into the same dated snapshot dir
- Audit listing helper (reads business/{TENANT}/audit.log.jsonl if present)
- Tenant validation helper (validates known files against schemas)

Used by:
- routes/files_routes.py (upload/download/version listing)
- scripts/snapshot_backup.py / scripts/restore_snapshot.py
- services/* stores read via this layer (read_json)
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    # jsonschema is pinned in requirements.txt
    import jsonschema  # type: ignore
    _HAS_JSONSCHEMA = True
except Exception:
    _HAS_JSONSCHEMA = False


REPO_ROOT = Path(os.getcwd()).resolve()  # assume app runs from repo root
BUSINESS_ROOT = REPO_ROOT / "business"
VERSIONS_ROOT = BUSINESS_ROOT / "versions"
SCHEMAS_ROOT = Path(__file__).resolve().parents[1] / "schemas"

_TENANT_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_WINDOWS_DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}

# Known tenant files and their schemas (if any)
KNOWN_FILES: Dict[str, Optional[str]] = {
    "business_core.json": "business-core.schema.json",
    "catalog.json": "catalog.schema.json",
    "delivery.json": "delivery.schema.json",
    "branches.json": "branches.schema.json",
    "faq.json": "faq.schema.json",
    "offers.json": "offers.schema.json",
    "synonyms.json": None,
    "overrides.json": None,
    "branding.json": None,
    "store_info.json": "store_info.schema.json",
}


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _atomic_write_json(path: Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


def _read_json(path: Path) -> Any:
    def invalid_constant(_value):
        raise ValueError("JSON numbers must be finite")

    def finite_number(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("JSON numbers must be finite")
        return number

    with path.open("r", encoding="utf-8") as f:
        return json.load(f, parse_constant=invalid_constant, parse_float=finite_number)


@dataclass(frozen=True, init=False)
class Storage:
    tenant_key: str
    business_root: Path = BUSINESS_ROOT
    versions_root: Path = VERSIONS_ROOT
    schemas_root: Path = SCHEMAS_ROOT

    def __init__(
        self,
        tenant_key: str = "EXAMPLE",
        *,
        base_dir: Optional[Path | str] = None,
        business_root: Optional[Path | str] = None,
        versions_root: Optional[Path | str] = None,
        schemas_root: Optional[Path | str] = None,
    ) -> None:
        runtime_root = Path(os.getcwd()).resolve()
        data_root = (os.getenv("V7_DATA_DIR") or "").strip()
        root = (
            Path(base_dir).resolve()
            if base_dir is not None
            else (Path(data_root).expanduser().resolve() / "business" if data_root else runtime_root / "business")
        )
        if business_root is not None:
            root = Path(business_root).resolve()
        elif base_dir is None and os.getenv("BUSINESS_DATA_ROOT"):
            root = Path(os.environ["BUSINESS_DATA_ROOT"]).expanduser().resolve()

        object.__setattr__(self, "tenant_key", tenant_key)
        object.__setattr__(self, "business_root", root)
        object.__setattr__(self, "_postgres_repositories", {})
        object.__setattr__(self, "_postgres_repository_lock", Lock())
        object.__setattr__(
            self,
            "versions_root",
            Path(versions_root).resolve() if versions_root is not None else root / "versions",
        )
        object.__setattr__(
            self,
            "schemas_root",
            Path(schemas_root).resolve()
            if schemas_root is not None
            else (runtime_root / "schemas" if (runtime_root / "schemas").exists() else SCHEMAS_ROOT),
        )

    # -------- paths --------

    @staticmethod
    def validate_tenant_key(tenant: str) -> str:
        """Return a safe tenant key or reject path-like identifiers."""
        value = str(tenant or "").strip()
        if not _TENANT_KEY_RE.fullmatch(value) or value.lower() in {"versions", *_WINDOWS_DEVICES}:
            raise ValueError("invalid_tenant")
        return value

    @staticmethod
    def _using_postgres() -> bool:
        from service.session_store import _using_postgres
        return _using_postgres()

    def _postgres_repository(self, tenant: Optional[str] = None):
        from service.postgres_business_documents import PostgresBusinessDocuments
        key = self.validate_tenant_key(tenant or self.tenant_key)
        # Reuse the same repository during revision-checked transactions. Its
        # active connection is held in a ContextVar, not shared between requests.
        # Concurrent first reads must not create different ContextVars for the
        # same tenant and split an active write transaction across repositories.
        with self._postgres_repository_lock:
            repositories = self._postgres_repositories
            if key not in repositories:
                repositories[key] = PostgresBusinessDocuments(key)
            return repositories[key]

    def canonical_tenant_key(self, tenant: Optional[str] = None) -> str:
        """Resolve filesystem aliases before authorizing a tenant identity.

        PostgreSQL keys stay exact. SQLite keys use the existing directory's
        spelling, so case-insensitive filesystems cannot split account,
        ownership, billing or conversation state into multiple identities.
        """
        key = self.validate_tenant_key(tenant or self.tenant_key)
        if self._using_postgres() or not self.business_root.is_dir():
            return key
        matches = [entry for entry in self.business_root.iterdir()
                   if entry.is_dir() and entry.name.casefold() == key.casefold()]
        if len(matches) > 1:
            raise ValueError("ambiguous_tenant")
        if matches:
            if matches[0].is_symlink():
                raise ValueError("invalid_tenant")
            key = self.validate_tenant_key(matches[0].name)
            self.tenant_dir(key)
        return key

    def tenant_exists(self, tenant: Optional[str] = None) -> bool:
        key = self.validate_tenant_key(tenant or self.tenant_key)
        if self._using_postgres():
            return self._postgres_repository(key).exists()
        return self.tenant_dir(key).is_dir()

    def tenant_keys(self) -> List[str]:
        if self._using_postgres():
            from flask import session
            from service import session_store
            from service.security import management_user
            # Revalidate session revision and privileges before asking the
            # bounded database function for keys. No tenant document is exposed.
            management_user(platform_only=True)
            token = session.get("management_token")
            if not isinstance(token, str):
                raise RuntimeError("Platform administrator session required")
            keys = []
            with session_store.postgres_connection(repeatable_read=True) as connection:
                while True:
                    rows = connection.execute(
                        "SELECT tenant FROM v7_private.list_platform_tenant_keys(%s, %s, %s)",
                        (session_store._digest(token), 500, len(keys)),
                    ).fetchall()
                    keys.extend(self.validate_tenant_key(row[0]) for row in rows)
                    if len(rows) < 500:
                        return keys
        root = self.business_root
        if not root.exists():
            return []
        keys = []
        for directory in root.iterdir():
            if directory.is_dir() and not directory.is_symlink():
                try:
                    if self.tenant_dir(directory.name).is_dir():
                        keys.append(self.validate_tenant_key(directory.name))
                except ValueError:
                    continue
        return sorted(keys, key=str.casefold)

    def tenant_dir(self, tenant: Optional[str] = None) -> Path:
        if self._using_postgres():
            raise RuntimeError("Tenant data has no filesystem path in PostgreSQL mode")
        key = self.validate_tenant_key(tenant or self.tenant_key)
        root = self.business_root.resolve()
        candidate = root / key
        target = candidate.resolve()
        if target.parent != root or target != candidate.absolute() or candidate.is_symlink():
            raise ValueError("invalid_tenant")
        if root.is_dir() and sum(p.is_dir() and p.name.casefold() == key.casefold() for p in root.iterdir()) > 1:
            raise ValueError("ambiguous_tenant")
        return target

    def file_path(self, tenant: Optional[str], filename: str) -> Path:
        if self._using_postgres():
            raise RuntimeError("Tenant data has no filesystem path in PostgreSQL mode")
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", filename)
                or filename.split(".", 1)[0].lower() in _WINDOWS_DEVICES or filename.endswith(".")):
            raise ValueError("invalid_filename")
        root = self.tenant_dir(tenant)
        candidate = root / filename
        target = candidate.resolve()
        if target.parent != root or target != candidate.absolute() or candidate.is_symlink():
            raise ValueError("invalid_filename")
        return target

    def versions_day_dir(self, day: Optional[str] = None, tenant: Optional[str] = None) -> Path:
        if self._using_postgres():
            raise RuntimeError("Tenant versions have no filesystem path in PostgreSQL mode")
        date_str = day or datetime.utcnow().strftime("%Y-%m-%d")
        datetime.strptime(date_str, "%Y-%m-%d")
        root = self.versions_root.resolve()
        day_root = root / date_str
        candidate = day_root / self.validate_tenant_key(tenant or self.tenant_key)
        target = candidate.resolve()
        if (root != self.versions_root.absolute() or not target.is_relative_to(root) or target != candidate.absolute()
                or day_root.is_symlink() or candidate.is_symlink()):
            raise ValueError("invalid_snapshot")
        return target

    # -------- public API --------

    def read_json(self, tenant: Optional[str], filename: str) -> Any:
        """
        Read a tenant JSON file. Raises FileNotFoundError if missing.
        """
        if self._using_postgres():
            return self._postgres_repository(tenant).read_document(filename)
        path = self.file_path(tenant, filename)
        return _read_json(path)

    def load_json(self, path: str) -> Any:
        """
        Backwards-compatible loader for paths like ``EXAMPLE/catalog.json``.
        """
        rel = Path(path)
        if rel.is_absolute():
            if self._using_postgres():
                raise ValueError("invalid_document_path")
            try:
                rel = rel.relative_to(self.business_root)
            except ValueError:
                raise ValueError("invalid_document_path") from None
        if len(rel.parts) != 2:
            raise ValueError("invalid_document_path")
        return self.read_json(rel.parts[0], rel.parts[1])

    def write_json(
        self,
        tenant: Optional[str],
        filename: str,
        data: Any,
        *,
        schema: Optional[str] = None,
        snapshot: bool = True,
    ) -> str:
        """
        Validate (optional) + write atomically to business/{tenant}/{filename}.
        Also snapshots under business/versions/YYYY-MM-DD/{tenant}/

        :returns: snapshot path (str) for the written file within the daily snapshot dir.
        """
        with self.write_lock(tenant):
            return self._write_json(tenant, filename, data, schema=schema, snapshot=snapshot)

    @contextmanager
    def write_lock(self, tenant: Optional[str] = None):
        """Serialize revision-checked MCP/API writes with existing JSON writers."""
        if self._using_postgres():
            with self._postgres_repository(tenant).locked() as connection:
                yield connection
            return
        self.business_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.business_root / '.write-lock.sqlite3'
        for candidate in [lock_path, *(Path(str(lock_path) + suffix) for suffix in ('-journal', '-wal', '-shm'))]:
            if candidate.resolve() != candidate.absolute() or candidate.is_symlink():
                raise ValueError("invalid_write_lock")
        db = sqlite3.connect(lock_path, timeout=10)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield
            db.commit()
        finally:
            db.close()

    def _write_json(self, tenant, filename, data, *, schema=None, snapshot=True):
        """Internal writer; callers hold write_lock across read/check/write."""
        tkey = tenant or self.tenant_key
        # Both backends must reject non-JSON numbers or recursive structures
        # before creating snapshots, changing a revision, or writing any data.
        try:
            json.dumps(data, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, RecursionError):
            raise ValueError('invalid_document_json') from None
        # schema may be provided as "schemas/catalog.schema.json" or just "catalog.schema.json"
        if filename == "catalog.json" and isinstance(data, dict) and "product_catalog" in data and "categories" not in data:
            schema = "catalog-sheet.schema.json"
        if filename == 'business_core.json':
            from service.business_core import validate_core
            validate_core(data)
            schema = 'business-core.schema.json'
        if filename == 'privacy.json':
            from service.privacy_settings import validate_settings
            validate_settings(data)
        if schema:
            schema_path = self._schema_path(schema)
            self._validate_json(data, schema_path)

        if self._using_postgres():
            return self._postgres_repository(tkey).write_document(filename, data, snapshot=snapshot)

        dest = self.file_path(tkey, filename)
        snap_path = ""
        if snapshot:
            snap_dir = self._ensure_daily_snapshot_folder(tkey)
            snapshot_file = snap_dir / filename
            if snapshot_file.resolve() != snapshot_file.absolute() or snapshot_file.is_symlink():
                raise ValueError("invalid_snapshot")
            if dest.exists() and not snapshot_file.exists():
                shutil.copy2(dest, snapshot_file)
            if snapshot_file.exists():
                snap_path = str(snapshot_file.relative_to(self.versions_root))
        _atomic_write_json(dest, data)

        return snap_path

    def list_versions(self, tenant: Optional[str] = None) -> List[str]:
        """
        Return list of YYYY-MM-DD version folders that contain this tenant.
        """
        tkey = self.validate_tenant_key(tenant or self.tenant_key)
        if self._using_postgres():
            return self._postgres_repository(tkey).list_version_days()
        if not self.versions_root.exists():
            return []
        days: List[str] = []
        for day_dir in sorted(self.versions_root.iterdir()):
            if not day_dir.is_dir():
                continue
            try:
                if self.versions_day_dir(day_dir.name, tkey).is_dir():
                    days.append(day_dir.name)
            except ValueError:
                continue
        return days

    def list_audit_entries(self, tenant: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Read audit log lines from business/{tenant}/audit.log.jsonl if present.
        """
        tkey = tenant or self.tenant_key
        if self._using_postgres():
            try:
                entries = self._postgres_repository(tkey).read_document("audit.log.jsonl")
            except FileNotFoundError:
                return []
            if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                raise ValueError("invalid_audit_log")
            return entries
        log_path = self.file_path(tkey, "audit.log.jsonl")
        if not log_path.exists():
            return []
        out: List[Dict[str, Any]] = []
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    # tolerate bad lines
                    continue
        return out

    def validate_tenant(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        """
        Validate all known files for tenant against schemas (if available).
        """
        tkey = tenant or self.tenant_key
        results: Dict[str, Any] = {"tenant": tkey, "files": {}}
        for fname, schema in KNOWN_FILES.items():
            try:
                data = self.read_json(tkey, fname)
            except FileNotFoundError:
                results["files"][fname] = {"exists": False, "valid": None, "error": None}
                continue
            except (ValueError, OSError):
                results["files"][fname] = {"exists": True, "valid": False, "error": "Invalid JSON"}
                continue
            if fname == "catalog.json" and isinstance(data, dict) and "product_catalog" in data and "categories" not in data:
                schema = "catalog-sheet.schema.json"
            if not schema:
                results["files"][fname] = {"exists": True, "valid": True, "error": None}
                continue
            try:
                schema_path = self._schema_path(schema)
                self._validate_json(data, schema_path)
                results["files"][fname] = {"exists": True, "valid": True, "error": None}
            except Exception as e:
                results["files"][fname] = {"exists": True, "valid": False, "error": str(e)}
        return results

    # -------- internal helpers --------

    def _schema_path(self, schema: str) -> Path:
        """
        Accepts 'catalog.schema.json' or 'schemas/catalog.schema.json'
        """
        p = Path(schema)
        if p.is_absolute():
            return p
        if p.parts and p.parts[0] == "schemas":
            return REPO_ROOT / p
        return self.schemas_root / p

    def _validate_json(self, data: Any, schema_path: Path) -> None:
        if not _HAS_JSONSCHEMA:
            raise RuntimeError(
                f"jsonschema package not available; cannot validate against {schema_path}"
            )
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file missing: {schema_path}")
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=data, schema=schema)

    def _ensure_daily_snapshot_folder(self, tenant: str) -> Path:
        """
        Ensure that today's snapshot folder exists and contains a mirror of current tenant files.
        If the folder for today does not exist, copy entire tenant directory at that moment.
        """
        today_dir = self.versions_day_dir(tenant=tenant)
        if today_dir.exists():
            return today_dir

        # First creation today → mirror current tenant dir
        src = self.tenant_dir(tenant)
        source_files = [self.file_path(tenant, p.name) for p in src.iterdir()
                        if p.is_file() and p.suffix.lower() == ".json"] if src.exists() else []
        today_dir.mkdir(parents=True, exist_ok=True)
        for p in source_files:
            shutil.copy2(p, today_dir / p.name)
        # write a snapshot metadata file
        try:
            source = str(src.relative_to(REPO_ROOT))
        except ValueError:
            source = str(src)
        meta = {"tenant": tenant, "created_at": _utc_now_iso(), "source": source}
        _atomic_write_json(today_dir / "_snapshot.json", meta)
        return today_dir
