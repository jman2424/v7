"""Runtime file locations, tenant mode resolution and first-start seeding."""
from pathlib import Path

from app.container import _bootstrap_persistent_business_data
from service import runtime_paths
from service.ai_mode import normalise, tenant_mode


def _clear(monkeypatch):
    for name in ("V7_DATA_DIR", "LOG_DIR", "ANALYTICS_DB_PATH", "SECURITY_DB_PATH",
                 "CRM_SNAPSHOT_PATH", "AUDIT_LOG_PATH"):
        monkeypatch.delenv(name, raising=False)


def test_state_files_follow_the_data_directory(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path / "data"))
    logs = tmp_path / "data" / "logs"
    assert runtime_paths.analytics_db_path() == logs / "analytics.db"
    assert runtime_paths.security_db_path() == logs / "security.db"
    assert runtime_paths.crm_snapshot_path() == logs / "crm_snapshot.json"
    assert runtime_paths.audit_log_path() == logs / "selfrepair.log"


def test_explicit_variables_win_and_defaults_stay_inside_the_working_directory(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert runtime_paths.analytics_db_path() == Path("logs/analytics.db")
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "custom.db"))
    assert runtime_paths.analytics_db_path() == tmp_path / "custom.db"


def test_existing_security_database_is_not_abandoned_on_upgrade(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "security.db").write_bytes(b"")
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path / "data"))
    assert runtime_paths.security_db_path() == Path("logs/security.db")
    (tmp_path / "data" / "logs").mkdir(parents=True)
    (tmp_path / "data" / "logs" / "security.db").write_bytes(b"")
    assert runtime_paths.security_db_path() == tmp_path / "data" / "logs" / "security.db"


def test_tenant_mode_reads_only_the_tenant_override():
    assert normalise("V6") == "v6"
    assert normalise("aiv7_flagship") == "v7"
    assert normalise(None) == "v7"
    assert tenant_mode({"ai": {"mode": "V5"}}) == "v5"
    assert tenant_mode({"ai": "invalid"}) == "v7"

    class Store:
        def get(self, key):
            return {"ai.mode": "v6"}.get(key)
    assert tenant_mode(Store()) == "v6"


def test_production_seed_copies_only_the_starter_business(tmp_path, monkeypatch):
    monkeypatch.setenv("V7_DATA_DIR", str(tmp_path))
    _bootstrap_persistent_business_data("EXAMPLE")
    assert sorted(path.name for path in (tmp_path / "business").iterdir()) == ["EXAMPLE"]
    assert (tmp_path / "business" / "EXAMPLE" / "store_info.json").is_file()
