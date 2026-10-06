from __future__ import annotations

import re
import pytest
from urllib.parse import parse_qs, urlsplit

from routes.owner_console_routes import SECTIONS
from service import session_store
from service.account_service import AccountService
from service.tenant_service import TenantService
from tests.conftest import set_test_identity


@pytest.fixture
def compiled_console(app, tmp_path):
    build_dir = tmp_path / 'compiled-console'
    build_dir.mkdir()
    for section in SECTIONS | {'index'}:
        (build_dir / (section+'.html')).write_text('<main>Console</main><script>start()</script>', encoding='utf-8')
    (build_dir / 'unknown.html').write_text('<main>Unlisted private page</main>', encoding='utf-8')
    app.config['OWNER_CONSOLE_DIR'] = str(build_dir)
    return build_dir


def sign_in(client, role='business_owner', tenant='EXAMPLE', permissions=None):
    if role == 'business_staff':
        account = AccountService(client.application.container.storage).create_account(tenant, {
            'email': 'console-staff@example.test', 'password': 'Console-staff-test-password-123',
            'roles': [role], 'permissions': permissions or [],
        })
        identity = {**account, 'tenant': tenant}
    else:
        identity = {'id': 'console-operator', 'roles': [role], 'tenant': tenant}
    with client.session_transaction() as state:
        set_test_identity(client, state, identity)


def test_owner_console_serves_compiled_assets_from_same_origin(client, app, tmp_path):
    build_dir = tmp_path / "owner-console"
    asset_dir = build_dir / "_app" / "immutable"
    asset_dir.mkdir(parents=True)
    (build_dir / "index.html").write_text("<main>V7 owner console</main>", encoding="utf-8")
    (asset_dir / "app.js").write_text("console.log('console');", encoding="utf-8")
    app.config["OWNER_CONSOLE_DIR"] = str(build_dir)

    redirect = client.get("/console")
    page = client.get("/console/")
    asset = client.get("/console/_app/immutable/app.js")
    missing = client.get("/console/missing.js")

    assert redirect.status_code == 308
    assert redirect.headers["Location"] == "/console/"
    assert page.status_code == 200
    assert page.get_data(as_text=True) == "<main>V7 owner console</main>"
    assert page.headers["Cache-Control"] == "no-store"
    assert client.get('/console/index.html').status_code == 200
    assert asset.status_code == 200
    assert asset.get_data(as_text=True) == "console.log('console');"
    assert missing.status_code == 404


@pytest.mark.parametrize("section", ["errors", "subscription", "platform", "catalog", "conversations", "test", "usage", "implementation", "whatsapp-qr", "statistics"])
def test_console_deep_links_keep_nonce_protected_bootstrap(client, app, tmp_path, section):
    sign_in(client, 'platform_admin')
    build_dir = tmp_path / "console-pages"
    build_dir.mkdir()
    (build_dir / f"{section}.html").write_text('<main>Console</main><script>start()</script>', encoding="utf-8")
    app.config["OWNER_CONSOLE_DIR"] = str(build_dir)
    response = client.get(f"/console/{section}")
    assert response.status_code == 200
    nonce = re.search(r'<script nonce="([^"]+)"', response.text).group(1)
    assert "'nonce-" + nonce + "'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/console/unrecognised").status_code == 404
    assert client.get("/console/%2e%2e/AGENTS.md").status_code == 404


def test_console_microphone_policy_is_limited_to_widget_and_test_pages(client, app, tmp_path):
    sign_in(client)
    app.config["OWNER_CONSOLE_DIR"] = str(tmp_path)
    for name in ("test", "website", "profile", "statistics"):
        (tmp_path / f"{name}.html").write_text("<main>Console</main>", encoding="utf-8")
    for path in ("/chat_ui", "/console/test", "/console/test/", "/console/test.html",
                 "/console/website", "/console/website/", "/console/website.html"):
        assert "microphone=(self)" in client.get(path).headers["Permissions-Policy"]
    for path in ("/console/profile", "/console/statistics", "/console/", "/"):
        assert "microphone=()" in client.get(path).headers["Permissions-Policy"]


@pytest.mark.parametrize('section', sorted(SECTIONS))
def test_private_console_sections_redirect_anonymous_users_to_safe_sign_in(client, compiled_console, section):
    response = client.get('/console/'+section+'?tenant=example&next=https://external.example')
    assert response.status_code == 303
    location = urlsplit(response.headers['Location'])
    assert not location.scheme and not location.netloc and location.path == '/console/'
    assert parse_qs(location.query) == {'next': [section], 'tenant': ['EXAMPLE']}
    assert 'Console</main>' not in response.text


@pytest.mark.parametrize('alias', ['catalog.html', 'catalog.HTML', 'CATALOG', 'catalog.html/.', 'catalog.html/'])
def test_html_and_filesystem_aliases_keep_private_console_protection(client, compiled_console, alias):
    assert client.get('/console/'+alias).status_code == 303


def test_unlisted_html_and_traversal_cannot_expose_private_pages(client, compiled_console):
    assert client.get('/console/unknown.html').status_code == 404
    assert client.get('/console/%2e%2e/AGENTS.md').status_code == 404
    assert client.get('/console/catalog?tenant=https://external.example').status_code == 400
    assert client.get('/console/catalog?tenant=../../EXAMPLE').status_code == 400


@pytest.mark.parametrize('role', ['business_owner', 'business_staff'])
def test_platform_console_requires_platform_operator(client, compiled_console, role):
    sign_in(client, role)
    assert client.get('/console/platform').status_code == 403
    assert client.get('/console/platform.html').status_code == 403


@pytest.mark.parametrize('section', ['team', 'companies'])
def test_team_and_company_sections_require_owner_or_operator(client, compiled_console, section):
    sign_in(client, 'business_staff')
    assert client.get('/console/'+section).status_code == 403
    sign_in(client, 'business_owner')
    assert client.get('/console/'+section).status_code == 200
    sign_in(client, 'platform_admin')
    assert client.get('/console/'+section).status_code == 200


@pytest.mark.parametrize('permissions', [[], ['view_costs'], ['view_subscriptions'], ['view_costs', 'view_subscriptions']])
def test_staff_console_sections_follow_current_account_permissions(client, compiled_console, permissions):
    sign_in(client, 'business_staff', permissions=permissions)
    assert client.get('/console/usage').status_code == (200 if 'view_costs' in permissions else 403)
    assert client.get('/console/subscription.html').status_code == (200 if 'view_subscriptions' in permissions else 403)
    assert client.get('/console/pipeline').status_code == 200
    assert client.get('/console/account').status_code == 200
    assert client.get('/console/privacy.html').status_code == 200


def test_console_tenant_selection_uses_the_authenticated_assignment(client, compiled_console):
    TenantService(client.application.container.storage).create_tenant('OTHER', 'Inactive other test business')
    sign_in(client, tenant='OTHER')
    # No URL tenant chooses the signed account's home, not the app default.
    assert client.get('/console/catalog').status_code == 200
    assert client.get('/console/privacy?tenant=other').status_code == 200
    assert client.get('/console/account?tenant=EXAMPLE').status_code == 403
    assert client.get('/console/catalog?tenant=EXAMPLE').status_code == 403
    sign_in(client, 'platform_admin')
    assert client.get('/console/catalog?tenant=OTHER').status_code == 200
    assert client.get('/console/account?tenant=MissingCo').status_code == 404


def test_revoked_console_session_redirects_to_sign_in(client, compiled_console):
    sign_in(client)
    with client.session_transaction() as state:
        session_store.revoke(state['management_token'])
    assert client.get('/console/account.html').status_code == 303
