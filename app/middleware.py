def install_csrf(app: Flask, settings: Settings) -> None:
    SAFE = {"GET", "HEAD", "OPTIONS"}
    HEADER = "X-CSRF-Token"

    @app.before_request
    def _csrf():
        if request.method in SAFE:
            return

        path = (request.path or "").lower()

        # Skip CSRF for public/webhook endpoints
        if (
            path.startswith("/chat_api")
            or path.startswith("/whatsapp")
            or path.startswith("/catalog_webhook")
            or path.startswith("/export_catalog_csv")
        ):
            return

        token = (
            request.headers.get(HEADER)
            or request.args.get("_csrf")
            or request.form.get("csrf_token")   # ✅ THIS is what fixes your form
        )

        expected = (getattr(settings, "SECRET_KEY", "") or "")[:16]

        if not token or token != expected:
            app.logger.warning("CSRF blocked: method=%s path=%s token=%r", request.method, path, token)
            abort(403, description="csrf_failed")
