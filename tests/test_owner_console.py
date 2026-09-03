from __future__ import annotations


def test_owner_console_serves_compiled_assets_from_same_origin(client, app, tmp_path):
    build_dir = tmp_path / "owner-console"
    asset_dir = build_dir / "_app" / "immutable"
    asset_dir.mkdir(parents=True)
    (build_dir / "index.html").write_text("<main>V7 owner console</main>", encoding="utf-8")
    (asset_dir / "app.js").write_text("console.log('console');", encoding="utf-8")
    app.config["OWNER_CONSOLE_DIR"] = str(build_dir)

    page = client.get("/console")
    asset = client.get("/console/_app/immutable/app.js")
    missing = client.get("/console/missing.js")

    assert page.status_code == 200
    assert page.get_data(as_text=True) == "<main>V7 owner console</main>"
    assert page.headers["Cache-Control"] == "no-store"
    assert asset.status_code == 200
    assert asset.get_data(as_text=True) == "console.log('console');"
    assert missing.status_code == 404
