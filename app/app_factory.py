# app/app_factory.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app.config import Settings, load_settings
from app.logging_setup import configure_logging
from app.container import Container
from app import middleware

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"


def _wants_json_response() -> bool:
    """
    We return JSON for API-ish routes and for requests that explicitly ask for JSON.
    We return HTML for dashboard/UI routes so the browser doesn't show blank JSON.
    """
    p = (request.path or "").lower()

    # Treat these as API routes
    if p.startswith((
        "/admin/api",
        "/analytics",
        "/chat_api",
        "/webchat",
        "/whatsapp",
        "/__diag",
        "/files",
        "/health",
        "/catalog",
        "/auth",
    )):
        return True

    accept = (request.headers.get("Accept") or "").lower()
    xrw = (request.headers.get("X-Requested-With") or "").lower()
    if "application/json" in accept or xrw == "xmlhttprequest":
        return True

    return False


def _register_blueprints(app: Flask) -> None:
    # Import inside function to avoid circular import problems
    from routes.health_routes import bp as health_bp
    from routes.webchat_routes import bp as webchat_bp
    from routes.whatsapp_routes import bp as whatsapp_bp
    from routes.analytics_routes import bp as analytics_bp
    from routes.admin_routes import bp as admin_bp

    # ✅ If you have this file, register it. If you don't, create it.
    # This is what your dashboard JS should call for charts/leads.
    try:
        from routes.admin_api_routes import bp as admin_api_bp  # type: ignore
    except Exception:
        admin_api_bp = None  # noqa

    from routes.files_routes import bp as files_bp
    from routes.auth_routes import bp as auth_bp
    from routes.diag_routes import bp as diag_bp
    from routes.catalog_routes import bp as catalog_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(webchat_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)
    if admin_api_bp is not None:
        app.register_blueprint(admin_api_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(diag_bp)
    app.register_blueprint(catalog_bp)


def _install_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        app.logger.warning("HTTP %s %s %s", err.code, request.method, request.path)

        if _wants_json_response():
            key = (err.name or "error").lower().replace(" ", "_")
            return jsonify({"error": key}), err.code

        # Basic HTML fallback for UI routes
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

        # Basic HTML fallback for UI routes
        return (
            "<h1>500 Server error</h1>"
            "<p>Something crashed. Check Render logs.</p>",
            500,
        )


def _ensure_container_ready(app: Flask) -> None:
    """
    Optionally initializes analytics DB or other services.
    Safe: it won't crash if your container doesn't have analytics.
    """
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


def create_app(config_override: Dict[str, Any] | None = None) -> Flask:
    settings: Settings = load_settings(config_override)
    configure_logging(settings)

    app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )

    app.logger.info(
        "Flask paths repo_root=%s templates=%s static=%s",
        REPO_ROOT, TEMPLATES_DIR, STATIC_DIR
    )

    # Flask session signing secret
    app.config["SECRET_KEY"] = settings.SECRET_KEY

    # DI container
    container = Container(settings)
    app.container = container  # type: ignore[attr-defined]

    # Middleware
    middleware.install_request_id(app)
    middleware.install_rate_limit(app, settings)
    middleware.install_csrf(app, settings)
    middleware.install_timing_metrics(app, container)

    # Routes + error handling
    _register_blueprints(app)
    _install_error_handlers(app)

    # Optional readiness checks (analytics DB, etc.)
    _ensure_container_ready(app)

    @app.get("/")
    def root():
        return {"ok": True, "mode": settings.MODE, "tenant": settings.BUSINESS_KEY}

    return app
