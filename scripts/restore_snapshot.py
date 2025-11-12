#!/usr/bin/env python3
"""
Restore a snapshot to business/<TENANT>/ with dry-run diff.

Usage:
  python scripts/restore_snapshot.py --tenant EXAMPLE --snapshot backups/2025-11-09/EXAMPLE.tar.gz [--apply]

Behavior:
- Lists added/changed/removed files vs current business/<TENANT>/*
- If --apply is provided, overwrites current files with snapshot contents
- Writes an audit entry per file changed (if services/audit.py is available)
"""

from __future__ import annotations
import argparse
import difflib
import io
import json
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, List

ROOT = Path(__file__).resolve().parents[1]
BUSINESS_DIR = ROOT / "business"

# Optional Audit hook
try:
    from services.audit import AuditService  # type: ignore
except Exception:
    class AuditService:  # lightweight stub
        def __init__(self, log_path: str = "logs/selfrepair.log"): self.log_path = log_path
        def record(self, **kwargs): pass

@dataclass
class DiffReport:
    added: List[str]
    removed: List[str]
    changed: List[str]

def read_tar_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    f = tar.extractfile(member)
    return f.read() if f else b""

def snapshot_map(snapshot_path: Path, tenant: str) -> Dict[str, bytes]:
    base_prefix = f"business/{tenant}/"
    out: Dict[str, bytes] = {}
    with tarfile.open(snapshot_path, "r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile(): 
                continue
            if not m.name.startswith(base_prefix):
                continue
            rel = m.name[len("business/"):]  # keep <TENANT>/...
            out[rel] = read_tar_bytes(tar, m)
    return out

def current_map(tenant: str) -> Dict[str, bytes]:
    base = BUSINESS_DIR / tenant
    out: Dict[str, bytes] = {}
    for p in base.glob("**/*"):
        if p.is_file():
            rel = str(p.relative_to(BUSINESS_DIR))
            out[rel] = p.read_bytes()
    return out

def compute_diff(curr: Dict[str, bytes], snap: Dict[str, bytes]) -> DiffReport:
    a = set(curr.keys()); b = set(snap.keys())
    added = sorted(b - a)
    removed = sorted(a - b)
    changed = sorted([k for k in (a & b) if curr[k] != snap[k]])
    return DiffReport(added, removed, changed)

def pretty_diff(old: bytes, new: bytes) -> str:
    try:
        old_s = old.decode("utf-8", "replace").splitlines()
        new_s = new.decode("utf-8", "replace").splitlines()
        return "\n".join(difflib.unified_diff(old_s, new_s, lineterm=""))
    except Exception:
        return "(binary diff omitted)"

def apply_changes(tenant: str, snap: Dict[str, bytes], report: DiffReport, audit: AuditService, actor="restore_snapshot"):
    base = BUSINESS_DIR / tenant
    base.mkdir(parents=True, exist_ok=True)

    for rel in report.added + report.changed:
        dst = base / rel[len(f"{tenant}/"):]
        dst.parent.mkdir(parents=True, exist_ok=True)
        before = None
        if dst.exists():
            try: before = json.loads(dst.read_text("utf-8"))
            except Exception: before = None
        dst.write_bytes(snap[rel])
        after = None
        try: after = json.loads(snap[rel].decode("utf-8"))
        except Exception: pass
        audit.record(user="system", role="admin", ip="127.0.0.1",
                     action="restore_write", target=str(dst),
                     before=before, after=after)

    for rel in report.removed:
        dst = base / rel[len(f"{tenant}/"):]
        if dst.exists():
            try:
                before = json.loads(dst.read_text("utf-8"))
            except Exception:
                before = None
            dst.unlink()
            audit.record(user="system", role="admin", ip="127.0.0.1",
                         action="restore_delete", target=str(dst),
                         before=before, after=None)

def main():
    ap = argparse.ArgumentParser(description="Restore snapshot (with dry-run diff).")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--snapshot", required=True, help="Path to <DATE>/<TENANT>.tar.gz")
    ap.add_argument("--apply", action="store_true", help="Apply changes")
    args = ap.parse_args()

    tenant = args.tenant
    snap_path = Path(args.snapshot)
    if not snap_path.exists():
        raise SystemExit(f"[ERR] Snapshot not found: {snap_path}")

    snap = snapshot_map(snap_path, tenant)
    curr = current_map(tenant)
    rep = compute_diff(curr, snap)

    print(f"[DRY-RUN] Diff for tenant={tenant}")
    print(f"  Added  : {len(rep.added)}")
    print(f"  Removed: {len(rep.removed)}")
    print(f"  Changed: {len(rep.changed)}")

    # Show a short preview for first few changed files
    for rel in rep.changed[:5]:
        print(f"\n--- {rel} ---")
        print(pretty_diff(curr[rel], snap[rel])[:2000])

    if not args.apply:
        print("\n[INFO] Use --apply to perform the restoration.")
        return

    audit = AuditService()
    apply_changes(tenant, snap, rep, audit)
    print("[OK] Restoration completed.")

if __name__ == "__main__":
    main()
