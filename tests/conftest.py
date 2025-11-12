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

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
        SECRET_KEY="test-secret",
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
