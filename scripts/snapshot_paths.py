"""Path boundaries shared by the offline, single-tenant snapshot tools."""
from pathlib import Path
import os
import re

try:
    from scripts.backup_utils import is_linked_path
except ModuleNotFoundError:
    from backup_utils import is_linked_path

_TENANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}


def validate_tenant(tenant: str) -> str:
    if not isinstance(tenant, str) or not _TENANT.fullmatch(tenant) or tenant.lower() == "versions":
        raise ValueError("Invalid snapshot tenant")
    return tenant


def reject_links(path: Path) -> None:
    absolute = path.absolute()
    if any(is_linked_path(part)
           for part in [absolute, *absolute.parents]):
        raise ValueError("Linked snapshot paths require review")


def tenant_base(business_root: Path, tenant: str) -> Path:
    if os.getenv("V7_STORAGE_BACKEND", "sqlite").strip().lower() != "sqlite":
        raise ValueError("Filesystem snapshot tools require the SQLite runtime")
    validate_tenant(tenant)
    reject_links(business_root)
    root = business_root.resolve()
    if root.exists():
        if not root.is_dir():
            raise ValueError("Invalid business directory")
        if any(child.name.casefold() == tenant.casefold() and child.name != tenant
               for child in root.iterdir()):
            raise ValueError("Case-ambiguous snapshot tenant")
    base = root / tenant
    reject_links(base)
    if base.exists() and not base.is_dir():
        raise ValueError("Invalid tenant directory")
    return base


def configured_business_root(repo_root: Path) -> Path:
    data_root = os.getenv("V7_DATA_DIR", "").strip()
    # Keep link/junction ancestors visible until tenant_base validates them.
    return Path(data_root).expanduser().absolute() / "business" if data_root else repo_root / "business"


def target_path(base: Path, relative: str, tenant: str) -> Path:
    validate_tenant(tenant)
    if (not isinstance(relative, str) or len(relative) > 2048
            or not relative.startswith(tenant + "/") or "\\" in relative):
        raise ValueError("Invalid snapshot member path")
    parts = relative[len(tenant) + 1:].split("/")
    for part in parts:
        if (not part or part in {".", ".."} or part.endswith((".", " "))
                or any(ord(char) < 32 or char in ':<>"|?*' for char in part)
                or part.split(".", 1)[0].upper() in _DEVICES):
            raise ValueError("Invalid snapshot member path")
    target = base.joinpath(*parts)
    reject_links(target)
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError("Snapshot target escapes tenant directory")
    return target
