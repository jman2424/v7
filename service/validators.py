"""
Input validators and normalizers.

Responsibilities:
- Postcode normalize/validate (UK-ish; supports outward-only prefixes)
- Phone validation (basic E.164)
- SKU sanity checks
- Generic text sanitation (strip controls, collapse whitespace)
- JSON schema validation wrappers

Connects:
- routes/files_routes.py (schema checks)
- services/router.py (entity normalization helpers)
- retrieval/storage.py (pre-save validation)
"""

from __future__ import annotations
import json
import os
import re
from typing import Any, Dict, Tuple, Optional

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover
    jsonschema = None  # type: ignore

# --- Regexes ---
_POSTCODE_FULL = re.compile(r"^\s*([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\s*$", re.I)
_POSTCODE_OUTWARD = re.compile(r"^\s*([A-Z]{1,2}\d{1,2}[A-Z]?)\s*$", re.I)
_PHONE = re.compile(r"^\+?\d{7,15}$")
_SKU = re.compile(r"^[A-Z0-9_]{4,64}$")
_WHITESPACE = re.compile(r"\s+")


def sanitize_text(s: str, *, max_len: int = 2000) -> str:
    s = (s or "").replace("\x00", "")
    s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", s)
    s = _WHITESPACE.sub(" ", s).strip()
    return s[:max_len]


# --- Postcode ---

def normalize_postcode(s: str) -> Optional[str]:
    """
    Returns normalized UK postcode (with space) or outward prefix.
    """
    if not s:
        return None
    s = s.strip().upper()
    m = _POSTCODE_FULL.match(s)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m2 = _POSTCODE_OUTWARD.match(s)
    if m2:
        return m2.group(1)
    return None


def is_valid_postcode(s: str) -> bool:
    return normalize_postcode(s) is not None


# --- Phone ---

def is_valid_phone(s: str) -> bool:
    return bool(_PHONE.match(s or ""))


# --- SKU ---

def is_valid_sku(s: str) -> bool:
    return bool(_SKU.match((s or "").upper()))


# --- Schema validation ---

class SchemaError(Exception):
    pass


def _load_schema(schema_path: str) -> Dict[str, Any]:
    if not os.path.exists(schema_path):
        raise SchemaError(f"Schema not found: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        try:
            if schema_path.endswith(".yaml") or schema_path.endswith(".yml"):
                import yaml  # lazy import
                return yaml.safe_load(f)
            return json.load(f)
        except Exception as e:  # pragma: no cover
            raise SchemaError(f"Invalid schema file: {e}") from e


def validate_json(data: Any, *, schema_path: str) -> Tuple[bool, Optional[str]]:
    """
    Returns (ok, error_message). If jsonschema unavailable, performs only a shape sanity check.
    """
    try:
        schema = _load_schema(schema_path)
    except SchemaError as e:
        return False, str(e)

    if jsonschema is None:
        # Fallback: basic type check
        if not isinstance(data, (dict, list)):
            return False, "Data must be object or array"
        return True, None

    try:
        jsonschema.validate(instance=data, schema=schema)  # type: ignore
        return True, None
    except Exception as e:
        return False, str(e)


# --- File safety ---

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


def safe_filename(name: str) -> Optional[str]:
    name = (name or "").strip()
    return name if _SAFE_NAME.match(name) else None
