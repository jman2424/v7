from __future__ import annotations

from app.container import _bootstrap_persistent_business_data
from retrieval.storage import Storage
from service.audit import AuditService
from service.crm_service import CRMService


def test_storage_uses_configured_persistent_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path))

    storage = Storage("EXAMPLE")

    assert storage.business_root == tmp_path / "business"
    assert storage.versions_root == tmp_path / "business" / "versions"


def test_persistent_bootstrap_seeds_once_without_overwriting_data(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path))

    _bootstrap_persistent_business_data()
    profile = tmp_path / "business" / "EXAMPLE" / "store_info.json"
    profile.write_text('{"name": "Saved tenant"}\n', encoding="utf-8")
    _bootstrap_persistent_business_data()

    assert profile.read_text(encoding="utf-8") == '{"name": "Saved tenant"}\n'
    assert (tmp_path / ".v7_data_initialized").is_file()


def test_lead_and_audit_storage_follow_persistent_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path))

    assert CRMService().snapshot_path == str(tmp_path / "logs" / "crm_snapshot.json")
    assert AuditService().log_path == str(tmp_path / "logs" / "selfrepair.log")
