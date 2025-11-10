"""
App factory: create_app()

- Loads config (env, flags, secrets)
- Sets up logging
- Wires DI container (stores, services, modes)
- Registers middleware (request IDs, rate limits, CSRF)
- Registers blueprints from routes/*
- Installs global error handlers
"""

from __future__ import annotations
import logging
from typing import Any, Dict

from flask import Flask, jsonify, request

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

    app.register_blueprint(health_bp)
    app.register_blueprint(webchat_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(diag_bp)


def _install_error_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(err):
        app.logger.warning(f"400: {err}")
        return jsonify({"error": "bad_request"}), 400

    @app.errorhandler(401)
    def unauthorized(err):
        return jsonify({"error": "unauthorized"}), 401

    @app.errorhandler(403)
    def forbidden(err):
        return jsonify({"error": "forbidden"}), 403

    @app.errorhandler(404)
    def not_found(err):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(429)
    def too_many(err):
        return jsonify({"error": "rate_limited"}), 429

    @app.errorhandler(500)
    def server_error(err):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": "server_error"}), 500


def create_app(config_override: Dict[str, Any] | None = None) -> Flask:
    # Settings & logging
    settings: Settings = load_settings(config_override)
    configure_logging(settings)

    app = Flask(__name__, static_folder=None)
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["WTF_CSRF_ENABLED"] = False  # using our own lightweight CSRF

    # Dependency container (stores, services, mode strategy)
    container = Container(settings)
    app.container = container  # type: ignore[attr-defined]

    # Middleware
    middleware.install_request_id(app)
    middleware.install_rate_limit(app, settings)
    middleware.install_csrf(app, settings)
    middleware.install_timing_metrics(app, container)

    # Blueprints
    _register_blueprints(app)

    # Error handlers
    _install_error_handlers(app)

    # Mode banner
    app.logger.info(f"App started in MODE={settings.MODE} TENANT={settings.BUSINESS_KEY}")

    # Simple root
    @app.get("/")
    def root():
        return {"ok": True, "mode": settings.MODE, "tenant": settings.BUSINESS_KEY}

    return app
