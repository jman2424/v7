"""Real account snapshots, MFA reuse, permissions and OAuth connection isolation."""
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest
from flask import Flask, session
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import HTTPException

from retrieval.storage import Storage
from service import account_mfa, mcp_auth, security, session_store
from service.account_service import ACCOUNT_FILE, AccountService


@pytest.fixture(scope="module")
def password_hash():
    return security.hash_password("Test-only-password-42!")


@pytest.fixture
def auth_context(tmp_path, monkeypatch, password_hash):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("V7_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.db"))
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://vertex.example")
    monkeypatch.setenv("MCP_OAUTH_CLIENTS", json.dumps({"test-client": {"redirect_uris": ["https://client.example/callback"]}}))
    for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_PASSWORD_HASH", "ADMIN_TOTP_SECRET", "BUSINESS_USERS_JSON"):
        monkeypatch.delenv(key, raising=False)
    registry = tmp_path / "accounts.json"
    registry.write_text(json.dumps({"users": [{"email": "owner@example.test", "password_hash": password_hash,
        "role": "business_owner", "tenant": "COMPANY_A", "totp_secret": "JBSWY3DPEHPK3PXP"}]}))
    monkeypatch.setenv("ADMIN_USERS_FILE", str(registry))
    app = Flask(__name__)
    app.testing = True
    app.secret_key = "test-only-session-secret-" * 2
    storage = Storage("COMPANY_A", business_root=tmp_path / "business")
    storage.tenant_dir().mkdir(parents=True)
    app.container = SimpleNamespace(settings=SimpleNamespace(BASE_URL="http://localhost"), storage=storage)
    with app.test_request_context():
        yield app, registry


def update_account(registry, changes):
    data = json.loads(registry.read_text())
    data["users"][0].update(changes)
    registry.write_text(json.dumps(data))


def authenticated(app):
    return security.authenticate_user(app.container, email="owner@example.test", password="Test-only-password-42!", tenant="COMPANY_A")


@pytest.mark.parametrize("changes", [{"password_hash": "scrypt:changed"}, {"tenant": "COMPANY_B"},
    {"permissions": []}, {"role": "platform_admin", "tenant": None}, {"totp_secret": "GEZDGNBVGY3TQOJQ"}, {"disabled": True}])
def test_account_change_during_password_check_cannot_create_session(auth_context, monkeypatch, changes):
    app, registry = auth_context
    original = security._verify_password

    def verify_then_change(password, hashed):
        valid = original(password, hashed)
        update_account(registry, changes)
        return valid

    monkeypatch.setattr(security, "_verify_password", verify_then_change)
    user = authenticated(app)
    assert user is not None
    with pytest.raises(HTTPException) as rejected:
        security.start_management_session(user, "COMPANY_A", mfa_verified=True)
    assert rejected.value.code == 401
    assert not session.get("management_token")
    with pytest.raises(ValueError, match="account_unavailable"):
        account_mfa.begin(user, "COMPANY_A")


def test_password_change_between_session_check_and_consent_cannot_issue_grant(auth_context):
    app, registry = auth_context
    security.start_management_session(authenticated(app), "COMPANY_A", mfa_verified=True)
    identity = security.management_user()
    update_account(registry, {"password_hash": "scrypt:changed"})
    with pytest.raises(HTTPException) as rejected:
        mcp_auth.authorize({"resource": mcp_auth.resource()}, identity)
    assert rejected.value.code == 401
    with mcp_auth.database() as db:
        assert db.execute("SELECT COUNT(*) FROM mcp_grants").fetchone()[0] == 0


def test_password_change_after_consent_recheck_does_not_issue_grant(auth_context, monkeypatch):
    app, registry = auth_context
    security.start_management_session(authenticated(app), "COMPANY_A", mfa_verified=True)
    identity = security.management_user()
    original = mcp_auth.management_user

    def checked_then_change():
        checked = original()
        update_account(registry, {"password_hash": "scrypt:changed"})
        return checked

    monkeypatch.setattr(mcp_auth, "management_user", checked_then_change)
    with pytest.raises(HTTPException) as rejected:
        mcp_auth.authorize({"resource": mcp_auth.resource()}, identity)
    assert rejected.value.code == 401


def test_mfa_code_is_single_use_across_direct_and_challenge_login(auth_context, monkeypatch):
    app, _ = auth_context
    monkeypatch.setattr(security.time, "time", lambda: 1800000000)
    user = authenticated(app)
    account_mfa.begin(user, "COMPANY_A")
    code = security.pyotp.TOTP(user["totp_secret"]).at(1800000000)
    verified = account_mfa.confirm(code)
    security.start_management_session(verified, "COMPANY_A", mfa_verified=True)
    assert not security.verify_totp(user["totp_secret"], code, identity=account_mfa.account_key(user))
    account_mfa.begin(authenticated(app), "COMPANY_A")
    with pytest.raises(ValueError, match="authenticator_code_reused"):
        account_mfa.confirm(code)


def test_password_change_during_mfa_confirmation_cannot_create_session(auth_context, monkeypatch):
    app, registry = auth_context
    user = authenticated(app)
    account_mfa.begin(user, "COMPANY_A")
    original = account_mfa._execute

    def delete_then_change(db, sql, params=()):
        result = original(db, sql, params)
        if sql == 'DELETE FROM mfa_challenges WHERE token=?':
            update_account(registry, {"password_hash": "scrypt:changed"})
        return result

    monkeypatch.setattr(account_mfa, "_execute", delete_then_change)
    verified = account_mfa.confirm(security.generate_totp_token(user["totp_secret"]))
    with pytest.raises(HTTPException) as rejected:
        security.start_management_session(verified, "COMPANY_A", mfa_verified=True)
    assert rejected.value.code == 401
    assert not session.get("management_token")


@pytest.mark.parametrize("role", [[], {}, 1, None])
def test_malformed_registry_roles_fail_closed(auth_context, role):
    app, registry = auth_context
    update_account(registry, {"role": role})
    assert authenticated(app) is None
    assert not security.has_permission({"roles": [role]}, "offerings.read")


@pytest.mark.parametrize("permissions", [["platform.read"], ["unknown"], [1], "offerings.read"])
def test_invalid_owner_permissions_fail_closed(auth_context, permissions):
    app, registry = auth_context
    update_account(registry, {"permissions": permissions})
    assert authenticated(app) is None


def test_private_credential_proof_does_not_enter_public_session(auth_context):
    app, _ = auth_context
    identity = security.start_management_session(authenticated(app), "COMPANY_A", mfa_verified=True)
    assert not any(key.startswith("_") for key in identity)
    assert not any(key.startswith("_") for key in session["user"])


def test_legacy_owner_defaults_and_new_owner_permission_subset(auth_context):
    app, _ = auth_context
    accounts = AccountService(app.container.storage)
    owner = accounts.create_account("COMPANY_A", {"email": "tenant@example.test", "password": "Test-only-password-42!", "roles": ["business_owner"]})
    user = security.authenticate_user(app.container, email=owner["email"], password="Test-only-password-42!", tenant="COMPANY_A")
    assert security.has_permission(user, "offerings.write")
    accounts.update_account("COMPANY_A", owner["id"], {"permissions": ["offerings.read"]})
    user = security.authenticate_user(app.container, email=owner["email"], password="Test-only-password-42!", tenant="COMPANY_A")
    assert security.has_permission(user, "offerings.read")
    assert not security.has_permission(user, "offerings.write")


def test_staff_permissions_are_explicit_and_cannot_grant_platform_access(auth_context):
    app, _ = auth_context
    service = AccountService(app.container.storage)
    staff = service.create_account("COMPANY_A", {"email": "staff@example.test", "password": "Test-only-password-42!", "roles": ["business_staff"]})
    user = security.authenticate_user(app.container, email=staff["email"], password="Test-only-password-42!", tenant="COMPANY_A")
    assert not security.has_permission(user, "offerings.read")
    service.update_account("COMPANY_A", staff["id"], {"permissions": ["offerings.read", "view_costs"]})
    user = security.authenticate_user(app.container, email=staff["email"], password="Test-only-password-42!", tenant="COMPANY_A")
    assert security.has_permission(user, "offerings.read")
    assert security.has_permission(user, "view_costs")
    with pytest.raises(ValueError, match="invalid_account_permissions"):
        service.update_account("COMPANY_A", staff["id"], {"permissions": ["platform.read"]})


def test_invalid_tenant_account_role_is_not_promoted(auth_context):
    app, _ = auth_context
    app.container.storage._write_json("COMPANY_A", ACCOUNT_FILE, [{"id": "bad", "email": "bad@example.test",
        "password_hash": security.hash_password("Test-only-password-42!"), "roles": ["platform_admin"]}])
    assert security.authenticate_user(app.container, email="bad@example.test", password="Test-only-password-42!", tenant="COMPANY_A") is None


def test_environment_owner_without_tenant_cannot_follow_a_requested_company(auth_context, monkeypatch, password_hash):
    app, _ = auth_context
    record = {"email": "environment@example.test", "password_hash": password_hash, "roles": ["business_owner"]}
    monkeypatch.setenv("BUSINESS_USERS_JSON", json.dumps([record]))
    assert security.authenticate_user(app.container, email=record["email"], password="Test-only-password-42!", tenant="COMPANY_A") is None
    record["tenant"] = "COMPANY_A"
    monkeypatch.setenv("BUSINESS_USERS_JSON", json.dumps([record]))
    assert security.authenticate_user(app.container, email=record["email"], password="Test-only-password-42!", tenant="COMPANY_A") is not None
    assert security.authenticate_user(app.container, email=record["email"], password="Test-only-password-42!", tenant="COMPANY_B") is None


@pytest.mark.parametrize("roles", [[], None, "business_owner", ["unknown"], [{}]])
def test_explicit_malformed_tenant_roles_do_not_default_to_owner(auth_context, roles, password_hash):
    app, _ = auth_context
    app.container.storage._write_json("COMPANY_A", ACCOUNT_FILE, [{"id": "bad", "email": "bad@example.test",
        "password_hash": password_hash, "roles": roles}])
    assert security.authenticate_user(app.container, email="bad@example.test", password="Test-only-password-42!", tenant="COMPANY_A") is None


def test_reenabled_account_does_not_resurrect_an_unused_old_session(auth_context):
    app, _ = auth_context
    service = AccountService(app.container.storage)
    owner = service.create_account("COMPANY_A", {"email": "tenant@example.test", "password": "Test-only-password-42!", "roles": ["business_owner"]})
    records = app.container.storage.read_json("COMPANY_A", ACCOUNT_FILE)
    records[0]["totp_secret"] = "JBSWY3DPEHPK3PXP"
    app.container.storage._write_json("COMPANY_A", ACCOUNT_FILE, records)
    user = security.authenticate_user(app.container, email=owner["email"], password="Test-only-password-42!", tenant="COMPANY_A")
    security.start_management_session(user, "COMPANY_A", mfa_verified=True)
    service.update_account("COMPANY_A", owner["id"], {"active": False})
    service.update_account("COMPANY_A", owner["id"], {"active": True})
    with pytest.raises(HTTPException) as rejected:
        security.management_user()
    assert rejected.value.code == 401


def test_authorized_analytics_tenant_checks_repository_aliases(auth_context, monkeypatch):
    app, _ = auth_context
    security.start_management_session(authenticated(app), "COMPANY_A", mfa_verified=True)

    def reject_alias(self, tenant):
        raise ValueError("private-storage-details")

    monkeypatch.setattr(type(app.container.storage), "tenant_exists", reject_alias)
    with pytest.raises(HTTPException) as rejected:
        security.authorized_tenant()
    assert rejected.value.code == 403
    assert "private-storage-details" not in rejected.value.description


def test_owner_can_still_select_an_additional_owned_tenant(auth_context):
    app, _ = auth_context
    from service import tenant_access
    identity = security.start_management_session(authenticated(app), "COMPANY_A", mfa_verified=True)
    app.container.storage.tenant_dir("COMPANY_B").mkdir()
    tenant_access.register("COMPANY_B", identity)
    assert security.authorized_tenant("COMPANY_B") == "COMPANY_B"


def issue(identity):
    verifier = "v" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    data = {"client_id": "test-client", "resource": mcp_auth.resource(), "scope": "business:read",
            "redirect_uri": "https://client.example/callback", "code_challenge": challenge}
    code = mcp_auth.authorize(data, identity)
    return mcp_auth.exchange(MultiDict({"grant_type": "authorization_code", "client_id": "test-client", "resource": data["resource"],
        "code": code, "redirect_uri": data["redirect_uri"], "code_verifier": verifier}))


def test_individual_connection_revocation_is_owner_scoped(auth_context):
    app, _ = auth_context
    identity = security.start_management_session(authenticated(app), "COMPANY_A", mfa_verified=True)
    first, second = issue(identity), issue(identity)
    connections = mcp_auth.owner_connections(identity)
    assert len(connections) == 2
    assert all(len(item["connection_id"]) == 32 for item in connections)
    assert "access_token" not in json.dumps(connections)
    mcp_auth.revoke_owner(identity, connections[0]["connection_id"])
    assert len(mcp_auth.owner_connections(identity)) == 1
    statuses = []
    for token in (first["access_token"], second["access_token"]):
        try:
            mcp_auth.authenticate("Bearer " + token)
            statuses.append(200)
        except HTTPException as error:
            statuses.append(error.code)
    assert sorted(statuses) == [200, 401]


def test_postgres_totp_steps_are_single_use(pg_runtime):
    account = "native-totp-" + pg_runtime["tenant"]
    assert session_store.consume_totp(account, "test-only-normalized-secret", 500)
    assert not session_store.consume_totp(account, "test-only-normalized-secret", 500)
    assert not session_store.consume_totp(account, "test-only-normalized-secret", 499)
    assert session_store.consume_totp(account, "test-only-normalized-secret", 501)
    key = session_store._digest(account + ":test-only-normalized-secret")
    assert pg_runtime["admin"].execute("SELECT step FROM v7_private.totp_steps WHERE account_hash=%s", (key,)).fetchone()[0] == 501
