"""Offline operators must reject directory aliases on Python 3.11 as well."""
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.backup_utils import checked_path, is_linked_path
from scripts.export_runtime import _safe_path
from scripts.prepare_supabase import _reject_linked_source
from scripts.snapshot_paths import reject_links


GUARDS = [checked_path, _safe_path, _reject_linked_source, reject_links]


@pytest.mark.parametrize("guard", GUARDS)
def test_offline_guard_rejects_junction_ancestor_without_pathlib_api(tmp_path, monkeypatch, guard):
    alias = tmp_path / "alias"
    alias.mkdir()
    payload = alias / "private.json"
    payload.write_text('{"synthetic":true}')
    original_lstat = Path.lstat
    monkeypatch.delattr(Path, "is_junction", raising=False)
    # Simulate Windows lstat metadata while running on Linux CI as well.
    monkeypatch.setattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003, raising=False)
    monkeypatch.setattr(Path, "lstat", lambda path: (
        SimpleNamespace(st_mode=stat.S_IFDIR, st_reparse_tag=0xA0000003)
        if path == alias else original_lstat(path)
    ))
    with pytest.raises(ValueError, match="[Ll]ink|junction"):
        guard(payload)
    assert payload.read_text() == '{"synthetic":true}'


@pytest.mark.skipif(os.name != "nt", reason="Windows junction integration")
@pytest.mark.parametrize("guard", GUARDS)
def test_real_windows_junction_rejected_without_pathlib_api(tmp_path, monkeypatch, guard):
    import _winapi

    target = tmp_path / "target"
    target.mkdir()
    payload = target / "private.json"
    payload.write_text('{"synthetic":true}')
    alias = tmp_path / "alias"
    _winapi.CreateJunction(str(target), str(alias))
    try:
        assert not alias.is_symlink()
        assert alias.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
        monkeypatch.delattr(Path, "is_junction", raising=False)
        with pytest.raises(ValueError, match="[Ll]ink|junction"):
            guard(alias / "private.json")
        assert payload.read_text() == '{"synthetic":true}'
    finally:
        # Remove only the freshly created junction, never its target directory.
        alias.rmdir()


def test_missing_offline_destination_and_regular_directory_remain_allowed(tmp_path, monkeypatch):
    monkeypatch.delattr(Path, "is_junction", raising=False)
    assert not is_linked_path(tmp_path)
    assert not is_linked_path(tmp_path / "new" / "private.json")
    assert checked_path(tmp_path / "new" / "private.json") == tmp_path / "new" / "private.json"


def test_offline_path_metadata_permission_failure_is_not_ignored(tmp_path, monkeypatch):
    candidate = tmp_path / "private.json"
    original_lstat = Path.lstat

    def lstat(path):
        if path == candidate:
            raise PermissionError("Synthetic denied metadata")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(PermissionError):
        is_linked_path(candidate)
