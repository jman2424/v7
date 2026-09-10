"""
Global test fixtures for AI Sales Assistant repo.

Creates an isolated Flask app, in-memory tenant sandbox, and
injects lightweight stubs for external connectors so tests
don’t hit network APIs.
"""

from __future__ import annotations
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any
import pytest
from flask.testing import FlaskClient
from werkzeug.security import generate_password_hash


class CsrfClient(FlaskClient):
    """Exercise real CSRF checks with the token a browser would submit."""
    def open(self, *args, **kwargs):
        if kwargs.get("method", "GET").upper() not in {"GET", "HEAD", "OPTIONS"}:
            with self.session_transaction() as state:
                token = state.get("_csrf")
            if not token:
                token = super().get("/auth/session").get_json()["csrf_token"]
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-CSRF-Token", token)
            kwargs["headers"] = headers
        return super().open(*args, **kwargs)


def set_test_identity(client, state, user):
    """Seed a real server session for route-permission unit tests."""
    from service.security import _revision
    from service import session_store
    identity = dict(user)
    roles = identity.get("roles") or [identity.get("role", "business_owner")]
    identity.update(roles=roles, id=identity.get("id") or identity.get("username") or "test",
                    email=identity.get("email") or str(identity.get("id") or "test") + "@example.test",
                    tenant=identity.get("tenant") or "EXAMPLE")
    with client.application.app_context():
        revision = _revision(identity)
        if not revision:
            registry = Path(os.environ["ADMIN_USERS_FILE"])
            data = json.loads(registry.read_text())
            data["users"] = [r for r in data["users"] if r["email"] != identity["email"]]
            data["users"].append({"email": identity["email"], "role": roles[0], "tenant": identity["tenant"],
                                  "password_hash": generate_password_hash("Unit-test-password-only")})
            registry.write_text(json.dumps(data))
            revision = _revision(identity)
        assert revision
        state["user"] = identity
        state["management_token"] = session_store.create(identity, revision)

# ---------------------------------------------------------------------------
# Import target app
# ---------------------------------------------------------------------------
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # type: ignore
from retrieval.storage import Storage  # type: ignore

# ---------------------------------------------------------------------------
# Pytest Hooks
# ---------------------------------------------------------------------------

def pytest_configure(config):
    """Called once per test run."""
    os.environ.setdefault("MODE", "V7")
    os.environ.setdefault("BUSINESS_KEY", "EXAMPLE")
    os.environ.setdefault("TESTING", "1")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def root_dir() -> Path:
    """Root of repo."""
    return ROOT


@pytest.fixture(scope="session")
def tenant_key() -> str:
    return "EXAMPLE"


@pytest.fixture()
def tmp_business(tmp_path: Path, tenant_key: str, root_dir: Path):
    """
    Copies business/EXAMPLE/* into tempdir for destructive tests.
    Returns the new path.
    """
    src = root_dir / "business" / tenant_key
    dst = tmp_path / "business" / tenant_key
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.json"):
        dst.joinpath(f.name).write_text(f.read_text("utf-8"), encoding="utf-8")
    yield dst


@pytest.fixture()
def app(tmp_business: Path, monkeypatch):
    """
    Flask app fixture (testing mode ON).
    Uses temp business path and disables external connectors.
    """
    monkeypatch.setenv("BUSINESS_KEY", "EXAMPLE")
    monkeypatch.setenv("MODE", "V7")
    monkeypatch.setenv("TESTING", "1")

    # Redirect business path for this test run
    monkeypatch.chdir(tmp_business.parent.parent)

    from service import analytics_db
    monkeypatch.setattr(analytics_db, "DB_PATH", str(tmp_business.parent.parent / "analytics.db"))
    monkeypatch.setattr(analytics_db, "_INIT_DONE", False)
    monkeypatch.setenv("ANALYTICS_DB_PATH", analytics_db.DB_PATH)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_business.parent.parent / "security.db"))
    registry = tmp_business.parent.parent / "test-accounts.json"
    registry.write_text('{"users": []}')
    monkeypatch.setenv("ADMIN_USERS_FILE", str(registry))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    flask_app = create_app({"TESTING": True, "SECRET_KEY": "test-secret-" * 4})
    flask_app.test_client_class = CsrfClient
    flask_app.config.update(
        TESTING=True,
        SERVER_NAME="localhost",
        BUSINESS_PATH=str(tmp_business),
    )
    yield flask_app


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture()
def storage(tmp_business: Path):
    """Returns a Storage instance using tmp tenant data."""
    s = Storage(base_dir=tmp_business.parent)
    yield s


@pytest.fixture()
def mock_catalog(storage):
    """Parsed catalog.json content for direct access."""
    return storage.load_json("EXAMPLE/catalog.json")


@pytest.fixture()
def mock_request():
    """Simulated WhatsApp webhook or webchat message payload."""
    return {
        "message": "show me chicken",
        "channel": "test",
        "user_id": "u123",
        "session_id": "s123"
    }


@pytest.fixture()
def mock_mode(monkeypatch):
    """Stub AI mode that echoes inputs for deterministic unit tests."""
    class DummyMode:
        def generate_reply(self, context: Dict[str, Any]) -> Dict[str, Any]:
            return {"reply": f"echo: {context.get('message', '')}"}

    monkeypatch.setattr("ai_modes.v7_flagship.Mode", DummyMode)
    yield DummyMode


@pytest.fixture()
def dummy_lead():
    """Sample CRM lead record."""
    return {
        "name": "John Doe",
        "phone": "+44 7000 000000",
        "email": "john@example.com",
        "tags": ["test"],
        "status": "new"
    }


@pytest.fixture()
def json_headers():
    return {"Content-Type": "application/json"}
