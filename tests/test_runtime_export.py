"""Offline complete-source export safety checks; never uses live V7 data."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scripts import export_runtime as exporter


@pytest.fixture(autouse=True)
def clean_export_environment(monkeypatch):
    for name in ('ADMIN_USERS_FILE', 'CRM_SNAPSHOT_PATH', 'V7_DATA_DIR',
                 'SECURITY_DB_PATH', 'ANALYTICS_DB_PATH', 'V7_STORAGE_BACKEND'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def runtime(tmp_path):
    source = tmp_path / 'runtime'
    logs = source / 'logs'
    logs.mkdir(parents=True)
    business = source / 'business'
    tenant = business / 'ALPHA'
    tenant.mkdir(parents=True)
    (tenant / 'owner_accounts.json').write_text(json.dumps([
        {'id': 'test-account', 'password_hash': 'test-only-hash', 'roles': ['business_owner']},
    ]))
    (tenant / 'website_knowledge.json').write_text(json.dumps({'pages': [{'text': 'Example facts'}]}))
    (tenant / 'ai_model.json').write_text(json.dumps({'model': 'gpt-4o-mini'}))
    version = business / 'versions/2026-09-26/ALPHA'
    version.mkdir(parents=True)
    (version / 'catalog.json').write_text('{"categories":[]}')
    (version / '_snapshot.json').write_text(json.dumps({
        'tenant': 'ALPHA', 'created_at': '2026-09-26T00:00:00Z', 'source': 'business/ALPHA',
    }))
    with closing(sqlite3.connect(logs / 'security.db')) as db, db:
        db.execute('CREATE TABLE account_authenticators (account TEXT PRIMARY KEY, secret TEXT NOT NULL)')
        db.execute("INSERT INTO account_authenticators VALUES ('test-account','test-only-secret')")
        db.execute('CREATE TABLE management_sessions (token_hash TEXT PRIMARY KEY, identity TEXT, revision TEXT, expires REAL)')
        db.execute("INSERT INTO management_sessions VALUES ('test-hash','{}','test-revision',99)")
    with closing(sqlite3.connect(logs / 'analytics.db')) as db, db:
        db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, tenant TEXT, event_type TEXT)')
        db.execute("INSERT INTO events VALUES (7,'ALPHA','msg_in')")
    (logs / 'crm_snapshot.json').write_text(json.dumps([
        {'id': 'test-lead', 'tenant': 'ALPHA', 'conversations': [{'text': 'Test conversation'}]},
    ]))
    (logs / 'selfrepair.log').write_text('{"action":"test-action"}\n')
    accounts = tmp_path / 'protected-accounts.json'
    accounts.write_text('{"users":[{"email":"operator@example.invalid","password_hash":"test-operator-hash"}]}')
    return exporter.Sources(business, logs / 'security.db', logs / 'analytics.db',
                            logs / 'crm_snapshot.json', logs / 'selfrepair.log', accounts)


def source_bytes(runtime):
    paths = list(runtime.business.rglob('*')) + [runtime.security, runtime.analytics,
                                                runtime.crm, runtime.audit, runtime.accounts]
    paths += [Path(str(db) + suffix) for db in [runtime.security, runtime.analytics]
              for suffix in ('-wal', '-shm', '-journal')]
    return {str(path): path.read_bytes() for path in paths if path is not None and path.is_file()}


def test_complete_export_preserves_credentials_and_sources(runtime, tmp_path):
    before = source_bytes(runtime)
    destination = tmp_path / 'backup'
    report = exporter.export_runtime(runtime, destination, source_frozen=True)
    assert report['complete'] is True
    assert report['counts']['tenants'] == 1
    assert report['counts']['document_versions'] == 2
    assert report['counts']['operator_accounts'] == 1
    assert report['counts']['crm_records'] == 1
    assert report['migration_skipped']['management_sessions'] == 1
    assert (destination / 'business/versions/2026-09-26/ALPHA/_snapshot.json').read_bytes() == (runtime.business / 'versions/2026-09-26/ALPHA/_snapshot.json').read_bytes()
    with closing(sqlite3.connect(destination / 'logs/security.db')) as db:
        assert db.execute('SELECT secret FROM account_authenticators').fetchone()[0] == 'test-only-secret'
        assert db.execute('SELECT count(*) FROM management_sessions').fetchone()[0] == 1
    assert (destination / 'business/ALPHA/owner_accounts.json').read_bytes() == (runtime.business / 'ALPHA/owner_accounts.json').read_bytes()
    assert before == source_bytes(runtime)
    assert exporter.verify_export(destination) == report
    if os.name != 'nt':
        assert destination.stat().st_mode & 0o077 == 0
        assert all(path.stat().st_mode & 0o077 == 0 for path in destination.rglob('*'))


def test_backup_api_captures_committed_wal_without_source_writes(runtime, tmp_path):
    with closing(sqlite3.connect(runtime.analytics)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO events VALUES (8,'ALPHA','msg_out')")
        writer.commit()
        before = source_bytes(runtime)
        report = exporter.export_runtime(runtime, tmp_path / 'backup', source_frozen=True)
        assert report['counts']['events'] == 2
        assert before == source_bytes(runtime)
        assert not (tmp_path / 'backup/logs/analytics.db-wal').exists()


def test_manifest_records_case_reconciliation_without_changing_raw_backup(runtime, tmp_path):
    (runtime.business / 'ALPHA').rename(runtime.business / 'Alpha')
    day = runtime.business / 'versions/2026-09-26'
    (day / 'ALPHA').rename(day / 'Alpha')
    marker = day / 'Alpha/_snapshot.json'
    metadata = json.loads(marker.read_text())
    metadata.update(tenant='Alpha', source='business/Alpha')
    marker.write_text(json.dumps(metadata))
    before = source_bytes(runtime)
    destination = tmp_path / 'backup'
    report = exporter.export_runtime(runtime, destination, source_frozen=True)
    assert report['migration_reconciled'] == {'events': 1, 'crm_records': 1}
    manifest = json.loads((destination / 'manifest.json').read_text())
    assert manifest['migration_reconciled'] == report['migration_reconciled']
    with closing(sqlite3.connect(destination / 'logs/analytics.db')) as db:
        assert db.execute('SELECT tenant FROM events').fetchone()[0] == 'ALPHA'
    assert (destination / 'logs/crm_snapshot.json').read_bytes() == runtime.crm.read_bytes()
    assert source_bytes(runtime) == before
    assert exporter.verify_export(destination) == report


def test_export_requires_frozen_source(runtime, tmp_path):
    with pytest.raises(ValueError, match='freeze|Stop all writers'):
        exporter.export_runtime(runtime, tmp_path / 'backup')
    assert not (tmp_path / 'backup').exists()


def test_never_overwrites_existing_destination(runtime, tmp_path):
    destination = tmp_path / 'backup'
    destination.mkdir()
    marker = destination / 'keep.txt'
    marker.write_text('original')
    with pytest.raises(ValueError, match='already exist'):
        exporter.export_runtime(runtime, destination, source_frozen=True)
    assert marker.read_text() == 'original'


@pytest.mark.parametrize('missing', ['security', 'analytics', 'crm', 'audit', 'accounts'])
def test_missing_expected_source_fails(runtime, tmp_path, missing):
    getattr(runtime, missing).unlink()
    with pytest.raises(FileNotFoundError):
        exporter.export_runtime(runtime, tmp_path / 'backup', source_frozen=True)
    assert not (tmp_path / 'backup').exists()


def test_rejects_unrecognized_business_files(runtime, tmp_path):
    (runtime.business / 'ALPHA/private.bin').write_bytes(b'test-data')
    with pytest.raises(ValueError, match='Unexpected business file'):
        exporter.export_runtime(runtime, tmp_path / 'backup', source_frozen=True)
    assert not (tmp_path / 'backup').exists()


@pytest.mark.parametrize('name,content', [
    ('_other.json', '{}'),
    ('_snapshot.json', '{"private_record":"must-not-be-skipped"}'),
    ('_snapshot.json', '{"tenant":"BETA","created_at":"2026-09-26T00:00:00Z","source":"business/ALPHA"}'),
])
def test_snapshot_metadata_exception_rejects_other_names_and_invalid_metadata(runtime, tmp_path, name, content):
    (runtime.business / 'versions/2026-09-26/ALPHA' / name).write_text(content)
    with pytest.raises(ValueError, match='Unexpected'):
        exporter.export_runtime(runtime, tmp_path / 'backup', source_frozen=True)
    assert not (tmp_path / 'backup').exists()


def test_rejects_source_change_and_removes_partial_export(runtime, tmp_path, monkeypatch):
    copy = exporter._copy_file
    changed = False
    def change_after_copy(source, target):
        nonlocal changed
        copy(source, target)
        if not changed:
            source.write_text(source.read_text() + '\n')
            changed = True
    monkeypatch.setattr(exporter, '_copy_file', change_after_copy)
    with pytest.raises(ValueError, match='Source changed'):
        exporter.export_runtime(runtime, tmp_path / 'backup', source_frozen=True)
    assert not (tmp_path / 'backup').exists()


def test_rejects_destination_inside_business_source(runtime):
    with pytest.raises(ValueError, match='overlap'):
        exporter.export_runtime(runtime, runtime.business / 'backup', source_frozen=True)
    assert not (runtime.business / 'backup').exists()


def test_manifest_detects_changed_and_missing_files(runtime, tmp_path):
    destination = tmp_path / 'backup'
    exporter.export_runtime(runtime, destination, source_frozen=True)
    account_path = destination / 'business/ALPHA/owner_accounts.json'
    original = account_path.read_bytes()
    account_path.write_bytes(b'[]')
    with pytest.raises(ValueError, match='checksum'):
        exporter.verify_export(destination)
    account_path.write_bytes(original)
    account_path.unlink()
    with pytest.raises(ValueError, match='inventory'):
        exporter.verify_export(destination)


def test_manifest_does_not_ignore_coordination_named_files_at_backup_root(runtime, tmp_path):
    destination = tmp_path / 'backup'
    exporter.export_runtime(runtime, destination, source_frozen=True)
    (destination / '.write-lock.sqlite3').write_bytes(b'unexpected backup file')
    with pytest.raises(ValueError, match='inventory'):
        exporter.verify_export(destination)


def test_import_cli_verifies_export_manifest_before_connecting(runtime, tmp_path, monkeypatch, capsys):
    from scripts import prepare_supabase as preparation
    destination = tmp_path / 'backup'
    exporter.export_runtime(runtime, destination, source_frozen=True)
    (destination / 'business/ALPHA/owner_accounts.json').write_text('[]')
    connected = False
    def destination_connection():
        nonlocal connected
        connected = True
        raise AssertionError('Do not connect after backup checksum mismatch')
    monkeypatch.setattr(preparation, 'connection', destination_connection)
    monkeypatch.setattr('sys.argv', ['prepare_supabase.py', '--data-dir', str(destination),
                                   '--apply', '--source-frozen'])
    assert preparation.main() == 1
    assert connected is False
    assert 'Source files were not modified' in capsys.readouterr().err


def test_manifest_detects_added_empty_directory(runtime, tmp_path):
    destination = tmp_path / 'backup'
    exporter.export_runtime(runtime, destination, source_frozen=True)
    (destination / 'unexpected').mkdir()
    with pytest.raises(ValueError, match='directory inventory'):
        exporter.verify_export(destination)


def test_rejects_linked_source_files(runtime, tmp_path):
    target = runtime.business / 'ALPHA/ai_model.json'
    target.unlink()
    try:
        target.symlink_to(runtime.accounts)
    except OSError:
        pytest.skip('Creating a symlink requires an unavailable OS permission')
    with pytest.raises(ValueError, match='Linked'):
        exporter.export_runtime(runtime, tmp_path / 'backup', source_frozen=True)
    assert not (tmp_path / 'backup').exists()


def test_cli_uses_configured_external_files_and_logs_counts_only(runtime, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('ADMIN_USERS_FILE', str(runtime.accounts))
    monkeypatch.setenv('SECURITY_DB_PATH', str(runtime.security))
    monkeypatch.setenv('ANALYTICS_DB_PATH', str(runtime.analytics))
    monkeypatch.setenv('CRM_SNAPSHOT_PATH', str(runtime.crm))
    output = tmp_path / 'backup'
    assert exporter.main(['--source-dir', str(runtime.business.parent), '--out', str(output), '--source-frozen']) == 0
    emitted = capsys.readouterr()
    assert '"complete": true' in emitted.out
    for secret in ('test-only-hash', 'test-only-secret', 'test-operator-hash', 'operator@example.invalid', 'Test conversation'):
        assert secret not in emitted.out + emitted.err
    assert (output / 'accounts.json').read_bytes() == runtime.accounts.read_bytes()


def test_cli_failure_does_not_echo_private_source_content(runtime, tmp_path, capsys):
    (runtime.business / 'ALPHA/owner_accounts.json').write_text('private-test-content-is-not-json')
    result = exporter.main(['--source-dir', str(runtime.business.parent), '--out', str(tmp_path / 'backup'),
                            '--analytics-db', str(runtime.analytics), '--source-frozen'])
    assert result == 1
    output = capsys.readouterr()
    assert 'private-test-content' not in output.out + output.err
    assert 'Export stopped (' in output.err


def test_cannot_declare_existing_crm_or_audit_absent(runtime, tmp_path):
    for flag in ('--no-crm-snapshot', '--no-audit-log'):
        assert exporter.main(['--source-dir', str(runtime.business.parent), '--out', str(tmp_path / 'backup'),
                              '--analytics-db', str(runtime.analytics), '--source-frozen', flag]) == 1
    assert not (tmp_path / 'backup').exists()


def test_configured_export_paths_match_literal_runtime_file_paths(runtime, monkeypatch):
    from types import SimpleNamespace
    root = runtime.business.parent
    monkeypatch.setenv('V7_DATA_DIR', '~/v7-test-data')
    monkeypatch.setenv('SECURITY_DB_PATH', '~/security.db')
    monkeypatch.setenv('ANALYTICS_DB_PATH', '~/analytics.db')
    monkeypatch.setenv('CRM_SNAPSHOT_PATH', '~/crm.json')
    monkeypatch.setenv('ADMIN_USERS_FILE', '~/accounts.json')
    args = SimpleNamespace(source_dir=root, business_dir=None, security_db=None,
        analytics_db=None, crm_snapshot=None, audit_log=None, accounts=None,
        no_crm_snapshot=False, no_audit_log=False)
    sources = exporter.configured_sources(args)
    assert sources.business == Path('~/v7-test-data').expanduser() / 'business'
    assert sources.security == root / '~/security.db'
    assert sources.analytics == root / '~/analytics.db'
    assert sources.crm == root / '~/crm.json'
    assert sources.audit == root / '~/v7-test-data/logs/selfrepair.log'
    assert sources.accounts == Path('~/accounts.json').expanduser()


def test_explicit_export_file_paths_expand_user(runtime, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv('V7_DATA_DIR', raising=False)
    args = SimpleNamespace(source_dir=runtime.business.parent, business_dir='~/business',
        security_db='~/security.db', analytics_db='~/analytics.db', crm_snapshot='~/crm.json',
        audit_log='~/audit.log', accounts='~/accounts.json',
        no_crm_snapshot=False, no_audit_log=False)
    sources = exporter.configured_sources(args)
    assert sources.business == Path('~/business').expanduser()
    assert sources.security == Path('~/security.db').expanduser()
    assert sources.analytics == Path('~/analytics.db').expanduser()
    assert sources.crm == Path('~/crm.json').expanduser()
    assert sources.audit == Path('~/audit.log').expanduser()
    assert sources.accounts == Path('~/accounts.json').expanduser()
