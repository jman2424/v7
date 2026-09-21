"""Real OAuth, MCP, storage and tenant-isolation regression coverage."""
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from service import analytics_db, mcp_auth
from service.audit import AuditService
from service.business_management import revision
from tests.test_platform_security import login, platform  # noqa: F401


@pytest.fixture
def mcp(request, monkeypatch):
    platform_data = request.getfixturevalue("platform")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://vertex.example")
    monkeypatch.setenv("MCP_OAUTH_CLIENTS", json.dumps({"test-client": {"redirect_uris": ["https://chatgpt.com/callback"]}}))
    return platform_data


def authorization(client, scope="business:read business:write"):
    verifier = "v" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    args = {"client_id": "test-client", "redirect_uri": "https://chatgpt.com/callback",
            "response_type": "code", "resource": "https://vertex.example/mcp", "scope": scope,
            "state": "state-for-this-request", "code_challenge": challenge, "code_challenge_method": "S256"}
    return "/oauth/authorize?" + urlencode(args), verifier, args


def issue(client, scope="business:read business:write"):
    csrf = login(client)
    url, verifier, args = authorization(client, scope)
    assert client.get(url).status_code == 200
    response = client.post(url, data={"csrf_token": csrf, "decision": "allow"})
    assert response.status_code == 303, response.text
    params = parse_qs(urlsplit(response.location).query)
    assert params["state"] == [args["state"]]
    form = {"grant_type": "authorization_code", "client_id": "test-client", "code": params["code"][0],
            "redirect_uri": args["redirect_uri"], "code_verifier": verifier, "resource": args["resource"]}
    response = client.post("/oauth/token", data=form)
    assert response.status_code == 200, response.text
    return response.json, form


def rpc(client, token, method="tools/call", params=None, **kwargs):
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": "2025-06-18", **kwargs.pop("headers", {})}
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=headers, **kwargs)


def call(client, token, name, args=None):
    response = rpc(client, token, params={"name": name, "arguments": args or {}})
    assert response.status_code == 200, response.text
    return response.json["result"]


def data(client, token, name, args=None):
    result = call(client, token, name, args)
    assert not result["isError"], result
    return result["structuredContent"]


def test_metadata_authentication_and_transport(mcp):
    client = mcp[0].test_client()
    assert client.get("/.well-known/oauth-protected-resource/mcp").json["resource"] == "https://vertex.example/mcp"
    assert client.get("/.well-known/oauth-authorization-server").json["code_challenge_methods_supported"] == ["S256"]
    denied = client.post("/mcp", json={})
    assert denied.status_code == 401
    assert "resource_metadata" in denied.headers["WWW-Authenticate"]
    tokens, _ = issue(client)
    token = tokens["access_token"]
    # A browser management session alone never authenticates MCP.
    assert client.post("/mcp", json={}).status_code == 401
    initialized = rpc(client, token, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "1"}, "capabilities": {}})
    assert initialized.json["result"]["protocolVersion"] == "2025-06-18"
    tools = rpc(client, token, "tools/list").json["result"]["tools"]
    assert len(tools) == 22
    assert all(t["inputSchema"]["additionalProperties"] is False for t in tools)
    assert rpc(client, token, "unknown").json["error"]["code"] == -32601
    assert rpc(client, token, headers={"Origin": "https://evil.test"}).status_code == 403
    assert rpc(client, token, headers={"MCP-Protocol-Version": "bogus"}).status_code == 400
    assert rpc(client, token, headers={"Accept": "text/html"}).status_code == 406
    assert client.get("/mcp", headers={"Authorization": "Bearer " + token}).status_code == 405


def test_oauth_pkce_redirect_replay_refresh_and_revocation(mcp):
    client = mcp[0].test_client()
    csrf = login(client)
    url, verifier, args = authorization(client)
    assert client.post(url, data={"decision": "allow"}).status_code == 403
    invalid = dict(args, redirect_uri="https://evil.test/callback")
    assert client.get("/oauth/authorize?" + urlencode(invalid)).status_code == 400
    invalid = dict(args, code_challenge_method="plain")
    assert client.get("/oauth/authorize?" + urlencode(invalid)).status_code == 400
    denied = client.post(url, data={"decision": "deny", "csrf_token": csrf})
    assert "error=access_denied" in denied.location
    allowed = client.post(url, data={"decision": "allow", "csrf_token": csrf})
    code = parse_qs(urlsplit(allowed.location).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "client_id": "test-client",
            "redirect_uri": args["redirect_uri"], "code_verifier": "x" * 50, "resource": args["resource"]}
    assert client.post("/oauth/token", data=form).status_code == 400
    form["code_verifier"] = verifier
    tokens = client.post("/oauth/token", data=form).json
    assert "access_token" in tokens
    assert client.post("/oauth/token", data=form).status_code == 400
    refresh = {"grant_type": "refresh_token", "client_id": "test-client", "refresh_token": tokens["refresh_token"], "resource": args["resource"]}
    assert client.post("/oauth/token", data={**refresh, "resource": "https://evil.test"}).status_code == 400
    new = client.post("/oauth/token", data=refresh)
    assert new.status_code == 200
    assert client.post("/oauth/token", data=refresh).status_code == 400
    assert client.post("/auth/mcp/revoke", json={}).status_code == 403
    assert client.post("/auth/mcp/revoke", json={}, headers={"X-CSRF-Token": csrf}).status_code == 200
    assert rpc(client, tokens["access_token"], "ping").status_code == 401
    assert rpc(client, new.json["access_token"], "ping").status_code == 401


def test_consent_login_without_existing_session(mcp):
    client = mcp[0].test_client()
    url, _, _ = authorization(client)
    response = client.get(url)
    assert '/console/platform' in response.text
    assert 'autocomplete="current-password"' not in response.text
    with client.session_transaction() as session:
        csrf = session["_csrf"]
    response = client.post(url, data={"csrf_token": csrf, "decision": "login", "email": "owner@example.test", "password": mcp[2]})
    assert response.status_code == 400
    login(client)
    assert 'Allow connection' in client.get(url).text


def test_tenant_isolation_all_reads_and_writes(mcp):
    app, registry, _ = mcp
    client = app.test_client()
    token = issue(client)[0]["access_token"]
    for tenant in ("ALPHA", "BETA"):
        analytics_db.log_message(tenant=tenant, channel="web", direction="inbound", session_id=tenant, text=tenant + " private")
        analytics_db.log_error(tenant=tenant, channel="web", session_id=tenant, error_code=tenant + " secret")
    catalog = data(client, token, "get_catalog")
    assert "Alpha laptop" in str(catalog) and "Beta tablet" not in str(catalog)
    assert data(client, token, "get_statistics")["kpis"]["inbound"] == 1
    assert data(client, token, "get_error_summary")["count"] == 1
    assert len(data(client, token, "get_recent_errors")["errors"]) == 1
    for name in ("get_catalog", "get_statistics", "get_offers", "get_users", "get_agent_health"):
        assert call(client, token, name, {"tenant": "BETA"})["isError"]
    assert call(client, token, "get_user_role", {"email": "admin@example.test"})["isError"]
    before = app.container.storage.read_json("BETA", "catalog.json")
    result = call(client, token, "update_catalog_item", {"category": "Devices", "name": "Beta tablet", "expected_revision": catalog["revision"], "changes": {"price": 1}})
    assert result["isError"]
    assert app.container.storage.read_json("BETA", "catalog.json") == before
    records = json.loads(registry.read_text())
    records["users"][1]["tenant"] = "BETA"
    registry.write_text(json.dumps(records))
    assert rpc(client, token, "ping").status_code == 401


def test_read_only_scope_cannot_write(mcp):
    client = mcp[0].test_client()
    token = issue(client, "business:read")[0]["access_token"]
    catalog = data(client, token, "get_catalog")
    names = [t["name"] for t in rpc(client, token, "tools/list").json["result"]["tools"]]
    assert "update_catalog_item" not in names
    result = call(client, token, "disable_catalog_item", {"category": "Devices", "name": "Alpha laptop", "expected_revision": catalog["revision"]})
    assert result["structuredContent"]["error"]["code"] == "forbidden"
    assert data(client, token, "get_catalog")["items"][0]["in_stock"] is True


@pytest.mark.parametrize("changes", [{"price": -1}, {"price": True}, {"price": 2.001}, {"price": float("nan")}, {"price": float("inf")}, {"price": "7.99"}, {"password": "bad"}, {}, {"name": " "}, {"price_str": "-9.99"}])
def test_invalid_catalogue_updates_rejected(mcp, changes):
    app = mcp[0]
    client = app.test_client()
    token = issue(client)[0]["access_token"]
    catalog = data(client, token, "get_catalog")
    result = call(client, token, "update_catalog_item", {"category": "Devices", "name": "Alpha laptop", "expected_revision": catalog["revision"], "changes": changes})
    assert result["isError"]
    assert data(client, token, "get_catalog")["revision"] == catalog["revision"]


def test_catalogue_actions_audit_conflict_and_dashboard_visibility(mcp):
    app = mcp[0]
    client = app.test_client()
    token = issue(client)[0]["access_token"]
    catalog = data(client, token, "get_catalog")
    updated = data(client, token, "update_catalog_item", {"category": "Devices", "name": "Alpha laptop", "expected_revision": catalog["revision"], "changes": {"price": 7.99}})
    assert updated["item"]["price"] == 7.99
    assert client.get("/files/raw/catalog.json").json["categories"][0]["items"][0]["price"] == 7.99
    stale = call(client, token, "disable_catalog_item", {"category": "Devices", "name": "Alpha laptop", "expected_revision": catalog["revision"]})
    assert stale["structuredContent"]["error"]["code"] == "conflict"
    added = data(client, token, "add_catalog_item", {"category": "Devices", "expected_revision": updated["revision"], "item": {"name": "New device", "price": 0.29}})
    disabled = data(client, token, "disable_catalog_item", {"category": "Devices", "name": "New device", "expected_revision": added["revision"]})
    assert disabled["item"]["in_stock"] is False
    assert data(client, token, "get_catalog")["total"] == 2
    from pathlib import Path
    entries = [json.loads(line) for line in Path("logs/selfrepair.log").read_text().splitlines()]
    successes = [e for e in entries if e["extra"]["result"] == "success"]
    assert {e["action"] for e in successes} == {"update_catalog_item", "add_catalog_item", "disable_catalog_item"}
    assert all(e["extra"]["tenant"] == "ALPHA" and e["extra"]["source"] == "ChatGPT MCP" for e in entries)
    assert "7.99" in str(entries)


def test_legacy_catalogue_preserves_format(mcp):
    app = mcp[0]
    doc = {"product_catalog": [{"name": "Meat", "items": [{"name": "Chicken", "price_str": "£8.99 / kg", "stock": "in stock"}]}]}
    app.container.storage.write_json("ALPHA", "catalog.json", doc)
    client = app.test_client()
    token = issue(client)[0]["access_token"]
    args = {"category": "Meat", "name": "Chicken", "expected_revision": revision(doc)}
    assert call(client, token, "update_catalog_item", {**args, "changes": {"price": 7.99}})["isError"]
    changed = data(client, token, "update_catalog_item", {**args, "changes": {"price_str": "£7.99 / kg"}})
    disabled = data(client, token, "disable_catalog_item", {**args, "expected_revision": changed["revision"]})
    assert disabled["item"]["stock"] == "out of stock"
    assert app.container.for_tenant("ALPHA").catalog.list_all_items()[0]["in_stock"] is False


def test_offer_actions_and_date_validation(mcp):
    client = mcp[0].test_client()
    token = issue(client)[0]["access_token"]
    offers = data(client, token, "get_offers")
    offer = {"title": "Weekend", "description": "Ask our team about this weekend's offer.", "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2027-01-01T00:00:00Z"}
    invalid = call(client, token, "create_offer", {"expected_revision": offers["revision"], "offer": {**offer, "ends_at": "2025-01-01T00:00:00Z"}})
    assert invalid["isError"]
    created = data(client, token, "create_offer", {"expected_revision": offers["revision"], "offer": offer})
    updated = data(client, token, "update_offer", {"offer_id": created["item"]["id"], "expected_revision": created["revision"], "changes": {"title": "Updated weekend"}})
    data(client, token, "disable_offer", {"offer_id": updated["item"]["id"], "expected_revision": updated["revision"]})
    assert data(client, token, "get_offers")["items"][0]["active"] is False
    from pathlib import Path
    entries = [json.loads(line) for line in Path("logs/selfrepair.log").read_text().splitlines()]
    assert {e["action"] for e in entries if e["extra"]["result"] == "success"} == {"create_offer", "update_offer", "disable_offer"}


def test_secrets_never_returned(mcp, monkeypatch):
    app = mcp[0]
    monkeypatch.setenv("WHATSAPP_TOKEN", "unique-secret-value-123")
    doc = app.container.storage.read_json("ALPHA", "catalog.json")
    doc["password_hash"] = "this-field-must-not-appear"
    doc["categories"][0]["items"][0]["name"] = "unique-secret-value-123"
    app.container.storage.write_json("ALPHA", "catalog.json", doc)
    client = app.test_client()
    token = issue(client)[0]["access_token"]
    analytics_db.log_error(tenant="ALPHA", channel="web", session_id="s", error_code="unique-secret-value-123", meta={"token": "another-secret"})
    for name in ("get_catalog", "get_users", "get_roles", "get_agent_health", "get_error_summary", "get_recent_errors"):
        result = call(client, token, name)
        assert "unique-secret-value-123" not in str(result)
        assert "password_hash" not in str(result)
        assert "another-secret" not in str(result)
        assert "this-field-must-not-appear" not in str(result)


def test_audit_failure_blocks_write(mcp, monkeypatch):
    client = mcp[0].test_client()
    token = issue(client)[0]["access_token"]
    catalog = data(client, token, "get_catalog")
    def fail(*args, **kwargs):
        raise OSError("private storage details")
    monkeypatch.setattr(AuditService, "record", fail)
    result = call(client, token, "disable_catalog_item", {"category": "Devices", "name": "Alpha laptop", "expected_revision": catalog["revision"]})
    assert result["structuredContent"]["error"]["code"] == "service_unavailable"
    assert "private storage details" not in str(result)
    assert data(client, token, "get_catalog")["revision"] == catalog["revision"]


def test_token_expiry_disabled_accounts_and_rate_limit(mcp):
    app, registry, _ = mcp
    client = app.test_client()
    token = issue(client)[0]["access_token"]
    with app.app_context(), mcp_auth.database() as db:
        db.execute("UPDATE mcp_grants SET expires=0 WHERE kind='access'")
    assert rpc(client, token, "ping").status_code == 401
    token = issue(client)[0]["access_token"]
    for _ in range(60):
        assert rpc(client, token, "ping").status_code == 200
    limited = rpc(client, token, "ping")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    records = json.loads(registry.read_text())
    records["users"][1]["disabled"] = True
    registry.write_text(json.dumps(records))
    assert rpc(client, token, "ping").status_code == 401


def test_explicit_statistics_windows(mcp):
    client = mcp[0].test_client()
    token = issue(client)[0]["access_token"]
    with analytics_db._conn() as db:
        for tenant, timestamp in [("ALPHA", "2026-09-01T00:00:00+00:00"),
                                   ("ALPHA", "2026-09-08T00:00:00+00:00"),
                                   ("BETA", "2026-09-01T00:00:00+00:00")]:
            db.execute("INSERT INTO events (tenant, ts_utc, channel, session_id, event_type) VALUES (?, ?, 'web', 'repeat-session', 'msg_in')", (tenant, timestamp))
    first = data(client, token, "get_statistics", {"start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-08T00:00:00Z"})
    second = data(client, token, "get_statistics", {"start_at": "2026-09-08T00:00:00Z", "end_at": "2026-09-15T00:00:00Z"})
    assert first["kpis"]["inbound"] == second["kpis"]["inbound"] == 1
    assert first["window_minutes"] == 10080
    assert first["daily"][0]["d"] == "2026-09-01"
    for args in [{"start_at": "2026-09-01T00:00:00Z"},
                 {"start_at": "2026-09-08T00:00:00Z", "end_at": "2026-09-01T00:00:00Z"},
                 {"start_at": "2026-01-01T00:00:00Z", "end_at": "2026-09-01T00:00:00Z"}]:
        assert call(client, token, "get_statistics", args)["structuredContent"]["error"]["code"] == "invalid_arguments"


def test_platform_admin_cannot_obtain_owner_grant(mcp):
    client = mcp[0].test_client()
    csrf = login(client, email="admin@example.test")
    url, _, _ = authorization(client)
    assert client.get(url).status_code == 403
    assert client.post(url, data={"decision": "allow", "csrf_token": csrf}).status_code == 403


def test_mcp_tokens_are_hashed_at_rest_and_client_removal_revokes(mcp, monkeypatch):
    app = mcp[0]
    client = app.test_client()
    tokens, form = issue(client)
    with app.app_context(), mcp_auth.database() as db:
        stored = str(db.execute("SELECT * FROM mcp_grants").fetchall())
    assert tokens["access_token"] not in stored
    assert tokens["refresh_token"] not in stored
    assert form["code"] not in stored
    monkeypatch.setenv("MCP_OAUTH_CLIENTS", "{}")
    assert rpc(client, tokens["access_token"], "ping").status_code != 200


def test_production_oauth_requires_matching_https_cookie_configuration(mcp):
    app = mcp[0]
    app.config["TESTING"] = False
    assert app.test_client().get("/.well-known/oauth-authorization-server").status_code == 503


def test_write_notification_is_not_executed(mcp):
    client = mcp[0].test_client()
    token = issue(client)[0]["access_token"]
    catalogue = data(client, token, "get_catalog")
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/call", "params": {
        "name": "disable_catalog_item", "arguments": {"category": "Devices", "name": "Alpha laptop", "expected_revision": catalogue["revision"]}}},
        headers={"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"})
    assert response.status_code == 400
    assert data(client, token, "get_catalog")["revision"] == catalogue["revision"]
