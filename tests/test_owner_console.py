from __future__ import annotations

import re
import pytest


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
    assert asset.status_code == 200
    assert asset.get_data(as_text=True) == "console.log('console');"
    assert missing.status_code == 404


@pytest.mark.parametrize("section", ["catalog", "conversations", "test", "usage", "implementation"])
def test_console_deep_links_keep_nonce_protected_bootstrap(client, app, tmp_path, section):
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


def test_console_microphone_policy_is_limited_to_test_page(client, app, tmp_path):
    app.config["OWNER_CONSOLE_DIR"] = str(tmp_path)
    for name in ("test", "profile"):
        (tmp_path / f"{name}.html").write_text("<main>Console</main>", encoding="utf-8")
    assert "microphone=(self)" in client.get("/console/test").headers["Permissions-Policy"]
    assert "microphone=()" in client.get("/console/profile").headers["Permissions-Policy"]
