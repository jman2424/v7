"""Back up SQLite, tenant files and accounts; restore only while service is stopped.

Run as the service operator with the same environment as the application. Output
contains private data: use a protected, encrypted backup filesystem.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.backup_utils import atomic_write, checked_path, contained_path, files_under, require_sqlite_files


def _configured_path(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).absolute()


def database_paths(root: Path) -> dict[str, Path]:
    return {
        "analytics.db": _configured_path(root, os.environ.get("ANALYTICS_DB_PATH") or root / "logs/analytics.db"),
        "security.db": _configured_path(root, os.environ.get("SECURITY_DB_PATH") or root / "logs/security.db"),
    }


def business_path(root: Path) -> Path:
    data_root = _configured_path(root, os.environ.get("V7_DATA_DIR") or root)
    return _configured_path(root, os.environ.get("BUSINESS_DATA_ROOT") or data_root / "business")


def private_paths(root: Path) -> dict[str, Path]:
    data_root = _configured_path(root, os.environ.get("V7_DATA_DIR") or root)
    return {
        "private/crm_snapshot.json": _configured_path(root, os.environ.get("CRM_SNAPSHOT_PATH") or data_root / "logs/crm_snapshot.json"),
        "private/audit.jsonl": _configured_path(root, os.environ.get("AUDIT_LOG_PATH") or data_root / "logs/selfrepair.log"),
    }


def sqlite_copy(source: Path, destination: Path) -> None:
    source = checked_path(source)
    destination = checked_path(destination)
    if not source.is_file():
        raise ValueError("Required SQLite database is missing or is a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    incoming = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    outgoing = sqlite3.connect(destination)
    try:
        incoming.backup(outgoing)
        outgoing.execute("PRAGMA journal_mode=DELETE")
        if outgoing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite backup integrity check failed")
    finally:
        incoming.close()
        outgoing.close()
    os.chmod(destination, 0o600)


def create_backup(root: Path, output: Path) -> Path:
    require_sqlite_files()
    root, output = checked_path(root), checked_path(output)
    business = checked_path(business_path(root))
    if output.is_relative_to(business):
        raise ValueError("Backups must be outside business data")
    files = files_under(business)
    if not files:
        raise ValueError("Business data is empty")
    databases = database_paths(root)
    if any(not path.is_file() for path in databases.values()):
        raise ValueError("Both analytics and security databases are required")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for file in files:
        # The lock database is operational coordination, never restored.
        if file.name.startswith(".write-lock.sqlite3"):
            continue
        destination = contained_path(output, "business/" + file.relative_to(business).as_posix())
        atomic_write(destination, file.read_bytes())
    for name, source in databases.items():
        sqlite_copy(source, output / "databases" / name)
    for name, source in private_paths(root).items():
        source = checked_path(source)
        if source.exists():
            if not source.is_file():
                raise ValueError("Private state backup source must be a regular file")
            atomic_write(output / name, source.read_bytes())
    registry = os.getenv("ADMIN_USERS_FILE", "").strip()
    if registry:
        account_file = checked_path(_configured_path(root, registry))
        if not account_file.is_file():
            raise ValueError("Account registry must be a regular file")
        atomic_write(output / "accounts.json", account_file.read_bytes())
    checksums = {file.relative_to(output).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
                 for file in files_under(output)}
    manifest = {"format": 1, "created": datetime.now(timezone.utc).isoformat(), "files": checksums}
    # Write manifest last; its absence marks an incomplete backup.
    atomic_write(output / "manifest.json", json.dumps(manifest, indent=2).encode())
    return output


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate backup manifest field")
        result[key] = value
    return result


def verify_backup(snapshot: Path) -> dict[str, bytes]:
    snapshot = checked_path(snapshot)
    files = files_under(snapshot)
    manifest = json.loads((snapshot / "manifest.json").read_text("utf-8"), object_pairs_hook=_unique_fields)
    if not isinstance(manifest, dict) or set(manifest) != {"format", "created", "files"}:
        raise ValueError("Unsupported backup manifest")
    expected = manifest.get("files")
    if (type(manifest.get("format")) is not int or manifest["format"] != 1
            or not isinstance(manifest["created"], str) or not 1 <= len(manifest["created"]) <= 64
            or not isinstance(expected, dict)):
        raise ValueError("Unsupported backup manifest")
    if len({name.casefold() for name in expected}) != len(expected):
        raise ValueError("Ambiguous backup path")
    actual = {p.relative_to(snapshot).as_posix() for p in files} - {"manifest.json"}
    if actual != set(expected) or not {"databases/analytics.db", "databases/security.db"}.issubset(actual):
        raise ValueError("Incomplete backup")
    result = {}
    for name, checksum in expected.items():
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("Invalid backup checksum")
        if (not name.startswith(("business/", "databases/")) and name != "accounts.json"
                and name not in {"private/crm_snapshot.json", "private/audit.jsonl"}):
            raise ValueError("Unknown backup resource")
        if name.startswith("databases/") and name not in {"databases/analytics.db", "databases/security.db"}:
            raise ValueError("Unknown database")
        data = contained_path(snapshot, name).read_bytes()
        if hashlib.sha256(data).hexdigest() != checksum:
            raise ValueError("Backup checksum mismatch")
        result[name] = data
    if not any(name.startswith("business/") for name in result):
        raise ValueError("Backup has no business data")
    return result


def _restore_database(data: bytes, current_security: Path | None = None) -> bytes:
    """Validate verified bytes and revoke restored credentials before replacement."""
    temporary = tempfile.TemporaryDirectory(prefix="v7-restore-")
    path = Path(temporary.name) / "database.sqlite3"
    atomic_write(path, data)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA journal_mode=DELETE")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Snapshot database is corrupt")
        if current_security is not None:
            existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("management_sessions", "mcp_grants", "mfa_challenges", "trusted_devices", "oidc_states"):
                if table in existing:
                    connection.execute(f"DELETE FROM {table}")
            if "registration_requests" in existing:
                connection.execute("UPDATE registration_requests SET password_hash='',code_hash='',status='expired' WHERE status IN ('verification', 'creating')")
            # Do not roll back an authenticator code already used after the backup.
            if current_security.is_file():
                current = sqlite3.connect(current_security.as_uri() + "?mode=ro", uri=True)
                try:
                    current_tables = {row[0] for row in current.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "totp_steps" in current_tables:
                        steps = current.execute("SELECT account_hash, step FROM totp_steps").fetchall()
                        if steps:
                            connection.execute("CREATE TABLE IF NOT EXISTS totp_steps (account_hash TEXT PRIMARY KEY, step INTEGER NOT NULL)")
                            connection.executemany(
                                "INSERT INTO totp_steps VALUES (?, ?) ON CONFLICT(account_hash) DO UPDATE SET step=MAX(totp_steps.step, excluded.step)", steps)
                    if "mfa_code_uses" in current_tables:
                        uses = current.execute("SELECT account,secret_hash,timestep FROM mfa_code_uses").fetchall()
                        if uses:
                            connection.execute("CREATE TABLE IF NOT EXISTS mfa_code_uses (account TEXT NOT NULL, secret_hash TEXT NOT NULL, timestep INTEGER NOT NULL, PRIMARY KEY(account,secret_hash,timestep))")
                            connection.executemany("INSERT INTO mfa_code_uses VALUES (?,?,?) ON CONFLICT(account,secret_hash,timestep) DO NOTHING", uses)
                    # Recovery must not undo account/IP lockouts recorded after the snapshot.
                    if "auth_login_failures" in current_tables:
                        failures = current.execute("SELECT attempt,subject_hash,attempted FROM auth_login_failures").fetchall()
                        if failures:
                            connection.execute("CREATE TABLE IF NOT EXISTS auth_login_failures (attempt TEXT PRIMARY KEY, subject_hash TEXT NOT NULL, attempted REAL NOT NULL)")
                            connection.executemany(
                                "INSERT INTO auth_login_failures VALUES (?,?,?) ON CONFLICT(attempt) DO UPDATE SET subject_hash=excluded.subject_hash, attempted=MAX(auth_login_failures.attempted, excluded.attempted)", failures)
                except sqlite3.DatabaseError as error:
                    raise ValueError("Current security database replay state cannot be read; preserve it and restore to a clean database target") from error
                finally:
                    current.close()
            connection.commit()
        return connection.serialize()
    except sqlite3.DatabaseError as error:
        raise ValueError("Snapshot database is corrupt or incompatible") from error
    finally:
        connection.close()
        temporary.cleanup()


def restore_backup(root: Path, snapshot: Path, *, service_stopped: bool = False) -> None:
    require_sqlite_files()
    if not service_stopped:
        raise ValueError("Stop the application and pass --service-stopped before restoring")
    root = checked_path(root)
    data = verify_backup(snapshot)
    databases = database_paths(root)
    targets = {}
    for name in data:
        if name.startswith("business/"):
            targets[name] = contained_path(business_path(root), name.removeprefix("business/"))
        elif name.startswith("databases/"):
            targets[name] = databases[name.removeprefix("databases/")]
        elif name in private_paths(root):
            targets[name] = private_paths(root)[name]
        else:
            registry = os.getenv("ADMIN_USERS_FILE", "").strip()
            if not registry:
                raise ValueError("Set ADMIN_USERS_FILE before restoring the account registry")
            targets[name] = _configured_path(root, registry)
        targets[name] = checked_path(targets[name])
        if targets[name].exists() and not targets[name].is_file():
            raise ValueError("Restore target must be a regular file")
    if len({str(path).casefold() for path in targets.values()}) != len(targets):
        raise ValueError("Restore targets must be distinct")
    for path in databases.values():
        for suffix in ("-wal", "-shm"):
            sidecar = checked_path(Path(str(path) + suffix))
            if sidecar.exists() and not sidecar.is_file():
                raise ValueError("SQLite sidecar must be a regular file")
    # Validate checksummed bytes and clear credentials before any live changes.
    for name in databases:
        key = "databases/" + name
        data[key] = _restore_database(data[key], databases[name] if name == "security.db" else None)
    for name, target in targets.items():
        atomic_write(target, data[name])
        if name.startswith("databases/"):
            # Remove previous WAL before a later file failure can interrupt recovery.
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(target) + suffix)
                if sidecar.exists():
                    sidecar.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify", "restore"))
    parser.add_argument("snapshot", type=Path, help="New directory for create, existing backup for verify/restore")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--service-stopped", action="store_true")
    args = parser.parse_args()
    if args.action == "create":
        create_backup(args.root, args.snapshot)
    elif args.action == "verify":
        verify_backup(args.snapshot)
    else:
        restore_backup(args.root, args.snapshot, service_stopped=args.service_stopped)
    print(f"[OK] Backup {args.action} completed")


if __name__ == "__main__":
    main()
