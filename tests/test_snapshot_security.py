"""Offline archive regressions; all documents and credentials are synthetic."""
import io
import tarfile
from pathlib import Path

import pytest

from scripts import restore_snapshot as restore
from scripts import snapshot_backup as backup
from scripts.snapshot_paths import configured_business_root


@pytest.fixture
def business(tmp_path, monkeypatch):
    root = tmp_path / "business"
    tenant = root / "EXAMPLE"
    tenant.mkdir(parents=True)
    (tenant / "catalog.json").write_bytes(b'{"current":true}')
    other = root / "OTHER"
    other.mkdir()
    (other / "owner_accounts.json").write_bytes(b'{"protected":"synthetic"}')
    monkeypatch.setattr(restore, "BUSINESS_DIR", root)
    monkeypatch.setattr(backup, "BUSINESS_DIR", root)
    return root


def archive(tmp_path, members):
    path = tmp_path / "snapshot.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data, kind in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                member.linkname = "../../OTHER/owner_accounts.json"
            elif kind == tarfile.REGTYPE:
                member.size = len(data)
            tar.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return path


@pytest.mark.parametrize("name", [
    "business/EXAMPLE/../OTHER/owner_accounts.json",
    "business/EXAMPLE/../../application.py",
    "business/EXAMPLE/folder/../../../application.py",
    "business/EXAMPLE/..\\OTHER\\owner_accounts.json",
    "business/EXAMPLE/C:/secret.json",
    "business/EXAMPLE/catalog.json:alternate",
    "business/EXAMPLE/CON.json",
    "business/OTHER/owner_accounts.json",
    "/business/EXAMPLE/catalog.json",
])
def test_archive_paths_cannot_escape_selected_tenant(business, tmp_path, name):
    before = {path: path.read_bytes() for path in business.rglob("*") if path.is_file()}
    path = archive(tmp_path, [(name, b'{}', tarfile.REGTYPE)])
    with pytest.raises(ValueError):
        restore.snapshot_map(path, "EXAMPLE")
    assert {path: path.read_bytes() for path in business.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_archive_links_and_special_files_are_rejected(business, tmp_path, kind):
    path = archive(tmp_path, [("business/EXAMPLE/catalog.json", b'', kind)])
    with pytest.raises(ValueError, match="links and special"):
        restore.snapshot_map(path, "EXAMPLE")


def test_empty_archive_cannot_delete_current_business(business, tmp_path):
    with pytest.raises(ValueError, match="no files"):
        restore.snapshot_map(archive(tmp_path, []), "EXAMPLE")
    with pytest.raises(ValueError, match="empty"):
        restore.apply_changes("EXAMPLE", {}, restore.DiffReport([], ["EXAMPLE/catalog.json"], []), None)
    assert (business / "EXAMPLE/catalog.json").read_bytes() == b'{"current":true}'


def test_duplicate_members_are_not_silently_overwritten(business, tmp_path):
    path = archive(tmp_path, [("business/EXAMPLE/catalog.json", value, tarfile.REGTYPE)
                              for value in (b'{"one":1}', b'{"two":2}')])
    with pytest.raises(ValueError, match="Duplicate"):
        restore.snapshot_map(path, "EXAMPLE")


@pytest.mark.parametrize("tenant", ["../OTHER", "EXAMPLE/../OTHER", "versions", "EXAMPLE\\OTHER"])
def test_tenant_paths_are_rejected_by_backup_and_restore(business, tmp_path, tenant):
    with pytest.raises(ValueError, match="tenant"):
        backup.gather_files(tenant)
    with pytest.raises(ValueError, match="tenant"):
        restore.current_map(tenant)


def test_apply_preflights_all_paths_before_changing_valid_file(business):
    before = (business / "EXAMPLE/catalog.json").read_bytes()
    snap = {"EXAMPLE/catalog.json": b'{}', "EXAMPLE/../OTHER/owner_accounts.json": b'{}'}
    report = restore.DiffReport(["EXAMPLE/../OTHER/owner_accounts.json"], [], ["EXAMPLE/catalog.json"])
    with pytest.raises(ValueError):
        restore.apply_changes("EXAMPLE", snap, report, None)
    assert (business / "EXAMPLE/catalog.json").read_bytes() == before


def test_apply_preflights_file_parent_conflicts_before_any_change(business):
    before = (business / "EXAMPLE/catalog.json").read_bytes()
    snap = {"EXAMPLE/catalog.json": b'{}', "EXAMPLE/catalog.json/child.json": b'{}'}
    report = restore.DiffReport(["EXAMPLE/catalog.json/child.json"], [], ["EXAMPLE/catalog.json"])
    with pytest.raises(ValueError, match="conflicting"):
        restore.apply_changes("EXAMPLE", snap, report, None)
    assert (business / "EXAMPLE/catalog.json").read_bytes() == before


def test_corrupt_gzip_footer_is_not_accepted_as_complete_snapshot(business, tmp_path):
    path = archive(tmp_path, [("business/EXAMPLE/catalog.json", b'{}', tarfile.REGTYPE)])
    path.write_bytes(path.read_bytes()[:-4])
    with pytest.raises(EOFError):
        restore.snapshot_map(path, "EXAMPLE")


def test_snapshot_restore_bounds_file_and_decompressed_archive_size(business, tmp_path, monkeypatch):
    path = archive(tmp_path, [("business/EXAMPLE/catalog.json", b'A' * 4096, tarfile.REGTYPE)])
    monkeypatch.setattr(restore, "MAX_FILE_BYTES", 100)
    with pytest.raises(ValueError, match="file exceeds"):
        restore.snapshot_map(path, "EXAMPLE")
    monkeypatch.setattr(restore, "MAX_FILE_BYTES", 16000)
    monkeypatch.setattr(restore, "MAX_ARCHIVE_BYTES", 2000)
    with pytest.raises(ValueError, match="archive exceeds"):
        restore.snapshot_map(path, "EXAMPLE")


def test_backup_and_restore_roundtrip_preserves_docs_and_other_tenant(business, tmp_path):
    (business / "EXAMPLE/nested").mkdir()
    (business / "EXAMPLE/nested/offers.json").write_bytes(b'{"offer":"synthetic"}')
    snapshot = backup.make_snapshot("EXAMPLE", tmp_path / "backups", "2026-09-29")
    snap = restore.snapshot_map(snapshot, "EXAMPLE")
    (business / "EXAMPLE/catalog.json").write_bytes(b'{"changed":true}')
    report = restore.compute_diff(restore.current_map("EXAMPLE"), snap)
    class Audit:
        def record(self, **kwargs):
            pass
    restore.apply_changes("EXAMPLE", snap, report, Audit())
    assert (business / "EXAMPLE/catalog.json").read_bytes() == b'{"current":true}'
    assert (business / "OTHER/owner_accounts.json").read_bytes() == b'{"protected":"synthetic"}'
    with pytest.raises(FileExistsError):
        backup.make_snapshot("EXAMPLE", tmp_path / "backups", "2026-09-29")
    assert restore.snapshot_map(snapshot, "EXAMPLE") == snap


def test_failed_backup_does_not_publish_partial_archive(business, tmp_path, monkeypatch):
    def fail_add(*args, **kwargs):
        raise OSError("Synthetic backup read failure")
    monkeypatch.setattr(tarfile.TarFile, "add", fail_add)
    out_dir = tmp_path / "backups"
    with pytest.raises(OSError, match="backup read failure"):
        backup.make_snapshot("EXAMPLE", out_dir, "2026-09-29")
    assert list((out_dir / "2026-09-29").iterdir()) == []


def test_restore_dry_run_does_not_log_credential_contents(business, tmp_path, monkeypatch, capsys):
    path = archive(tmp_path, [("business/EXAMPLE/catalog.json", b'{"token":"synthetic-secret-value"}', tarfile.REGTYPE)])
    monkeypatch.setattr("sys.argv", ["restore_snapshot.py", "--tenant", "EXAMPLE", "--snapshot", str(path)])
    restore.main()
    output = capsys.readouterr()
    assert "synthetic-secret-value" not in output.out + output.err


def test_restore_audit_contains_file_metadata_and_never_credential_content(business, tmp_path):
    records = []
    class Audit:
        def record(self, **kwargs):
            records.append(kwargs)
    snap = {"EXAMPLE/catalog.json": b'{"token":"synthetic-secret-value"}'}
    report = restore.compute_diff(restore.current_map("EXAMPLE"), snap)
    restore.apply_changes("EXAMPLE", snap, report, Audit())
    assert [row["action"] for row in records] == ["restore_start", "restore_write"]
    assert "synthetic-secret-value" not in str(records)
    assert records[-1]["after"] == {"size": len(snap["EXAMPLE/catalog.json"])}


def test_unwritable_audit_stops_restore_before_any_file_change(business):
    class Audit:
        def record(self, **kwargs):
            raise OSError("Synthetic audit failure")
    snap = {"EXAMPLE/catalog.json": b'{}'}
    before = (business / "EXAMPLE/catalog.json").read_bytes()
    with pytest.raises(OSError, match="audit failure"):
        restore.apply_changes("EXAMPLE", snap, restore.DiffReport([], [], ["EXAMPLE/catalog.json"]), Audit())
    assert (business / "EXAMPLE/catalog.json").read_bytes() == before


def test_linked_destination_rejected_before_reading_or_writing(business, tmp_path):
    target = business / "EXAMPLE/link.json"
    try:
        target.symlink_to(business / "OTHER/owner_accounts.json")
    except OSError:
        pytest.skip("Creating a symlink requires an unavailable OS permission")
    path = archive(tmp_path, [("business/EXAMPLE/link.json", b'{}', tarfile.REGTYPE)])
    with pytest.raises(ValueError, match="Linked"):
        restore.snapshot_map(path, "EXAMPLE")


def test_filesystem_snapshot_tools_refuse_postgres_mode(business, monkeypatch):
    monkeypatch.setenv("V7_STORAGE_BACKEND", "postgres")
    with pytest.raises(ValueError, match="SQLite runtime"):
        restore.current_map("EXAMPLE")
    with pytest.raises(ValueError, match="SQLite runtime"):
        backup.gather_files("EXAMPLE")


def test_filesystem_snapshot_tools_resolve_mounted_business_root(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path / "data"))
    assert configured_business_root(Path("/unused/repo")) == tmp_path / "data/business"


def test_configured_root_does_not_resolve_away_links_before_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path / "data"))
    def reject_early_resolution(*args, **kwargs):
        raise AssertionError("Link validation must precede canonical resolution")
    monkeypatch.setattr(Path, "resolve", reject_early_resolution)
    assert configured_business_root(Path("/unused/repo")) == tmp_path / "data/business"
