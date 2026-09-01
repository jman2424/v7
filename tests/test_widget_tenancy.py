from __future__ import annotations

import json
import shutil
from pathlib import Path


def _add_tenant(app, name: str = "ALT") -> None:
    business_root = Path(app.container.storage.business_root)
    source = business_root / "EXAMPLE"
    target = business_root / name
    if not target.exists():
        shutil.copytree(source, target)


def _as_platform_admin(client, tenant: str = "EXAMPLE") -> None:
    with client.session_transaction() as sess:
        sess["user"] = {"id": "platform", "roles": ["platform_admin"], "tenant": tenant}


def test_chat_api_uses_the_requested_tenant_runtime(client, app):
    _add_tenant(app)

    default_container = app.container.for_tenant("EXAMPLE")
    alternate_container = app.container.for_tenant("ALT")
    default_container.handler.handle = lambda *_args, **_kwargs: {"reply": "example reply", "intent": "faq"}
    alternate_container.handler.handle = lambda *_args, **kwargs: {
        "reply": f"alternate reply for {kwargs['tenant']}",
        "intent": "faq",
    }

    response = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "ALT", "message": "hello", "session_id": "tenant-test"}),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.get_json()["reply"] == "alternate reply for ALT"


def test_chat_api_rejects_path_like_tenant_values(client):
    response = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "../../EXAMPLE", "message": "hello"}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 404
    assert response.get_json()["error"] == "unknown_tenant"


def test_chat_api_only_returns_cors_headers_for_tenant_allowlist(client, app):
    storage = app.container.storage
    branding = storage.read_json("EXAMPLE", "branding.json")
    branding["widget"]["allowed_origins"] = ["https://www.example.test"]
    storage.write_json("EXAMPLE", "branding.json", branding, snapshot=False)

    app.container.handler.handle = lambda *_args, **_kwargs: {"reply": "ok", "intent": "faq"}
    allowed = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "EXAMPLE", "message": "hello"}),
        headers={"Content-Type": "application/json", "Origin": "https://www.example.test"},
    )
    denied = client.post(
        "/chat_api",
        data=json.dumps({"tenant": "EXAMPLE", "message": "hello"}),
        headers={"Content-Type": "application/json", "Origin": "https://other.example.test"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://www.example.test"
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "origin_forbidden"


def test_embed_script_and_hosted_chat_are_tenant_scoped(client):
    script = client.get("/widget.js?tenant=EXAMPLE")
    chat = client.get("/chat_ui?tenant=EXAMPLE&embed=1")

    assert script.status_code == 200
    assert script.mimetype == "application/javascript"
    assert '"tenant": "EXAMPLE"' in script.get_data(as_text=True)
    assert "/chat_ui?tenant=" in script.get_data(as_text=True)
    assert chat.status_code == 200
    assert "Example Butchers Assistant" in chat.get_data(as_text=True)
    assert "frame-ancestors" in chat.headers["Content-Security-Policy"]


def test_business_owner_cannot_request_another_tenant_admin_data(client, app):
    _add_tenant(app)
    with client.session_transaction() as sess:
        sess["user"] = {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"}

    response = client.get("/admin/api/catalog?tenant=ALT")
    assert response.status_code == 403


def test_widget_settings_are_saved_by_an_authorized_owner(client):
    _as_platform_admin(client)
    payload = {
        "chat_title": "Example sales team",
        "greeting": "Ask us about today's cuts.",
        "avatar": "https://assets.example.test/avatar.png",
        "allowed_origins": ["https://www.example.test", "http://localhost:5173"],
    }
    response = client.put("/admin/api/widget", json=payload)

    assert response.status_code == 200
    body = response.get_json()
    assert body["widget"]["chat_title"] == payload["chat_title"]
    assert body["widget"]["allowed_origins"] == payload["allowed_origins"]
    assert "widget.js?tenant=EXAMPLE" in body["embed"]["snippet"]


def test_platform_operator_can_create_a_clean_starter_tenant(client):
    _as_platform_admin(client)
    response = client.post("/admin/api/tenants", json={"key": "NORTHSTAR", "name": "Northstar Homewares"})

    assert response.status_code == 201
    created = response.get_json()["tenant"]
    assert created["key"] == "NORTHSTAR"
    assert created["valid"] is True

    tenants = client.get("/admin/api/tenants").get_json()["tenants"]
    northstar = next(tenant for tenant in tenants if tenant["key"] == "NORTHSTAR")
    assert northstar["name"] == "Northstar Homewares"
    assert northstar["widget_configured"] is False


def test_business_owner_cannot_onboard_tenants(client):
    with client.session_transaction() as sess:
        sess["user"] = {"id": "owner", "roles": ["business_owner"], "tenant": "EXAMPLE"}

    response = client.post("/admin/api/tenants", json={"key": "OTHER", "name": "Other Company"})
    assert response.status_code == 403
