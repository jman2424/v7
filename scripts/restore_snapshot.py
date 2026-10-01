#!/usr/bin/env python3
"""
Restore a snapshot to business/<TENANT>/ with dry-run diff.

Usage:
  python scripts/restore_snapshot.py --tenant EXAMPLE --snapshot backups/2025-11-09/EXAMPLE.tar.gz [--apply]

Behavior:
- Lists added/changed/removed files vs current business/<TENANT>/*
- If --apply is provided, overwrites current files with snapshot contents
- Writes an audit entry per file changed, without private document contents
"""

from __future__ import annotations
import argparse
import difflib
import gzip
import os
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

try:
    from scripts.snapshot_paths import configured_business_root, reject_links, target_path, tenant_base, validate_tenant
except ModuleNotFoundError:
    from snapshot_paths import configured_business_root, reject_links, target_path, tenant_base, validate_tenant

ROOT = Path(__file__).resolve().parents[1]
BUSINESS_DIR = configured_business_root(ROOT)
MAX_SNAPSHOT_FILES = 2000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024

def _audit_service():
    # Direct script execution needs the trusted repository package path too.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from service.audit import AuditService
    return AuditService()

@dataclass
class DiffReport:
    added: List[str]
    removed: List[str]
    changed: List[str]

def read_tar_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    if member.size < 0 or member.size > MAX_FILE_BYTES:
        raise ValueError("Snapshot file exceeds restore limit")
    f = tar.extractfile(member)
    if f is None:
        raise ValueError("Unreadable snapshot file")
    with f:
        content = f.read(member.size + 1)
    if len(content) != member.size:
        raise ValueError("Incomplete snapshot file")
    return content


class _BoundedArchive:
    def __init__(self, source):
        self.source = source
        self.total = 0

    def read(self, size=-1):
        remaining = MAX_ARCHIVE_BYTES - self.total
        value = self.source.read(min(size, remaining + 1) if size >= 0 else remaining + 1)
        self.total += len(value)
        if self.total > MAX_ARCHIVE_BYTES:
            raise ValueError("Snapshot archive exceeds restore limit")
        return value

def snapshot_map(snapshot_path: Path, tenant: str) -> Dict[str, bytes]:
    base = tenant_base(BUSINESS_DIR, tenant)
    reject_links(snapshot_path)
    if not snapshot_path.is_file() or snapshot_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Invalid or oversized snapshot archive")
    base_prefix = f"business/{tenant}/"
    out: Dict[str, bytes] = {}
    seen = set()
    total = 0
    entries = 0
    with snapshot_path.open("rb") as raw, gzip.GzipFile(fileobj=raw) as compressed:
        reader = _BoundedArchive(compressed)
        with tarfile.open(fileobj=reader, mode="r|") as tar:
            for m in tar:
                entries += 1
                if entries > MAX_SNAPSHOT_FILES:
                    raise ValueError("Snapshot has too many entries")
                if m.isdir() and m.name.rstrip("/") in {"business", f"business/{tenant}"}:
                    continue
                if not m.name.startswith(base_prefix):
                    raise ValueError("Snapshot contains another tenant or an unexpected root")
                rel = m.name[len("business/"):].rstrip("/") if m.isdir() else m.name[len("business/"):]
                target_path(base, rel, tenant)
                if m.isdir():
                    continue
                if not m.isfile():
                    raise ValueError("Snapshot links and special files are forbidden")
                if rel.casefold() in seen:
                    raise ValueError("Duplicate or case-ambiguous snapshot file")
                seen.add(rel.casefold())
                total += m.size
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("Snapshot contents exceed restore limit")
                out[rel] = read_tar_bytes(tar, m)
        # Read through the gzip footer too: a valid tar EOF must not hide a
        # truncated/corrupt compressed stream or an unbounded trailing payload.
        while reader.read(8192):
            pass
    if not out:
        raise ValueError("Snapshot contains no files for the selected tenant")
    return out

def current_map(tenant: str) -> Dict[str, bytes]:
    base = tenant_base(BUSINESS_DIR, tenant)
    out: Dict[str, bytes] = {}
    for p in base.glob("**/*"):
        reject_links(p)
        if p.is_file():
            rel = p.relative_to(base.parent).as_posix()
            target_path(base, rel, tenant)
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

def apply_changes(tenant: str, snap: Dict[str, bytes], report: DiffReport, audit, actor="restore_snapshot"):
    base = tenant_base(BUSINESS_DIR, tenant)
    if not snap:
        raise ValueError("Cannot restore an empty snapshot")
    # Validate the entire archive and every destination before creating/writing
    # any directory or replacing/deleting any current tenant file.
    targets = {rel: target_path(base, rel, tenant) for rel in set(snap) | set(report.added + report.changed + report.removed)}
    for rel in report.added + report.changed:
        if rel not in snap or not isinstance(snap[rel], bytes) or len(snap[rel]) > MAX_FILE_BYTES:
            raise ValueError("Invalid snapshot content")
    if any(path.exists() and not path.is_file() for path in targets.values()):
        raise ValueError("Snapshot destination is not a regular file")
    planned_files = {targets[rel] for rel in snap}
    for path in targets.values():
        for parent in path.parents:
            if parent == base:
                break
            if parent in planned_files or (parent.exists() and not parent.is_dir()):
                raise ValueError("Snapshot contains conflicting file and directory paths")
    audit.record(user=actor, role="admin", ip="127.0.0.1", action="restore_start", target=tenant,
                 extra={"added": len(report.added), "changed": len(report.changed), "removed": len(report.removed)})
    base.mkdir(parents=True, exist_ok=True)

    for rel in report.added + report.changed:
        dst = targets[rel]
        dst.parent.mkdir(parents=True, exist_ok=True)
        before = {"size": dst.stat().st_size} if dst.exists() else None
        descriptor, temporary = tempfile.mkstemp(prefix=".restore-", dir=dst.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(snap[rel])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, dst)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        audit.record(user=actor, role="admin", ip="127.0.0.1",
                     action="restore_write", target=rel,
                     before=before, after={"size": len(snap[rel])})

    for rel in report.removed:
        dst = targets[rel]
        if dst.exists():
            before = {"size": dst.stat().st_size}
            dst.unlink()
            audit.record(user=actor, role="admin", ip="127.0.0.1",
                         action="restore_delete", target=rel,
                         before=before, after=None)

def main():
    ap = argparse.ArgumentParser(description="Restore snapshot (with dry-run diff).")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--snapshot", required=True, help="Path to <DATE>/<TENANT>.tar.gz")
    ap.add_argument("--apply", action="store_true", help="Apply changes")
    args = ap.parse_args()

    tenant = validate_tenant(args.tenant)
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

    # Do not log private document contents, password hashes or MFA/provider keys.
    for rel in rep.changed[:5]:
        print(f"  Changed file: {rel}")

    if not args.apply:
        print("\n[INFO] Use --apply to perform the restoration.")
        return

    audit = _audit_service()
    apply_changes(tenant, snap, rep, audit)
    print("[OK] Restoration completed.")

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, tarfile.TarError, EOFError) as exc:
        raise SystemExit(f"Snapshot restore stopped ({type(exc).__name__}); no document contents were logged.") from None
