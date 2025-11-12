#!/usr/bin/env python3
"""
Validate a tenant catalog against JSON Schema and business rules.

Usage:
  python scripts/validate_catalog.py --tenant EXAMPLE \
    [--schema schemas/catalog.schema.json] [--min-price 0.1] [--max-price 999.0]

Exits non-zero on validation failure.
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple, Any

ROOT = Path(__file__).resolve().parents[1]
BUSINESS = ROOT / "business"
DEFAULT_SCHEMA = ROOT / "schemas" / "catalog.schema.json"

# Optional jsonschema
try:
    import jsonschema  # type: ignore
except Exception:
    jsonschema = None  # type: ignore

def load_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def validate_schema(data: Any, schema_path: Path) -> List[str]:
    if jsonschema is None:
        # soft check
        if not isinstance(data, dict) or "categories" not in data:
            return ["Schema module unavailable and data missing 'categories'"]
        return []
    schema = load_json(schema_path)
    try:
        jsonschema.validate(instance=data, schema=schema)  # type: ignore
        return []
    except Exception as e:
        return [str(e)]

def scan_business_rules(catalog: Dict[str, Any], min_price: float, max_price: float) -> List[str]:
    errs: List[str] = []
    seen = set()
    cats = catalog.get("categories") or []
    if not cats:
        errs.append("No categories in catalog")
        return errs

    for c in cats:
        items = c.get("items") or []
        if not items:
            errs.append(f"Empty category: {c.get('id') or c.get('name')}")
        for it in items:
            sku = (it.get("sku") or "").strip()
            name = (it.get("name") or "").strip()
            price = it.get("price")
            if not sku:
                errs.append(f"Item missing SKU in category {c.get('id') or c.get('name')}: {name}")
            elif sku in seen:
                errs.append(f"Duplicate SKU: {sku}")
            else:
                seen.add(sku)
            try:
                p = float(price)
                if p < min_price or p > max_price:
                    errs.append(f"Unreasonable price for {sku}: {p}")
            except Exception:
                errs.append(f"Invalid price for {sku}: {price}")
    return errs

def main():
    ap = argparse.ArgumentParser(description="Validate tenant catalog")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    ap.add_argument("--min-price", type=float, default=0.1)
    ap.add_argument("--max-price", type=float, default=999.0)
    args = ap.parse_args()

    cat_path = BUSINESS / args.tenant / "catalog.json"
    if not cat_path.exists():
        raise SystemExit(f"[ERR] Catalog not found: {cat_path}")

    data = load_json(cat_path)
    schema_errs = validate_schema(data, Path(args.schema))
    rule_errs = scan_business_rules(data, args.min_price, args.max_price)
    all_errs = schema_errs + rule_errs

    if all_errs:
        print("[FAIL] Catalog validation errors:")
        for e in all_errs:
            print(" -", e)
        raise SystemExit(1)
    print("[OK] Catalog is valid.")

if __name__ == "__main__":
    main()
