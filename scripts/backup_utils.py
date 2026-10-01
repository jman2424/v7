"""Portable, contained file handling for operator-only backup commands."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path, PurePosixPath

MAX_FILES = 20_000
MAX_BYTES = 512 * 1024 * 1024


def require_sqlite_files() -> None:
    if os.getenv("V7_STORAGE_BACKEND", "sqlite").strip().lower() != "sqlite":
        raise ValueError("This file backup tool supports SQLite only; use a verified PostgreSQL backup for PostgreSQL storage")


def checked_path(path: Path) -> Path:
    """Do not follow directory aliases when reading or replacing operator files."""
    path = path.absolute()
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
            raise ValueError("Symlinks and junctions are not supported by backups")
    return path


def tenant_path(business: Path, tenant: str) -> Path:
    if not isinstance(tenant, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", tenant) or tenant.lower() == "versions":
        raise ValueError("Invalid tenant")
    root = checked_path(business)
    path = root / tenant
    checked_path(path)
    if path.resolve().parent != root.resolve():
        raise ValueError("Tenant directory escapes business root")
    if root.is_dir() and any(p.name.casefold() == tenant.casefold() and p.name != tenant for p in root.iterdir()):
        raise ValueError("Ambiguous tenant directory")
    return path


def contained_path(root: Path, relative: str) -> Path:
    root = checked_path(root)
    if not isinstance(relative, str):
        raise ValueError("Unsafe backup path")
    parts = PurePosixPath(relative).parts
    if (not parts or relative.startswith("/") or "\\" in relative
            or re.search(r'[<>:"|?*\x00-\x1f]', relative)
            or any(p in {"", ".", ".."} or p.endswith((".", " "))
                   or re.fullmatch(r"(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
                   for p in relative.split("/"))):
        raise ValueError("Unsafe backup path")
    target = root.joinpath(*parts)
    checked_path(target)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Backup path escapes destination")
    return target


def files_under(root: Path) -> list[Path]:
    root = checked_path(root)
    if not root.is_dir():
        raise ValueError("Backup source must be a real directory")
    files = []
    size = 0
    names = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        contained_path(root, relative)
        if relative.casefold() in names:
            raise ValueError("Ambiguous backup path")
        names.add(relative.casefold())
        if path.is_file():
            files.append(path)
            size += path.stat().st_size
            if len(files) > MAX_FILES or size > MAX_BYTES:
                raise ValueError("Backup exceeds configured size limit")
    return files


def atomic_write(path: Path, data: bytes) -> None:
    path = checked_path(path)
    if path.exists() and not path.is_file():
        raise ValueError("Restore target must be a regular file")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
