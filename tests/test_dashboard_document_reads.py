"""Dashboard document batches preserve missing values and tenant boundaries."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from retrieval.storage import Storage
from service import platform_overview, postgres_business_documents
from service.postgres_business_documents import PostgresBusinessDocuments, TenantDocumentStorageError
from tests.conftest import set_test_identity


def test_postgres_batch_uses_one_checked_scope_and_preserves_null(monkeypatch):
    opened, statements = [], []

    class Database:
        def execute(self, sql, params=()):
            statements.append((sql, params))
            if sql.startswith("SELECT c.relname"):
                return SimpleNamespace(fetchall=lambda: [
                    (table, True, True, False)
                    for table in ("tenants", "business_documents", "document_versions")
                ])
            if sql.startswith("SELECT has_table_privilege"):
                return SimpleNamespace(fetchone=lambda: (False,))
            assert "WHERE tenant = %s AND filename = ANY(%s)" in sql
            assert params == ("Clinic_Mixed", ["catalog.json", "offers.json", "missing.json"])
            return SimpleNamespace(fetchall=lambda: [
                ("catalog.json", {"name": "Selected company's catalog"}), ("offers.json", None)
            ])

    @contextmanager
    def connection(tenant):
        opened.append(tenant)
        yield Database()

    monkeypatch.setattr(postgres_business_documents, "postgres_connection", connection)
    repository = PostgresBusinessDocuments("Clinic_Mixed")
    assert repository.read_documents(("catalog.json", "offers.json", "missing.json")) == {
        "catalog.json": {"name": "Selected company's catalog"}, "offers.json": None,
    }
    assert opened == ["Clinic_Mixed"]
    assert len(statements) == 5  # Existing table/privilege checks plus one document query.
    # Read again rather than reusing a prior response, preserving current data.
    repository.read_documents(("catalog.json", "offers.json", "missing.json"))
    assert opened == ["Clinic_Mixed", "Clinic_Mixed"]


def test_postgres_batch_keeps_forced_rls_validation(monkeypatch):
    class Database:
        def execute(self, sql, params=()):
            assert sql.startswith("SELECT c.relname")
            return SimpleNamespace(fetchall=lambda: [
                ("tenants", True, True, False),
                ("business_documents", True, False, False),
                ("document_versions", True, True, False),
            ])

    @contextmanager
    def connection(tenant):
        assert tenant == "ALPHA"
        yield Database()

    monkeypatch.setattr(postgres_business_documents, "postgres_connection", connection)
    with pytest.raises(TenantDocumentStorageError, match="Restricted V7 business tables"):
        PostgresBusinessDocuments("ALPHA").read_documents(("catalog.json",))


@pytest.mark.parametrize("filenames", [("catalog.json", "../other.json"), tuple("a.json" for _ in range(33))])
def test_postgres_batch_rejects_invalid_selection_before_database(monkeypatch, filenames):
    monkeypatch.setattr(postgres_business_documents, "postgres_connection",
                        lambda *args: pytest.fail("Database opened for invalid selection"))
    with pytest.raises(ValueError):
        PostgresBusinessDocuments("ALPHA").read_documents(filenames)


def test_local_batch_omits_only_missing_and_keeps_exact_tenant(tmp_path):
    for tenant in ("ALPHA", "BETA"):
        root = tmp_path / tenant
        root.mkdir()
        (root / "catalog.json").write_text(json.dumps({"name": tenant}))
        (root / "offers.json").write_text("null")
    storage = Storage("ALPHA", base_dir=tmp_path)
    assert storage.read_json_many("ALPHA", ("catalog.json", "offers.json", "missing.json")) == {
        "catalog.json": {"name": "ALPHA"}, "offers.json": None,
    }
    (tmp_path / "ALPHA" / "offers.json").write_text("malformed JSON")
    with pytest.raises(ValueError):
        storage.read_json_many("ALPHA", ("catalog.json", "offers.json"))
    with pytest.raises(ValueError, match="invalid_filename"):
        storage.read_json_many("ALPHA", ("catalog.json", "../BETA/catalog.json"))


def test_platform_batch_reports_missing_null_and_unstructured_documents(monkeypatch):
    calls = []
    documents = {
        "catalog.json": None, "faq.json": "malformed structure", "branches.json": [],
        "delivery.json": {}, "store_info.json": {"name": "Alpha"},
        "overrides.json": {"ai": {"mode": "v6"}},
    }

    def read(tenant, filenames):
        calls.append((tenant, filenames))
        return documents

    storage = SimpleNamespace(_using_postgres=lambda: True, tenant_keys=lambda: ["ALPHA"],
                              read_json_many=read)
    monkeypatch.setattr(platform_overview, "get_kpis", lambda **kwargs: {"total": 0, "errors": 0})
    monkeypatch.setattr(platform_overview, "get_errors", lambda **kwargs: [])
    result = platform_overview.get_platform_overview(
        SimpleNamespace(storage=storage, settings=SimpleNamespace(MODE="v7")))
    company = result["companies"][0]
    assert calls == [("ALPHA", platform_overview.KNOWLEDGE_FILES)]
    assert company["name"] == "Alpha" and company["mode"] == "v6"
    assert company["knowledge_files"] == 4
    assert company["issues"] == [
        "catalog.json: expected structured data", "faq.json: expected structured data",
        "branding.json: missing",
    ]
    assert company["status"] == "needs_attention"


def test_statistics_missing_optional_offer_retains_required_catalog(client, monkeypatch):
    with client.session_transaction() as state:
        set_test_identity(client, state, {"id": "dashboard-reader", "role": "business_owner"})
    storage = client.application.container.storage
    offer_path = storage.file_path("EXAMPLE", "offers.json")
    offer_path.unlink(missing_ok=True)
    captured = []
    monkeypatch.setattr("service.statistics.get_statistics", lambda **kwargs: captured.append(kwargs) or {})
    response = client.get("/admin/api/statistics?tenant=EXAMPLE&days=7")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert captured[0]["offers"] == []
    assert captured[0]["catalog"] == storage.read_json("EXAMPLE", "catalog.json")
    assert client.get("/admin/api/statistics?tenant=OTHER").status_code == 403
    assert len(captured) == 1
    storage.file_path("EXAMPLE", "catalog.json").unlink()
    assert client.get("/admin/api/statistics?tenant=EXAMPLE").status_code == 503
    assert len(captured) == 1
