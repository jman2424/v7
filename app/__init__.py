"""
App factory: create_app()

- Loads config
- Sets up logging
- Wires DI container
- Registers middleware
- Registers blueprints
- Installs global error handlers
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app.config import Settings, load_settings
from app.logging_setup import configure_logging
from app.container import Container
from app import middleware


def _register_blueprints(app: Flask) -> None:
    # Lazy imports to avoid circulars
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
    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        app.logger.warning("HTTP %s %s %s", err.code, request.method, request.path)
        key = (err.name or "error").lower().replace(" ", "_")
        return jsonify({"error": key}), err.code

    @app.errorhandler(Exception)
    def handle_exception(err: Exception):
        app.logger.exception("UNHANDLED_EXCEPTION %s %s", request.method, request.path)
        return jsonify({"error": "server_error"}), 500


def create_app(config_override: Dict[str, Any] | None = None) -> Flask:
    settings: Settings = load_settings(config_override)
    configure_logging(settings)

    app = Flask(__name__, static_folder=None)
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["WTF_CSRF_ENABLED"] = False

    container = Container(settings)
    app.container = container  # type: ignore[attr-defined]

    middleware.install_request_id(app)
    middleware.install_rate_limit(app, settings)
    middleware.install_csrf(app, settings)
    middleware.install_timing_metrics(app, container)

    _register_blueprints(app)
    _install_error_handlers(app)

    # --- TEMP: route map (remove after you find paths) ---
    @app.get("/__routes")
    def __routes():
        rows = []
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
            rows.append(
                {
                    "rule": str(rule),
                    "endpoint": rule.endpoint,
                    "methods": sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"}),
                }
            )
        return {"routes": rows}
    # -----------------------------------------------------

    app.logger.info("App started MODE=%s TENANT=%s", settings.MODE, settings.BUSINESS_KEY)

    @app.get("/")
    def root():
        return {"ok": True, "mode": settings.MODE, "tenant": settings.BUSINESS_KEY}

    return app
