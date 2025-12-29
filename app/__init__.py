"""
App factory: create_app()

- Loads config
- Sets up logging
- Wires DI container
- Registers middleware
- Registers blueprints
- Installs global error handlers
- Points Flask to dashboard/templates + dashboard/static
- Adds small diag endpoints for route/template debugging
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app.config import Settings, load_settings
from app.container import Container
from app.logging_setup import configure_logging
from app import middleware

# /app/app/__init__.py -> parents[1] == /app (repo root)
REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"


def _register_blueprints(app: Flask) -> None:
    """
    Import + register all blueprints exactly once.
    IMPORTANT: blueprint names must be unique across the app.
    """
    from routes.health_routes import bp as health_bp
    from routes.webchat_routes import bp as webchat_bp
    from routes.whatsapp_routes import bp as whatsapp_bp
    from routes.analytics_routes import bp as analytics_bp
    from routes.admin_routes import bp as admin_bp
    from routes.files_routes import bp as files_bp
    from routes.auth_routes import bp as auth_bp
    from routes.diag_routes import bp as diag_bp
    from routes.catalog_routes import bp as catalog_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(webchat_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(diag_bp)
    app.register_blueprint(catalog_bp)


def _install_error_handlers(app: Flask) -> None:
    """
    Keep errors JSON across the whole API (including admin APIs),
    so your frontend can reliably handle failures.
    """

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        # keep a consistent error code for frontend
        code = err.code or 500
        key = (err.name or "error").lower().replace(" ", "_")
        app.logger.warning(
            "HTTP %s %s %s (%s)", code, request.method, request.path, key
        )
        return jsonify({"error": key}), code

    @app.errorhandler(Exception)
    def handle_exception(err: Exception):
        app.logger.exception("UNHANDLED_EXCEPTION %s %s", request.method, request.path)
        return jsonify({"error": "server_error"}), 500


def create_app(config_override: Optional[Dict[str, Any]] = None) -> Flask:
    settings: Settings = load_settings(config_override)
    configure_logging(settings)

    # Build Flask with correct template/static roots
    app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )

    # Core config
    app.config["SECRET_KEY"] = settings.SECRET_KEY

    # Your project uses custom CSRF middleware (header-based).
    # Flask-WTF CSRF must be OFF to avoid double-CSRF + confusion.
    app.config["WTF_CSRF_ENABLED"] = False

    # DI container
    container = Container(settings)
    app.container = container  # type: ignore[attr-defined]

    # Middleware
    middleware.install_request_id(app)
    middleware.install_rate_limit(app, settings)
    middleware.install_csrf(app, settings)
    middleware.install_timing_metrics(app, container)

    # Blueprints + errors
    _register_blueprints(app)
    _install_error_handlers(app)

    # -------------------------
    # Diagnostics (safe / read-only)
    # -------------------------
    @app.get("/__diag/templates")
    def __diag_templates():
        try:
            files = sorted(p.name for p in TEMPLATES_DIR.glob("*.html"))
        except Exception as e:
            files = [f"ERR: {e}"]
        return jsonify(
            {
                "repo_root": str(REPO_ROOT),
                "templates_dir": str(TEMPLATES_DIR),
                "static_dir": str(STATIC_DIR),
                "templates_exist": TEMPLATES_DIR.exists(),
                "static_exist": STATIC_DIR.exists(),
                "html_files": files[:200],
            }
        )

    @app.get("/__diag/routes")
    def __diag_routes():
        # Helps you answer: “what URLs exist right now?”
        rules = []
        for r in sorted(app.url_map.iter_rules(), key=lambda x: str(x)):
            rules.append(
                {
                    "rule": str(r),
                    "endpoint": r.endpoint,
                    "methods": sorted([m for m in r.methods if m not in {"HEAD", "OPTIONS"}]),
                }
            )
        return jsonify({"routes": rules})

    # Root health
    @app.get("/")
    def root():
        return jsonify({"ok": True, "mode": settings.MODE, "tenant": settings.BUSINESS_KEY})

    # Startup log (shows up in Render)
    app.logger.info(
        "App started MODE=%s TENANT=%s templates=%s static=%s",
        settings.MODE,
        settings.BUSINESS_KEY,
        TEMPLATES_DIR,
        STATIC_DIR,
    )

    return app
