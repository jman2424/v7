"""Export a frozen, filesystem-accessible SQLite runtime without modifying it.

This cannot access a Render Free instance or recover files from a previous
instance. Run it only where the actual source files are accessible. See
docs/LIVE_BACKUP.md. No provider connection or application import is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.prepare_supabase import prepare, strict_json, _protect_directory
except ModuleNotFoundError:
    from prepare_supabase import prepare, strict_json, _protect_directory


_COORDINATION = {
    '.write-lock.sqlite3', '.write-lock.sqlite3-journal',
    '.write-lock.sqlite3-wal', '.write-lock.sqlite3-shm',
}
_FORMAT = 'v7-runtime-backup-v1'


@dataclass(frozen=True)
class Sources:
    business: Path
    security: Path
    analytics: Path
    crm: Path | None
    audit: Path | None
    accounts: Path | None = None


def _safe_path(path: Path, *, directory: bool = False) -> Path:
    # Check before resolving: resolution must never hide a link/junction.
    absolute = path.absolute()
    for part in [absolute, *absolute.parents]:
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('Linked source or destination paths require review')
    resolved = absolute.resolve(strict=True)
    if directory and not resolved.is_dir():
        raise ValueError('Required source directory is missing')
    if not directory and not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError('Required source must be a regular file')
    return resolved


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(256 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path, *, ignore_coordination: bool = False) -> dict[str, Path]:
    result = {}
    for path in sorted(root.rglob('*')):
        if ignore_coordination and path.parent == root and path.name in _COORDINATION:
            _safe_path(path)
            continue
        if path.is_dir() and not path.is_symlink():
            _safe_path(path, directory=True)
            continue
        result[path.relative_to(root).as_posix()] = _safe_path(path)
    return result


def _source_state(sources: Sources) -> dict[str, str]:
    state = {'business/' + name: _checksum(path)
             for name, path in _inventory(sources.business, ignore_coordination=True).items()}
    for path in sorted(sources.business.rglob('*')):
        if path.is_dir():
            _safe_path(path, directory=True)
            state['directory/' + path.relative_to(sources.business).as_posix()] = ''
    for name, path in [('security', sources.security), ('analytics', sources.analytics),
                       ('crm', sources.crm), ('audit', sources.audit), ('accounts', sources.accounts)]:
        if path is None:
            continue
        state[name] = _checksum(_safe_path(path))
        if name in {'security', 'analytics'}:
            for suffix in ('-wal', '-shm', '-journal'):
                sidecar = Path(str(path) + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    state[name + suffix] = _checksum(_safe_path(sidecar))
    return state


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        if os.name != 'nt':
            os.fchmod(outgoing.fileno(), 0o600)
        shutil.copyfileobj(incoming, outgoing, length=256 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if _checksum(source) != _checksum(destination):
        raise ValueError('Copied file verification failed')


def _copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with destination.open('xb') as handle:
        if os.name != 'nt':
            os.fchmod(handle.fileno(), 0o600)
    # SQLite immutable reads ignore WAL. Even a read-only WAL connection may
    # create/write a shared-memory sidecar. Copy the frozen database + journals
    # into the protected destination first, and run the online backup API on
    # that disposable copy. Never open the original database with SQLite.
    with tempfile.TemporaryDirectory(prefix='.sqlite-source-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'source.db'
        _copy_file(source, staged)
        for suffix in ('-wal', '-journal'):
            sidecar = Path(str(source) + suffix)
            if sidecar.exists():
                _copy_file(_safe_path(sidecar), Path(str(staged) + suffix))
        with closing(sqlite3.connect(staged)) as incoming:
            with closing(sqlite3.connect(destination)) as outgoing:
                incoming.backup(outgoing)
                outgoing.execute('PRAGMA journal_mode=DELETE')
                if outgoing.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Exported SQLite integrity check failed')


def verify_export(destination: Path) -> dict:
    """Verify exact file inventory, checksums and the migration's source layout."""
    destination = _safe_path(destination, directory=True)
    manifest_path = _safe_path(destination / 'manifest.json')
    manifest = strict_json(manifest_path.read_text(encoding='utf-8'))
    if (not isinstance(manifest, dict) or manifest.get('format') != _FORMAT
            or manifest.get('source_frozen') is not True
            or type(manifest.get('accounts_included')) is not bool
            or not isinstance(manifest.get('files'), dict)
            or not isinstance(manifest.get('directories'), list)):
        raise ValueError('Invalid backup manifest')
    files = _inventory(destination)
    files.pop('manifest.json')
    if set(files) != set(manifest['files']):
        raise ValueError('Backup inventory does not match manifest')
    directories = sorted(path.relative_to(destination).as_posix()
                         for path in destination.rglob('*') if path.is_dir())
    if directories != manifest['directories']:
        raise ValueError('Backup directory inventory does not match manifest')
    for flag, name in [('accounts_included', 'accounts.json'),
                       ('crm_included', 'logs/crm_snapshot.json'), ('audit_included', 'logs/selfrepair.log')]:
        if type(manifest.get(flag)) is not bool or manifest[flag] != (name in files):
            raise ValueError('Backup optional-file inventory does not match manifest')
    for name, path in files.items():
        expected = manifest['files'][name]
        if (not isinstance(expected, dict) or expected.get('size') != path.stat().st_size
                or expected.get('sha256') != _checksum(path)):
            raise ValueError('Backup checksum verification failed')
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            raise ValueError('Backup file permissions are too broad')
    if os.name != 'nt' and destination.stat().st_mode & 0o077:
        raise ValueError('Backup directory permissions are too broad')
    accounts = destination / 'accounts.json' if manifest['accounts_included'] else None
    bundle = prepare(destination, accounts=accounts)
    if (bundle.counts() != manifest.get('migration_counts')
            or bundle.skipped != manifest.get('migration_skipped')
            or bundle.reconciled != manifest.get('migration_reconciled')):
        raise ValueError('Backup migration inventory verification failed')
    return {'complete': True, 'files': len(files), 'counts': bundle.counts(),
            'migration_skipped': bundle.skipped, 'migration_reconciled': bundle.reconciled}


def export_runtime(sources: Sources, destination: Path, *, source_frozen: bool = False) -> dict:
    if not source_frozen:
        raise ValueError('Stop all writers and explicitly confirm source_frozen')
    if os.getenv('V7_STORAGE_BACKEND', 'sqlite').strip().lower() != 'sqlite':
        raise ValueError('This exporter requires the SQLite runtime')
    if sources.accounts is None and os.getenv('ADMIN_USERS_FILE', '').strip():
        raise ValueError('Configured account registry must be included')
    if sources.crm is None and os.getenv('CRM_SNAPSHOT_PATH', '').strip():
        raise ValueError('Configured CRM snapshot must be included')
    sources = Sources(
        _safe_path(sources.business, directory=True), _safe_path(sources.security),
        _safe_path(sources.analytics),
        _safe_path(sources.crm) if sources.crm is not None else None,
        _safe_path(sources.audit) if sources.audit is not None else None,
        _safe_path(sources.accounts) if sources.accounts is not None else None,
    )
    destination = destination.absolute()
    parent = _safe_path(destination.parent, directory=True)
    destination = parent / destination.name
    if destination.exists() or destination.is_symlink():
        raise ValueError('Backup destination must not already exist')
    source_paths = [sources.business, sources.security, sources.analytics,
                    sources.crm, sources.audit, sources.accounts]
    for path in filter(None, source_paths):
        if path == destination or path.is_relative_to(destination) or destination.is_relative_to(path):
            raise ValueError('Backup destination must not overlap sources')
    before = _source_state(sources)
    destination.mkdir(mode=0o700)
    created = destination.stat()
    try:
        _protect_directory(destination)
        business = destination / 'business'
        business.mkdir(mode=0o700)
        # Preserve even empty directories; the importer will reject unexpected
        # directories/files rather than silently omitting them.
        for path in sorted(sources.business.rglob('*')):
            if path.is_dir():
                _safe_path(path, directory=True)
                (business / path.relative_to(sources.business)).mkdir(mode=0o700, parents=True, exist_ok=True)
        for name, path in _inventory(sources.business, ignore_coordination=True).items():
            _copy_file(path, business / name)
        _copy_database(sources.security, destination / 'logs/security.db')
        _copy_database(sources.analytics, destination / 'logs/analytics.db')
        for path, name in [(sources.crm, 'logs/crm_snapshot.json'),
                           (sources.audit, 'logs/selfrepair.log'), (sources.accounts, 'accounts.json')]:
            if path is not None:
                _copy_file(path, destination / name)
        if _source_state(sources) != before:
            raise ValueError('Source changed during export; freeze every writer')
        bundle = prepare(destination, accounts=destination / 'accounts.json' if sources.accounts else None)
        files = _inventory(destination)
        manifest = {
            'format': _FORMAT, 'created_at': datetime.now(timezone.utc).isoformat(),
            'source_frozen': True, 'accounts_included': sources.accounts is not None,
            'crm_included': sources.crm is not None, 'audit_included': sources.audit is not None,
            'migration_counts': bundle.counts(), 'migration_skipped': bundle.skipped,
            'migration_reconciled': bundle.reconciled,
            'directories': sorted(path.relative_to(destination).as_posix()
                                  for path in destination.rglob('*') if path.is_dir()),
            'files': {name: {'size': path.stat().st_size, 'sha256': _checksum(path)}
                      for name, path in files.items()},
        }
        manifest_path = destination / 'manifest.json'
        with manifest_path.open('x', encoding='utf-8') as handle:
            if os.name != 'nt':
                os.fchmod(handle.fileno(), 0o600)
            json.dump(manifest, handle, sort_keys=True, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        result = verify_export(destination)
        if _source_state(sources) != before:
            raise ValueError('Source changed during verification; freeze every writer')
        return result
    except BaseException:
        # Remove only the exact directory created by this invocation, never a
        # pre-existing or substituted directory and never anything in sources.
        if destination.exists() and not destination.is_symlink() and destination.parent.resolve() == parent:
            current = destination.stat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                shutil.rmtree(destination)
        raise


def configured_sources(args) -> Sources:
    root = _safe_path(args.source_dir, directory=True)
    def rooted(value, *, expand_user=False):
        path = Path(value).expanduser() if expand_user else Path(value)
        return path if path.is_absolute() else root / path
    raw_data_root = os.getenv('V7_DATA_DIR', '').strip()
    data_root = rooted(raw_data_root, expand_user=True) if raw_data_root else root
    # Storage expands V7_DATA_DIR; existing CRM/audit defaults do not. Mirror
    # the actual source paths instead of choosing a different file during export.
    file_data_root = rooted(raw_data_root) if raw_data_root else root
    business = args.business_dir or data_root / 'business'
    security = args.security_db or os.getenv('SECURITY_DB_PATH') or root / 'logs/security.db'
    analytics = args.analytics_db or os.getenv('ANALYTICS_DB_PATH') or Path('/app/logs/analytics.db')
    configured_crm = args.crm_snapshot or os.getenv('CRM_SNAPSHOT_PATH', '').strip()
    crm = configured_crm or file_data_root / 'logs/crm_snapshot.json'
    audit = args.audit_log or file_data_root / 'logs/selfrepair.log'
    accounts = args.accounts or os.getenv('ADMIN_USERS_FILE', '').strip()
    if args.no_crm_snapshot:
        if configured_crm or rooted(crm, expand_user=bool(args.crm_snapshot)).exists():
            raise ValueError('Cannot omit a configured or existing CRM snapshot')
        crm = None
    if args.no_audit_log:
        if args.audit_log or rooted(audit, expand_user=bool(args.audit_log)).exists():
            raise ValueError('Cannot omit a configured or existing audit log')
        audit = None
    return Sources(rooted(business, expand_user=bool(args.business_dir)),
                   rooted(security, expand_user=bool(args.security_db)),
                   rooted(analytics, expand_user=bool(args.analytics_db)),
                   rooted(crm, expand_user=bool(args.crm_snapshot)) if crm is not None else None,
                   rooted(audit, expand_user=bool(args.audit_log)) if audit is not None else None,
                   rooted(accounts, expand_user=True) if accounts else None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New directory under an existing protected parent')
    parser.add_argument('--verify-only', action='store_true', help='Verify a previously completed export')
    parser.add_argument('--source-dir', type=Path, default=Path.cwd(), help='Actual runtime working directory')
    parser.add_argument('--business-dir', type=Path)
    parser.add_argument('--security-db', type=Path)
    parser.add_argument('--analytics-db', type=Path)
    parser.add_argument('--crm-snapshot', type=Path)
    parser.add_argument('--audit-log', type=Path)
    parser.add_argument('--accounts', type=Path, help='Configured protected ADMIN_USERS_FILE, if used')
    parser.add_argument('--no-crm-snapshot', action='store_true', help='Confirm the unconfigured default CRM file was never created')
    parser.add_argument('--no-audit-log', action='store_true', help='Confirm the default audit file was never created')
    parser.add_argument('--source-frozen', action='store_true', help='Confirm all application, webhook and other writers are stopped')
    args = parser.parse_args(argv)
    if not args.verify_only and not args.source_frozen:
        parser.error('Export requires --source-frozen after stopping every writer')
    try:
        result = verify_export(args.out) if args.verify_only else export_runtime(
            configured_sources(args), args.out, source_frozen=args.source_frozen)
        print(json.dumps({'mode': 'verified' if args.verify_only else 'exported', **result}, indent=2))
    except Exception as exc:
        # SQLite, JSON and filesystem exceptions may contain private data/paths.
        print('Export stopped (' + type(exc).__name__ + '). Check docs/LIVE_BACKUP.md. '
              'No source records or credentials were logged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
