"""Inspect or copy a frozen V7 backup into private Supabase tables; never alter sources.

Defaults to an offline dry run. Applying requires --apply --source-frozen and a
server-only V7_SUPABASE_MIGRATION_DSN. See docs/SUPABASE_MIGRATION.md.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path


SECURITY_TABLES = {
    'management_sessions', 'login_attempts', 'account_authenticators', 'mfa_challenges',
    'managed_businesses', 'registration_requests', 'billing_contracts', 'billing_invoices',
    'billing_discounts', 'billing_api_charges', 'billing_references', 'webhook_inbox', 'mcp_grants', 'mcp_rate',
}
ANALYTICS_TABLES = {
    'events', 'leads', 'api_usage', 'recorded_sales', 'inventory_history',
    'usage_exchange_rate', 'sales_action_requests', 'sales_action_attempts',
}
EXTRA_TABLES = {'tenants', 'business_documents', 'document_versions', 'operator_accounts', 'crm_records', 'audit_records'}
DATA_TABLES = SECURITY_TABLES | ANALYTICS_TABLES | EXTRA_TABLES
TRANSIENT_TABLES = {'management_sessions', 'mfa_challenges', 'mcp_grants', 'sales_action_attempts'}
TENANT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
FILENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}')


def tenant_key(value):
    if not isinstance(value, str) or not TENANT.fullmatch(value) or value.lower() == 'versions':
        raise ValueError('Invalid source tenant key')
    return value


def strict_json(text):
    # Reject NaN/Infinity and duplicate object keys rather than silently changing data.
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key in source')
            result[key] = value
        return result
    def invalid_constant(_value):
        raise ValueError('Non-finite JSON value in source')
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Non-finite JSON value in source')
        return number
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant,
                      parse_float=finite_float)


def _reject_linked_source(path):
    absolute = path.absolute()
    if any(part.is_symlink() or getattr(part, 'is_junction', lambda: False)()
           for part in [absolute, *absolute.parents]):
        raise ValueError('Linked source paths require review')


def json_file(path):
    _reject_linked_source(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Source must be a regular file')
    return strict_json(path.read_text(encoding='utf-8-sig'))


def json_lines(path):
    _reject_linked_source(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Source must be a regular file')
    return [strict_json(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False, default=lambda item: item.isoformat() if isinstance(item, (date, datetime)) else str(item))


def digest(rows):
    hashes = sorted(hashlib.sha256(canonical(row).encode()).hexdigest() for row in rows)
    return hashlib.sha256('\n'.join(hashes).encode()).hexdigest()


def _protect_directory(path: Path) -> None:
    if os.name != 'nt':
        path.chmod(0o700)
        return
    # Protect the empty staging/export directory before writing private files.
    identity = subprocess.run(
        ['whoami', '/user', '/fo', 'csv', '/nh'],
        check=True, capture_output=True, text=True,
    )
    sid = next(csv.reader(io.StringIO(identity.stdout)))[1].strip()
    if not sid.startswith('S-1-') or any(char not in 'S0123456789-' for char in sid):
        raise ValueError('Cannot establish protected backup owner')
    subprocess.run(
        ['icacls', str(path), '/inheritance:r', '/grant:r',
         '*' + sid + ':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
        check=True, capture_output=True, text=True,
    )


def _file_digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(256 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def _sqlite_source_state(path):
    state = {}
    for suffix in ('', '-wal', '-shm', '-journal'):
        source = Path(str(path) + suffix)
        if suffix and not source.exists() and not source.is_symlink():
            continue
        if (not source.is_file()
                or any(part.is_symlink() or getattr(part, 'is_junction', lambda: False)()
                       for part in [source.absolute(), *source.absolute().parents])):
            raise ValueError('Required SQLite backup is missing or not a regular file')
        state[suffix] = _file_digest(source)
    return state


@dataclass
class Bundle:
    rows: dict = field(default_factory=lambda: {table: [] for table in DATA_TABLES})
    skipped: dict = field(default_factory=dict)
    reconciled: dict = field(default_factory=dict)

    def counts(self):
        return {table: len(rows) for table, rows in sorted(self.rows.items())}


def read_sqlite(path, allowed, bundle):
    # Even mode=ro may write/create SQLite SHM. Inspect only a private copy of
    # the frozen database and its journals; never open the original with SQLite.
    before = _sqlite_source_state(path)
    with tempfile.TemporaryDirectory(prefix='v7-prepare-sqlite-') as temporary:
        root = Path(temporary)
        _protect_directory(root)
        staged = root / 'source.db'
        for suffix, checksum in before.items():
            target = Path(str(staged) + suffix)
            with Path(str(path) + suffix).open('rb') as incoming, target.open('xb') as outgoing:
                if os.name != 'nt':
                    os.fchmod(outgoing.fileno(), 0o600)
                shutil.copyfileobj(incoming, outgoing, length=256 * 1024)
            if _file_digest(target) != checksum:
                raise ValueError('SQLite source changed during preparation; use a frozen export')
        if _sqlite_source_state(path) != before:
            raise ValueError('SQLite source changed during preparation; use a frozen export')
        with closing(sqlite3.connect(staged)) as source:
            with closing(sqlite3.connect(':memory:')) as snapshot:
                source.backup(snapshot)
                if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite integrity check failed')
                snapshot.row_factory = sqlite3.Row
                tables = {row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if tables - allowed:
                    raise ValueError('Unknown SQLite tables require review before migration')
                for table in sorted(tables):
                    # Table identifiers are restricted to the static allowlist above.
                    rows = [dict(row) for row in snapshot.execute(f'SELECT * FROM "{table}"')]
                    if table in TRANSIENT_TABLES:
                        bundle.skipped[table] = len(rows)
                        continue
                    for row in rows:
                        if table == 'registration_requests' and row['status'] in {'verification', 'creating'}:
                            row.update(status='expired', code_hash='', password_hash='')
                    bundle.rows[table] = rows
        if _sqlite_source_state(path) != before:
            raise ValueError('SQLite source changed during preparation; use a frozen export')


def prepare(data_dir: Path, *, accounts: Path | None = None) -> Bundle:
    _reject_linked_source(data_dir)
    data_dir = data_dir.resolve(strict=True)
    bundle = Bundle()
    read_sqlite(data_dir / 'logs/security.db', SECURITY_TABLES, bundle)
    read_sqlite(data_dir / 'logs/analytics.db', ANALYTICS_TABLES, bundle)
    root = data_dir / 'business'
    _reject_linked_source(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Required business directory is missing or unsafe')
    seen = set()
    for directory in sorted(root.iterdir()):
        _reject_linked_source(directory)
        if directory.name in {'.write-lock.sqlite3','.write-lock.sqlite3-journal','.write-lock.sqlite3-wal','.write-lock.sqlite3-shm'} and directory.is_file() and not directory.is_symlink():
            continue  # Local coordination only; never application records.
        if directory.name == 'versions':
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Unexpected entry in business directory')
        tenant = tenant_key(directory.name)
        if tenant.casefold() in seen:
            raise ValueError('Case-ambiguous tenant keys require review')
        seen.add(tenant.casefold())
        bundle.rows['tenants'].append({'tenant': tenant})
        for path in sorted(directory.iterdir()):
            if path.name == 'audit.log.jsonl':
                bundle.rows['business_documents'].append({
                    'tenant': tenant, 'filename': path.name, 'payload': json_lines(path),
                })
                continue
            if path.is_symlink() or path.suffix != '.json' or not FILENAME.fullmatch(path.name):
                raise ValueError('Unexpected business file requires review before migration')
            bundle.rows['business_documents'].append({'tenant':tenant, 'filename':path.name, 'payload':json_file(path)})
    if not seen:
        raise ValueError('No source businesses found')
    canonical_tenants = {row['tenant'].casefold(): row['tenant'] for row in bundle.rows['tenants']}

    def canonical_reference(value, table):
        key = tenant_key(value)
        canonical_key = canonical_tenants.get(key.casefold())
        if canonical_key is None:
            raise ValueError('Legacy tenant reference has no source business; stop and investigate')
        if key != canonical_key:
            bundle.reconciled[table] = bundle.reconciled.get(table, 0) + 1
        return canonical_key

    # Older SQLite analytics and CRM uppercase tenant IDs, while document
    # directories preserve case. Reconcile only a unique existing business;
    # never create a tenant or discard/merge rows to hide an orphan/collision.
    for table in sorted(ANALYTICS_TABLES):
        for row in bundle.rows[table]:
            if 'tenant' in row:
                row['tenant'] = canonical_reference(row['tenant'], table)
    for row in bundle.rows['managed_businesses']:
        if row['tenant'] not in {item['tenant'] for item in bundle.rows['tenants']}:
            raise ValueError('Managed business has no source documents; stop and investigate')
    versions = root / 'versions'
    if versions.exists():
        if versions.is_symlink():
            raise ValueError('Unsafe version directory')
        for day in sorted(versions.iterdir()):
            _reject_linked_source(day)
            if day.is_symlink() or not day.is_dir():
                raise ValueError('Unexpected version entry')
            date.fromisoformat(day.name)
            for directory in sorted(day.iterdir()):
                _reject_linked_source(directory)
                if directory.is_symlink() or not directory.is_dir():
                    raise ValueError('Unsafe version tenant')
                tenant = tenant_key(directory.name)
                for path in sorted(directory.iterdir()):
                    if path.name == '_snapshot.json':
                        # Storage generates this provenance file alongside daily
                        # versions. Preserve it with an exact-name exception;
                        # arbitrary underscore filenames remain forbidden.
                        metadata = json_file(path)
                        if (not isinstance(metadata, dict)
                                or set(metadata) != {'tenant', 'created_at', 'source'}
                                or metadata['tenant'] != tenant
                                or not isinstance(metadata['created_at'], str)
                                or not isinstance(metadata['source'], str)
                                or not metadata['source'].strip()):
                            raise ValueError('Unexpected snapshot metadata requires review')
                        try:
                            created = datetime.fromisoformat(metadata['created_at'].replace('Z', '+00:00'))
                        except ValueError:
                            raise ValueError('Unexpected snapshot metadata requires review') from None
                        if created.utcoffset() != timedelta(0):
                            raise ValueError('Unexpected snapshot metadata requires review')
                        bundle.rows['document_versions'].append({
                            'tenant': tenant, 'day': day.name, 'filename': path.name, 'payload': metadata,
                        })
                        continue
                    if path.is_symlink() or path.suffix != '.json' or not FILENAME.fullmatch(path.name):
                        raise ValueError('Unexpected version file')
                    bundle.rows['document_versions'].append({'tenant':tenant, 'day':day.name, 'filename':path.name, 'payload':json_file(path)})
    if accounts is None:
        canonical_registry = data_dir / 'accounts.json'
        if canonical_registry.exists() or canonical_registry.is_symlink():
            accounts = canonical_registry
    if accounts:
        registry = json_file(accounts)
        if not isinstance(registry, dict) or not isinstance(registry.get('users'), list):
            raise ValueError('Invalid operator registry')
        for account in registry['users']:
            if not isinstance(account, dict) or not isinstance(account.get('email'), str):
                raise ValueError('Invalid operator account')
            bundle.rows['operator_accounts'].append({'email':account['email'], 'payload':account})
    crm_path = data_dir / 'logs/crm_snapshot.json'
    if crm_path.exists():
        for row in json_file(crm_path):
            tenant = canonical_reference(row['tenant'], 'crm_records')
            payload = {**row, 'tenant': tenant}
            bundle.rows['crm_records'].append({'tenant':tenant, 'id':row['id'], 'payload':payload})
    audit_path = data_dir / 'logs/selfrepair.log'
    if audit_path.exists():
        for entry in json_lines(audit_path):
            bundle.rows['audit_records'].append({'payload':entry})
    return bundle


def connection():
    import psycopg
    dsn = os.getenv('V7_SUPABASE_MIGRATION_DSN', '')
    if not dsn:
        raise ValueError('Set V7_SUPABASE_MIGRATION_DSN as a server secret')
    # Always override weaker sslmode values supplied in the DSN.
    return psycopg.connect(dsn, sslmode='verify-full',
                           sslrootcert=os.getenv('V7_SUPABASE_CA_FILE', 'system'),
                           connect_timeout=15, autocommit=False)


def verify(conn, bundle):
    from psycopg import sql
    from psycopg.rows import dict_row
    for table in sorted(DATA_TABLES):
        expected = bundle.rows[table]
        columns = list(expected[0]) if expected else ['*']
        projection = sql.SQL('*') if not expected else sql.SQL(',').join(map(sql.Identifier, columns))
        query = sql.SQL('SELECT {} FROM v7_private.{}').format(projection, sql.Identifier(table))
        with conn.cursor(row_factory=dict_row) as cursor:
            actual = cursor.execute(query).fetchall()
        if len(actual) != len(expected) or digest(actual) != digest(expected):
            raise ValueError('Destination verification failed for '+table)


def import_bundle(conn, bundle):
    from psycopg import sql
    from psycopg.types.json import Jsonb
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(71616001)')
        version = conn.execute('SELECT version FROM v7_private.schema_version ORDER BY version').fetchall()
        if version != [(1,), (2,), (3,), (4,), (5,)]:
            raise ValueError('Apply the reviewed V7 schema migration first')
        for table in sorted(DATA_TABLES | {'migration_runs'}):
            query = sql.SQL('SELECT EXISTS(SELECT 1 FROM v7_private.{})').format(sql.Identifier(table))
            if conn.execute(query).fetchone()[0]:
                raise ValueError('Destination must be empty; import will never overwrite data')
        # Parent records first. All remaining legacy identities and relationships retain their keys.
        order = ['tenants'] + sorted(DATA_TABLES - {'tenants'})
        for table in order:
            rows = bundle.rows[table]
            if not rows:
                continue
            columns = list(rows[0])
            if any(set(row) != set(columns) for row in rows):
                raise ValueError('Inconsistent source columns')
            query = sql.SQL('INSERT INTO v7_private.{} ({}) VALUES ({})').format(
                sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                sql.SQL(',').join(sql.Placeholder() for _ in columns))
            for row in rows:
                values = [Jsonb(row[column]) if column == 'payload' else row[column] for column in columns]
                conn.execute(query, values)
        verify(conn, bundle)
        for table in ['events','leads','api_usage','inventory_history','audit_records']:
            # Fixed allowlist; qualified regclass never comes from user data.
            name = 'v7_private.'+table
            sequence = conn.execute("SELECT pg_get_serial_sequence(%s, 'id')", (name,)).fetchone()[0]
            maximum = conn.execute(sql.SQL('SELECT MAX(id) FROM v7_private.{}').format(sql.Identifier(table))).fetchone()[0]
            conn.execute('SELECT setval(%s::regclass,%s,%s)', (sequence,maximum or 1,maximum is not None))
        run_id = digest([{'table':table,'digest':digest(rows)} for table,rows in sorted(bundle.rows.items())])
        conn.execute('INSERT INTO v7_private.migration_runs (id,counts) VALUES (%s,%s)', (run_id,Jsonb(bundle.counts())))
    return bundle.counts()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True, help='Frozen backup containing business/ and logs/')
    parser.add_argument('--accounts', type=Path, help='Protected ADMIN_USERS_FILE backup, if used')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--verify-only', action='store_true')
    parser.add_argument('--source-frozen', action='store_true', help='Confirm all writers were stopped before the backup was taken')
    args = parser.parse_args()
    if (args.apply or args.verify_only) and not args.source_frozen:
        parser.error('Database operations require a frozen backup and --source-frozen')
    try:
        # A canonical exporter manifest is checked before opening the destination
        # database. prepare() itself must remain usable on a frozen raw backup.
        manifest = args.data_dir / 'manifest.json'
        if manifest.exists() or manifest.is_symlink():
            try:
                from scripts.export_runtime import verify_export
            except ModuleNotFoundError:
                from export_runtime import verify_export
            verify_export(args.data_dir)
        bundle = prepare(args.data_dir, accounts=args.accounts)
        if args.apply or args.verify_only:
            with connection() as conn:
                if args.apply:
                    import_bundle(conn,bundle)
                else:
                    verify(conn,bundle)
        print(json.dumps({'mode':'imported' if args.apply else 'verified' if args.verify_only else 'dry-run',
                          'counts':bundle.counts(),'sessions_not_copied':bundle.skipped,
                          'tenant_references_reconciled':bundle.reconciled}, indent=2))
    except Exception as exc:
        # Database errors can contain DSNs, credentials, email or entire rejected rows.
        # Never dump exception messages/tracebacks from this credential-handling tool.
        print('Migration stopped ('+type(exc).__name__+'). Source files were not modified. '
              'Check the prerequisites in docs/SUPABASE_MIGRATION.md; no credentials or rows were logged.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
