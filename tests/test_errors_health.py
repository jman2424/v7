"""The console owns health checks; the legacy page cannot be rendered."""
from unittest.mock import Mock

from tests.test_platform_security import login, platform  # noqa: F401


def test_legacy_errors_redirect_is_local_and_tenant_scoped(request):
    app, _, _ = request.getfixturevalue("platform")
    client = app.test_client()
    assert client.get("/admin/errors?tenant=ALPHA").status_code == 303
    login(client)
    response = client.get("/admin/errors?tenant=ALPHA&next=https://untrusted.example")
    assert response.status_code == 303
    assert response.headers["Location"] == "/console/errors?tenant=ALPHA"
    assert "Business data check" not in response.text
    assert client.get("/admin/errors?tenant=BETA").status_code == 403


def test_health_checks_require_auth_and_do_not_expose_rejected_data(request, monkeypatch):
    app, _, _ = request.getfixturevalue("platform")
    client = app.test_client()
    assert client.get("/__diag/validate?tenant=ALPHA").status_code == 401
    login(client)
    assert client.get("/__diag/validate?tenant=BETA").status_code == 403
    monkeypatch.setattr(type(app.container.storage), "validate_tenant", Mock(return_value={
        "tenant": "ALPHA", "files": {"catalog.json": {
            "exists": True, "valid": False, "error": "Invalid instance: sensitive-business-data"}}}))
    response = client.get("/__diag/validate?tenant=ALPHA")
    assert response.status_code == 200
    assert response.json["ok"] is False
    assert response.json["validation"]["files"]["catalog.json"]["valid"] is False
    assert "sensitive-business-data" not in response.text


def test_error_rows_use_label_and_count_and_scope_to_company(request):
    app, _, _ = request.getfixturevalue("platform")
    from service import analytics_db
    analytics_db.log_error(tenant="ALPHA", channel="web", session_id="alpha", error_code="provider_timeout")
    analytics_db.log_error(tenant="BETA", channel="web", session_id="beta", error_code="other_company_error")
    client = app.test_client()
    assert client.get("/admin/api/errors?tenant=ALPHA").status_code == 401
    login(client)
    response = client.get("/admin/api/errors?tenant=ALPHA&minutes=10080")
    assert response.status_code == 200
    assert response.json == [{"label": "provider_timeout", "count": 1}]
    assert client.get("/admin/api/errors?tenant=BETA").status_code == 403


def test_readiness_checks_database_but_liveness_stays_lightweight(client, monkeypatch):
    from service import session_store
    assert client.get('/ready').status_code == 200
    def unavailable():
        raise RuntimeError('synthetic database outage')
    monkeypatch.setattr(session_store, 'connection', unavailable)
    response = client.get('/ready')
    assert response.status_code == 503 and response.json == {'ready':False}
    assert 'synthetic' not in response.text
    assert client.get('/health').status_code == 200
