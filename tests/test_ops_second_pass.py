"""Operator recovery must reject ambiguity and never resurrect authentication."""
import hashlib
import io
import json
import logging
import sqlite3
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.logging_setup import SafeFormatter
from scripts import platform_backup, restore_snapshot, snapshot_backup
from scripts.backup_utils import checked_path, contained_path


@pytest.fixture
def backup_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("V7_DATA_DIR", raising=False)
    root = tmp_path / "app"
    tenant = root / "business/ALPHA"
    tenant.mkdir(parents=True)
    (tenant / "catalog.json").write_text('{"price":25}')
    logs = root / "logs"
    logs.mkdir()
    monkeypatch.setenv("BUSINESS_DATA_ROOT", str(root / "business"))
    monkeypatch.delenv("ADMIN_USERS_FILE", raising=False)
    monkeypatch.setenv("CRM_SNAPSHOT_PATH", str(logs / "crm_snapshot.json"))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(logs / "audit.jsonl"))
    (logs / "crm_snapshot.json").write_text('{}')
    for key, name in (("ANALYTICS_DB_PATH", "analytics.db"), ("SECURITY_DB_PATH", "security.db")):
        path = logs / name
        monkeypatch.setenv(key, str(path))
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE sample (value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('original')")
            if name == "security.db":
                for table in ("management_sessions", "mcp_grants", "mfa_challenges", "trusted_devices", "oidc_states"):
                    connection.execute(f"CREATE TABLE {table} (token TEXT)")
                    connection.execute(f"INSERT INTO {table} VALUES ('old-active-grant')")
                connection.execute("CREATE TABLE totp_steps (account_hash TEXT PRIMARY KEY, step INTEGER NOT NULL)")
                connection.execute("INSERT INTO totp_steps VALUES ('account', 100)")
                connection.execute("CREATE TABLE mfa_code_uses (account TEXT NOT NULL, secret_hash TEXT NOT NULL, timestep INTEGER NOT NULL, PRIMARY KEY(account,secret_hash,timestep))")
                connection.execute("INSERT INTO mfa_code_uses VALUES ('account', 'secret-hash', 100)")
                connection.execute("CREATE TABLE auth_login_failures (attempt TEXT PRIMARY KEY, subject_hash TEXT NOT NULL, attempted REAL NOT NULL)")
                connection.execute("INSERT INTO auth_login_failures VALUES ('shared-attempt', 'subject-hash', 100)")
                connection.execute("CREATE TABLE oidc_links (provider TEXT, account TEXT)")
                connection.execute("INSERT INTO oidc_links VALUES ('google', 'account')")
                connection.execute("CREATE TABLE registration_requests (password_hash TEXT, code_hash TEXT, status TEXT)")
                connection.execute("INSERT INTO registration_requests VALUES ('pending-password', 'email-code', 'verification')")
                connection.execute("INSERT INTO registration_requests VALUES ('verified-password', '', 'pending')")
        connection.close()
    snapshot = platform_backup.create_backup(root, tmp_path / "backup")
    return root, snapshot


@pytest.mark.parametrize("relative", ["ALPHA/CON.json", "ALPHA/aux", "ALPHA/NUL", "ALPHA/COM1.txt", "ALPHA/a?b", "ALPHA/a|b", "ALPHA/\x00bad"])
def test_reserved_backup_paths_are_rejected(tmp_path, relative):
    with pytest.raises(ValueError, match="Unsafe backup path"):
        contained_path(tmp_path, relative)


@pytest.mark.parametrize("kind", ["is_symlink", "is_junction"])
def test_backup_paths_reject_parent_directory_alias(tmp_path, monkeypatch, kind):
    alias = tmp_path / "aliased-directory"
    original = getattr(Path, kind, lambda path: False)
    monkeypatch.setattr(Path, kind, lambda path: path == alias or original(path), raising=False)
    with pytest.raises(ValueError, match="junctions"):
        checked_path(alias / "private/accounts.json")


@pytest.mark.parametrize("manifest", [
    '[]',
    '{"format":1,"created":"today","files":{},"files":{}}',
    '{"format":true,"created":"today","files":{}}',
    '{"format":1,"created":"today","files":{},"unexpected":true}',
])
def test_ambiguous_manifest_rejected_before_restore(backup_environment, manifest):
    _, snapshot = backup_environment
    (snapshot / "manifest.json").write_text(manifest)
    with pytest.raises(ValueError):
        platform_backup.verify_backup(snapshot)


def test_case_colliding_manifest_paths_are_rejected(backup_environment):
    _, snapshot = backup_environment
    manifest = json.loads((snapshot / "manifest.json").read_text())
    manifest["files"]["business/alpha/catalog.json"] = hashlib.sha256(b'{}').hexdigest()
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Ambiguous"):
        platform_backup.verify_backup(snapshot)


def test_recovery_rejects_same_database_targets_before_changes(backup_environment, monkeypatch):
    root, snapshot = backup_environment
    monkeypatch.setenv("SECURITY_DB_PATH", str(root / "logs/analytics.db"))
    (root / "business/ALPHA/catalog.json").write_text('changed')
    with pytest.raises(ValueError, match="distinct"):
        platform_backup.restore_backup(root, snapshot, service_stopped=True)
    assert (root / "business/ALPHA/catalog.json").read_text() == 'changed'


def test_recovery_failure_cannot_restore_active_credentials(backup_environment, monkeypatch):
    root, snapshot = backup_environment
    security = root / "logs/security.db"
    with sqlite3.connect(security) as connection:
        for table in ("management_sessions", "mcp_grants", "mfa_challenges", "trusted_devices", "oidc_states"):
            connection.execute(f"DELETE FROM {table}")
        connection.execute("UPDATE totp_steps SET step=101")
        connection.execute("INSERT INTO mfa_code_uses VALUES ('account', 'secret-hash', 101)")
        connection.execute("UPDATE auth_login_failures SET attempted=101")
        connection.execute("INSERT INTO auth_login_failures VALUES ('recent-attempt', 'subject-hash', 102)")
    connection.close()
    original_write = platform_backup.atomic_write

    def fail_private_write(path, data):
        if path == root / "logs/crm_snapshot.json":
            raise OSError("simulated interrupted restore")
        original_write(path, data)

    monkeypatch.setattr(platform_backup, "atomic_write", fail_private_write)
    with pytest.raises(OSError, match="interrupted"):
        platform_backup.restore_backup(root, snapshot, service_stopped=True)
    with sqlite3.connect(security) as connection:
        for table in ("management_sessions", "mcp_grants", "mfa_challenges", "trusted_devices", "oidc_states"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("SELECT step FROM totp_steps WHERE account_hash='account'").fetchone()[0] == 101
        assert connection.execute("SELECT timestep FROM mfa_code_uses ORDER BY timestep").fetchall() == [(100,), (101,)]
        assert connection.execute("SELECT attempt,attempted FROM auth_login_failures ORDER BY attempted").fetchall() == [('shared-attempt', 101), ('recent-attempt', 102)]
        assert connection.execute("SELECT provider,account FROM oidc_links").fetchone() == ('google', 'account')
        assert connection.execute("SELECT password_hash,code_hash FROM registration_requests WHERE status='expired'").fetchone() == ('', '')
        assert connection.execute("SELECT password_hash FROM registration_requests WHERE status='pending'").fetchone()[0] == 'verified-password'
    connection.close()


def test_recovery_rejects_directory_database_sidecar_before_changes(backup_environment):
    root, snapshot = backup_environment
    (root / "logs/security.db-wal").unlink(missing_ok=True)
    (root / "logs/security.db-wal").mkdir()
    (root / "business/ALPHA/catalog.json").write_text('changed')
    with pytest.raises(ValueError, match="sidecar"):
        platform_backup.restore_backup(root, snapshot, service_stopped=True)
    assert (root / "business/ALPHA/catalog.json").read_text() == 'changed'


def test_old_security_snapshot_retains_current_replay_and_lockout_tables(backup_environment):
    root, snapshot = backup_environment
    with sqlite3.connect(":memory:") as database:
        database.deserialize((snapshot / "databases/security.db").read_bytes())
        database.execute("DROP TABLE mfa_code_uses")
        database.execute("DROP TABLE auth_login_failures")
        old_snapshot = database.serialize()
    restored = platform_backup._restore_database(old_snapshot, root / "logs/security.db")
    with sqlite3.connect(":memory:") as database:
        database.deserialize(restored)
        assert database.execute("SELECT account,secret_hash,timestep FROM mfa_code_uses").fetchone() == ('account', 'secret-hash', 100)
        assert database.execute("SELECT attempt,subject_hash,attempted FROM auth_login_failures").fetchone() == ('shared-attempt', 'subject-hash', 100)


def test_unreadable_live_replay_state_requires_clean_restore_target(backup_environment):
    root, snapshot = backup_environment
    (root / "logs/security.db").write_bytes(b'not a database')
    (root / "business/ALPHA/catalog.json").write_text('changed')
    with pytest.raises(ValueError, match="clean database target"):
        platform_backup.restore_backup(root, snapshot, service_stopped=True)
    assert (root / "business/ALPHA/catalog.json").read_text() == 'changed'


def test_snapshot_restore_requires_audit_before_changes(tmp_path, monkeypatch):
    business = tmp_path / "business"
    tenant = business / "ALPHA"
    tenant.mkdir(parents=True)
    (tenant / "catalog.json").write_bytes(b'old')
    monkeypatch.setattr(restore_snapshot, "BUSINESS_DIR", business)
    audit = Mock()
    audit.record.side_effect = OSError("audit unavailable")
    snapshot = {"ALPHA/catalog.json": b'new'}
    report = restore_snapshot.compute_diff({"ALPHA/catalog.json": b'old'}, snapshot)
    with pytest.raises(OSError, match="audit unavailable"):
        restore_snapshot.apply_changes("ALPHA", snapshot, report, audit)
    assert (tenant / "catalog.json").read_bytes() == b'old'


def test_case_colliding_tenant_archive_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(restore_snapshot, "BUSINESS_DIR", tmp_path / "business")
    archive = tmp_path / "snapshot.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name in ("catalog.json", "CATALOG.json"):
            entry = tarfile.TarInfo("business/ALPHA/" + name)
            entry.size = 2
            stream.addfile(entry, io.BytesIO(b'{}'))
    with pytest.raises(ValueError, match="Duplicate"):
        restore_snapshot.snapshot_map(archive, "ALPHA")


def test_tenant_backup_cannot_be_written_inside_business_data(tmp_path, monkeypatch):
    business = tmp_path / "business"
    (business / "ALPHA").mkdir(parents=True)
    (business / "ALPHA/catalog.json").write_text('{}')
    monkeypatch.setattr(snapshot_backup, "BUSINESS_DIR", business)
    with pytest.raises(ValueError, match="outside business"):
        snapshot_backup.make_snapshot("ALPHA", business / "ALPHA/backups", "2026-09-30")


def test_log_formatter_cannot_reuse_private_cached_exception_text():
    error = ValueError("private customer document")
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "operation failed: %s", (error,), None)
    record.exc_text = "private cached traceback and bearer token"
    result = SafeFormatter("%(message)s").format(record)
    assert result == "operation failed: ValueError"
    assert record.args == (error,)


def test_encoded_credentials_are_redacted(monkeypatch):
    monkeypatch.setenv("PROVIDER_TOKEN", "private+token/with spaces")
    record = logging.LogRecord("test", logging.WARNING, __file__, 1,
                               "/callback?hub%2Everify_token=arbitrary-secret&client_secret=another-secret "
                               "private%2Btoken%2Fwith%20spaces", (), None)
    output = SafeFormatter("%(message)s").format(record)
    assert "arbitrary-secret" not in output
    assert "another-secret" not in output
    assert "private%2Btoken" not in output


@pytest.mark.parametrize("action", ["create", "restore", "tenant"])
def test_file_backups_fail_closed_for_postgres(tmp_path, monkeypatch, action):
    monkeypatch.setenv("V7_STORAGE_BACKEND", "postgres")
    with pytest.raises(ValueError, match="SQLite"):
        if action == "create":
            platform_backup.create_backup(tmp_path, tmp_path / "snapshot")
        elif action == "restore":
            platform_backup.restore_backup(tmp_path, tmp_path / "snapshot", service_stopped=True)
        else:
            snapshot_backup.gather_files("ALPHA")
    assert not (tmp_path / "snapshot").exists()


def test_persistent_root_and_explicit_overrides_are_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path / "persistent"))
    monkeypatch.setenv("BUSINESS_DATA_ROOT", "")
    monkeypatch.setenv("AUDIT_LOG_PATH", "")
    monkeypatch.setenv("CRM_SNAPSHOT_PATH", "")
    assert platform_backup.business_path(tmp_path) == tmp_path / "persistent/business"
    assert platform_backup.private_paths(tmp_path)["private/audit.jsonl"] == tmp_path / "persistent/logs/selfrepair.log"
    from service.audit import AuditService
    assert Path(AuditService().log_path) == tmp_path / "persistent/logs/selfrepair.log"
    monkeypatch.setenv("BUSINESS_DATA_ROOT", str(tmp_path / "separate-business"))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "separate-audit.jsonl"))
    assert platform_backup.business_path(tmp_path) == tmp_path / "separate-business"
    assert Path(AuditService().log_path) == tmp_path / "separate-audit.jsonl"


def test_relative_operator_paths_resolve_against_runtime_root(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_DATA_DIR", "persistent")
    monkeypatch.setenv("BUSINESS_DATA_ROOT", "")
    monkeypatch.setenv("ANALYTICS_DB_PATH", "logs/analytics.db")
    monkeypatch.setenv("CRM_SNAPSHOT_PATH", "private/crm.json")
    assert platform_backup.business_path(tmp_path) == tmp_path / "persistent/business"
    assert platform_backup.database_paths(tmp_path)["analytics.db"] == tmp_path / "logs/analytics.db"
    assert platform_backup.private_paths(tmp_path)["private/crm_snapshot.json"] == tmp_path / "private/crm.json"
