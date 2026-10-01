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
import tempfile
from pathlib import Path
from typing import List

try:
    from scripts.snapshot_paths import configured_business_root, reject_links, target_path, tenant_base
    from scripts.prepare_supabase import _protect_directory
except ModuleNotFoundError:
    from snapshot_paths import configured_business_root, reject_links, target_path, tenant_base
    from prepare_supabase import _protect_directory

ROOT = Path(__file__).resolve().parents[1]
BUSINESS_DIR = configured_business_root(ROOT)

def gather_files(tenant: str) -> List[Path]:
    base = tenant_base(BUSINESS_DIR, tenant)
    if not base.exists():
        raise SystemExit(f"[ERR] Tenant folder not found: {base}")
    files = []
    for path in base.glob("**/*"):
        reject_links(path)
        if path.is_file():
            target_path(base, path.relative_to(base.parent).as_posix(), tenant)
            files.append(path)
    return files

def make_snapshot(tenant: str, out_dir: Path, date_str: str) -> Path:
    if dt.date.fromisoformat(date_str).isoformat() != date_str:
        raise ValueError("Snapshot date must use YYYY-MM-DD")
    files = gather_files(tenant)
    if not files:
        raise SystemExit(f"[ERR] No files to snapshot for tenant {tenant}")
    reject_links(out_dir)
    day_dir = out_dir / date_str
    reject_links(day_dir)
    day_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    out_path = day_dir / f"{tenant}.tar.gz"
    reject_links(out_path)
    # Snapshot archives contain account hashes and may contain MFA/API secrets.
    # Build inside a new private directory, then publish the completed inode
    # without replacing an existing archive or inheriting a shared folder ACL.
    with tempfile.TemporaryDirectory(prefix=".v7-snapshot-", dir=day_dir) as temporary:
        staging = Path(temporary)
        _protect_directory(staging)
        staged = staging / "archive.tar.gz"
        with staged.open("xb") as target:
            if os.name != "nt":
                os.fchmod(target.fileno(), 0o600)
            with tarfile.open(fileobj=target, mode="w:gz") as tar:
                for f in files:
                    arcname = "business/" + f.relative_to(BUSINESS_DIR).as_posix()
                    tar.add(f, arcname=arcname, recursive=False)
            target.flush()
            os.fsync(target.fileno())
        os.link(staged, out_path)
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
    try:
        main()
    except (ValueError, OSError, tarfile.TarError) as exc:
        raise SystemExit(f"Snapshot backup stopped ({type(exc).__name__}); no document contents were logged.") from None
