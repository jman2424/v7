# app/app_factory.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app.config import Settings, load_settings
from app.logging_setup import configure_logging
from app.container import Container
from app import middleware

# Ensure analytics DB exists at boot (safe if missing)
try:
    from app.service.analytics_db import init_db as init_analytics_db  # ✅ FIXED IMPORT
except Exception:  # pragma: no cover
    init_analytics_db = None

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"


def _wants_json_response() -> bool:
    p = (request.path or "").lower()

    if p.startswith(
        (
            "/admin/api",
            "/analytics",
            "/chat_api",
            "/chat_ui",
            "/webchat",
            "/whatsapp",
            "/__diag",
            "/files",
            "/health",
            "/healthz",
            "/catalog",
            "/auth",
            "/mode",
            "/version",
        )
    ):
        return True

    accept = (request.headers.get("Accept") or "").lower()
    xrw = (request.headers.get("X-Requested-With") or "").lower()
    return ("application/json" in accept) or (xrw == "xmlhttprequest")


def _register_blueprints(app: Flask) -> None:
    """
    Register all blueprints.

    IMPORTANT:
    - Because gunicorn loads `app.app_factory:create_app`,
      the correct imports are `app.routes.*` (not `routes.*`).
    """
    # ✅ FIXED imports: app.routes.*
    from app.routes.health_routes import bp as health_bp
    from app.routes.webchat_routes import bp as webchat_bp
    from app.routes.whatsapp_routes import bp as whatsapp_bp
    from app.routes.analytics_routes import bp as analytics_bp
    from app.routes.admin_routes import bp as admin_bp
    from app.routes.files_routes import bp as files_bp
    from app.routes.auth_routes import bp as auth_bp
    from app.routes.diag_routes import bp as diag_bp
    from app.routes.catalog_routes import bp as catalog_bp
    from app.routes.mode_routes import bp as mode_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(webchat_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(diag_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(mode_bp)

    # Admin API routes (dashboard)
    try:
        from app.routes.admin_api_routes import bp as admin_api_bp  # ✅ FIXED
        app.register_blueprint(admin_api_bp)
        app.logger.info(
            "Registered blueprint: app.routes.admin_api_routes (url_prefix=%s)",
            getattr(admin_api_bp, "url_prefix", None),
        )
    except Exception as e:
        # If this fails, your /admin/api endpoints will be 404.
        app.logger.exception("FATAL: failed to import/register app.routes.admin_api_routes: %s", e)


def _install_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        app.logger.warning("HTTP %s %s %s", err.code, request.method, request.path)

        if _wants_json_response():
            key = (err.name or "error").lower().replace(" ", "_")
            return jsonify({"error": key, "status": err.code}), err.code

        return (
            f"<h1>{err.code} {err.name}</h1>"
            f"<p>{err.description}</p>",
            err.code,
        )

    @app.errorhandler(Exception)
    def handle_exception(err: Exception):
        app.logger.exception("UNHANDLED_EXCEPTION %s %s", request.method, request.path)

        if _wants_json_response():
            return jsonify({"error": "server_error"}), 500

        return (
            "<h1>500 Server error</h1>"
            "<p>Something crashed. Check logs.</p>",
            500,
        )


def _ensure_container_ready(app: Flask) -> None:
    try:
        container = getattr(app, "container", None)
        if not container:
            return

        analytics = getattr(container, "analytics", None)
        if analytics and hasattr(analytics, "ensure_ready"):
            analytics.ensure_ready()
            app.logger.info("Analytics service ready")
    except Exception:
        app.logger.exception("Failed to ensure container readiness")


def create_app(config_override: Optional[Dict[str, Any]] = None) -> Flask:
    settings: Settings = load_settings(config_override)
    configure_logging(settings)

    # Analytics DB init (safe)
    try:
        if init_analytics_db:
            init_analytics_db()
            logging.getLogger("APP.Factory").info("Analytics DB init ok")
        else:
            logging.getLogger("APP.Factory").warning("Analytics DB init skipped (import failed)")
    except Exception:
        logging.getLogger("APP.Factory").exception("Failed to init analytics DB")

    app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )

    app.logger.info(
        "Flask paths repo_root=%s templates=%s static=%s",
        REPO_ROOT,
        TEMPLATES_DIR,
        STATIC_DIR,
    )

    app.config["SECRET_KEY"] = settings.SECRET_KEY

    container = Container(settings)
    app.container = container  # type: ignore[attr-defined]

    # Middleware
    middleware.install_request_id(app)
    middleware.install_rate_limit(app, settings)
    middleware.install_csrf(app, settings)
    middleware.install_timing_metrics(app, container)

    # Routes + errors
    _register_blueprints(app)
    _install_error_handlers(app)
    _ensure_container_ready(app)

    # Root
    @app.get("/")
    def root():
        return {"ok": True, "mode": settings.MODE, "tenant": settings.BUSINESS_KEY}

    # Health for Render
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
