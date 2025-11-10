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
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
SCHEMAS_ROOT = REPO_ROOT / "schemas"

# Known tenant files and their schemas (if any)
KNOWN_FILES: Dict[str, Optional[str]] = {
    "catalog.json": "catalog.schema.json",
    "delivery.json": "delivery.schema.json",
    "branches.json": "branches.schema.json",
    "faq.json": "faq.schema.json",
    "synonyms.json": None,
    "overrides.json": None,
    "branding.json": None,
    "store_info.json": None,
}


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _atomic_write_json(path: Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@dataclass(frozen=True)
class Storage:
    tenant_key: str
    business_root: Path = BUSINESS_ROOT
    versions_root: Path = VERSIONS_ROOT
    schemas_root: Path = SCHEMAS_ROOT

    # -------- paths --------

    def tenant_dir(self, tenant: Optional[str] = None) -> Path:
        return self.business_root / (tenant or self.tenant_key)

    def file_path(self, tenant: Optional[str], filename: str) -> Path:
        return self.tenant_dir(tenant) / filename

    def versions_day_dir(self, day: Optional[str] = None, tenant: Optional[str] = None) -> Path:
        date_str = day or datetime.utcnow().strftime("%Y-%m-%d")
        return self.versions_root / date_str / (tenant or self.tenant_key)

    # -------- public API --------

    def read_json(self, tenant: Optional[str], filename: str) -> Any:
        """
        Read a tenant JSON file. Raises FileNotFoundError if missing.
        """
        path = self.file_path(tenant, filename)
        return _read_json(path)

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
        tkey = tenant or self.tenant_key
        # schema may be provided as "schemas/catalog.schema.json" or just "catalog.schema.json"
        if schema:
            schema_path = self._schema_path(schema)
            self._validate_json(data, schema_path)

        dest = self.file_path(tkey, filename)
        _atomic_write_json(dest, data)

        snap_path = ""
        if snapshot:
            snap_dir = self._ensure_daily_snapshot_folder(tkey)
            # ensure identical path structure inside snapshot
            snap_path = str((snap_dir / filename).relative_to(self.versions_root))
            _atomic_write_json(snap_dir / filename, data)

        return snap_path

    def list_versions(self, tenant: Optional[str] = None) -> List[str]:
        """
        Return list of YYYY-MM-DD version folders that contain this tenant.
        """
        tkey = tenant or self.tenant_key
        if not self.versions_root.exists():
            return []
        days: List[str] = []
        for day_dir in sorted(self.versions_root.iterdir()):
            if not day_dir.is_dir():
                continue
            if (day_dir / tkey).exists():
                days.append(day_dir.name)
        return days

    def list_audit_entries(self, tenant: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Read audit log lines from business/{tenant}/audit.log.jsonl if present.
        """
        tkey = tenant or self.tenant_key
        log_path = self.tenant_dir(tkey) / "audit.log.jsonl"
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
            path = self.file_path(tkey, fname)
            if not path.exists():
                results["files"][fname] = {"exists": False, "valid": None, "error": None}
                continue
            data = _read_json(path)
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
        today_dir.mkdir(parents=True, exist_ok=True)
        if src.exists():
            for p in src.iterdir():
                if p.is_file() and p.suffix.lower() == ".json":
                    try:
                        shutil.copy2(p, today_dir / p.name)
                    except Exception:
                        # tolerate partial copies; writes will still snapshot file-by-file
                        pass
        # write a snapshot metadata file
        meta = {"tenant": tenant, "created_at": _utc_now_iso(), "source": str(src.relative_to(REPO_ROOT))}
        _atomic_write_json(today_dir / "_snapshot.json", meta)
        return today_dir
