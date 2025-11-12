#!/usr/bin/env python3
"""
Create a versioned tar.gz snapshot of a tenant's business data.

Usage:
  python scripts/snapshot_backup.py --tenant EXAMPLE [--out-dir backups] [--date 2025-11-09]

Notes:
- Only captures files under business/<TENANT>/ (JSONs, branding, etc.)
- Output path: <out-dir>/<YYYY-MM-DD>/<TENANT>.tar.gz
"""

from __future__ import annotations
import argparse
import datetime as dt
import os
import tarfile
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
BUSINESS_DIR = ROOT / "business"

def gather_files(tenant: str) -> List[Path]:
    base = BUSINESS_DIR / tenant
    if not base.exists():
        raise SystemExit(f"[ERR] Tenant folder not found: {base}")
    return [p for p in base.glob("**/*") if p.is_file()]

def make_snapshot(tenant: str, out_dir: Path, date_str: str) -> Path:
    day_dir = out_dir / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / f"{tenant}.tar.gz"

    files = gather_files(tenant)
    if not files:
        raise SystemExit(f"[ERR] No files to snapshot for tenant {tenant}")

    with tarfile.open(out_path, "w:gz") as tar:
        for f in files:
            arcname = f.relative_to(ROOT)
            tar.add(f, arcname=str(arcname))
    return out_path

def main():
    ap = argparse.ArgumentParser(description="Create business data snapshot (tar.gz)")
    ap.add_argument("--tenant", required=True, help="Tenant key, e.g., EXAMPLE")
    ap.add_argument("--out-dir", default="backups", help="Destination dir (default: backups/)")
    ap.add_argument("--date", default=None, help="Override date (YYYY-MM-DD). Default: today.")
    args = ap.parse_args()

    date_str = args.date or dt.date.today().isoformat()
    out = make_snapshot(args.tenant, Path(args.out_dir), date_str)
    print(f"[OK] Snapshot created: {out}")

if __name__ == "__main__":
    main()
