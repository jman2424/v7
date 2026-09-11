from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, g, make_response, redirect, send_from_directory


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD_DIR = REPO_ROOT / "frontend" / "build"

bp = Blueprint("owner_console", __name__)


def _build_dir() -> Path:
    configured = current_app.config.get("OWNER_CONSOLE_DIR")
    return Path(configured) if configured else DEFAULT_BUILD_DIR


def _serve_console(asset_path: str = ""):
    build_dir = _build_dir().resolve()
    if not build_dir.is_dir():
        abort(404, description="owner_console_not_available")

    requested = asset_path or "index.html"
    screens = {"pipeline", "test", "usage", "conversations", "agent", "website", "integrations", "catalog", "offers", "faqs", "delivery", "profile", "branches", "team", "companies", "errors"}
    if requested.strip("/") in screens:
        requested = requested.strip("/") + ".html"
    candidate = (build_dir / requested).resolve()
    try:
        candidate.relative_to(build_dir)
    except ValueError:
        abort(404)

    if not candidate.is_file():
        abort(404)

    if requested.endswith(".html"):
        html = candidate.read_text(encoding="utf-8")
        html = html.replace("<script", '<script nonce="' + g.csp_nonce + '"')
        response = make_response(html)
        response.headers["Cache-Control"] = "no-store"
    else:
        response = send_from_directory(build_dir, requested)
    return response


@bp.get("/console")
def owner_console_redirect():
    return redirect("/console/", code=308)


@bp.get("/console/")
def owner_console_index():
    return _serve_console()


@bp.get("/console/<path:asset_path>")
def owner_console_asset(asset_path: str):
    return _serve_console(asset_path)
