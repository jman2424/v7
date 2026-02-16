"""
Input validators and normalizers.

Responsibilities:
- Postcode normalize/validate (UK-ish; supports outward-only prefixes)
- Phone validation (basic E.164) + normalization helper
- SKU sanity checks + normalization helper
- Generic text sanitation (strip controls, collapse whitespace)
- JSON schema validation wrappers (JSON/YAML; safe fallback)

Connects:
- routes/files_routes.py (schema checks)
- services/router.py (entity normalization helpers)
- retrieval/storage.py (pre-save validation)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover
    jsonschema = None  # type: ignore

# ---------------------------
# Regexes
# ---------------------------

# Pragmatic UK postcode matcher:
# - accepts "SW1A 1AA" and "SW1A1AA"
# - accepts outward-only like "SW1A"
_POSTCODE_FULL = re.compile(r"^\s*([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\s*$", re.I)
_POSTCODE_OUTWARD = re.compile(r"^\s*([A-Z]{1,2}\d[A-Z\d]?)\s*$", re.I)

# E.164-ish:
# - "+447..." or "447..." or "07..." (UK heuristic in normalizer)
_PHONE_E164 = re.compile(r"^\+?[1-9]\d{7,14}$")

# SKU
_SKU = re.compile(r"^[A-Z0-9_]{4,64}$")

# Whitespace + control chars
_WHITESPACE = re.compile(r"\s+")
_CTRL = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

# File safety allowlist
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


# ---------------------------
# Text sanitation
# ---------------------------

def sanitize_text(s: Any, *, max_len: int = 2000) -> str:
    """
    - converts to str
    - removes NUL/control chars
    - collapses whitespace
    - trims
    - caps length
    """
    if s is None:
        s = ""
    if not isinstance(s, str):
        try:
            s = str(s)
        except Exception:
            s = ""

    s = s.replace("\x00", "")
    s = _CTRL.sub(" ", s)
    s = _WHITESPACE.sub(" ", s).strip()

    if max_len and max_len > 0:
        return s[:max_len]
    return s


# ---------------------------
# Postcode
# ---------------------------

def normalize_postcode(s: Any) -> Optional[str]:
    """
    Returns normalized UK postcode (with space) or outward prefix.

    Accepts:
    - "SW1A 1AA"
    - "SW1A1AA"
    - "sw1a1aa"
    - "SW1A, London"  (takes left side)
    """
    raw = sanitize_text(s, max_len=32).upper()
    if not raw:
        return None

    # tolerate comma-separated inputs
    raw = raw.split(",")[0].strip()

    m = _POSTCODE_FULL.match(raw)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    m2 = _POSTCODE_OUTWARD.match(raw)
    if m2:
        return m2.group(1)

    return None


def is_valid_postcode(s: Any) -> bool:
    return normalize_postcode(s) is not None


# ---------------------------
# Phone
# ---------------------------

def normalize_phone(s: Any, *, default_country_code: str = "44") -> Optional[str]:
    """
    Normalizes phone numbers to E.164-ish.
    - "+447..." stays
    - "447..." -> "+447..."
    - "07..." -> "+44..." (UK heuristic, only if default_country_code == "44")

    Returns None if invalid.
    """
    raw = sanitize_text(s, max_len=64)
    if not raw:
        return None

    # Strip common formatting: spaces, hyphens, parentheses
    raw = re.sub(r"[^\d+]", "", raw)

    if raw.startswith("+"):
        return raw if _PHONE_E164.match(raw) else None

    # UK mobile heuristic: 07xxxxxxxxx => +44 7xxxxxxxxx
    if default_country_code == "44" and raw.startswith("07") and len(raw) >= 10:
        raw = "44" + raw[1:]  # drop leading 0
        raw = "+" + raw
        return raw if _PHONE_E164.match(raw) else None

    # Otherwise assume it's a country-code-leading number
    raw = "+" + raw
    return raw if _PHONE_E164.match(raw) else None


def is_valid_phone(s: Any) -> bool:
    return normalize_phone(s) is not None


# ---------------------------
# SKU
# ---------------------------

def normalize_sku(s: Any) -> Optional[str]:
    sku = sanitize_text(s, max_len=80).upper()
    if not sku:
        return None
    return sku if _SKU.match(sku) else None


def is_valid_sku(s: Any) -> bool:
    return normalize_sku(s) is not None


# ---------------------------
# Schema validation
# ---------------------------

class SchemaError(Exception):
    pass


def _load_schema(schema_path: str) -> Dict[str, Any]:
    if not schema_path:
        raise SchemaError("Schema path is empty")
    if not os.path.exists(schema_path):
        raise SchemaError(f"Schema not found: {schema_path}")

    with open(schema_path, "r", encoding="utf-8") as f:
        try:
            if schema_path.endswith((".yaml", ".yml")):
                try:
                    import yaml  # type: ignore
                except Exception as e:
                    raise SchemaError("Schema is YAML but PyYAML is not installed") from e
                schema = yaml.safe_load(f)
            else:
                schema = json.load(f)
        except SchemaError:
            raise
        except Exception as e:  # pragma: no cover
            raise SchemaError(f"Invalid schema file: {e}") from e

    if not isinstance(schema, dict):
        raise SchemaError("Schema must be an object (dict)")
    return schema


def validate_json(data: Any, *, schema_path: str) -> Tuple[bool, Optional[str]]:
    """
    Returns (ok, error_message).
    If jsonschema unavailable, performs only a basic shape sanity check.
    """
    try:
        schema = _load_schema(schema_path)
    except SchemaError as e:
        return False, str(e)

    if jsonschema is None:
        if not isinstance(data, (dict, list)):
            return False, "Data must be object or array"
        return True, None

    try:
        jsonschema.validate(instance=data, schema=schema)  # type: ignore
        return True, None
    except Exception as e:
        return False, str(e)


# ---------------------------
# File safety
# ---------------------------

def safe_filename(name: Any) -> Optional[str]:
    name = sanitize_text(name, max_len=128)
    return name if _SAFE_NAME.match(name) else None
