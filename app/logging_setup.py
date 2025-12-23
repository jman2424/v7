from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import Settings


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def _mk_handler(path: Path, level: int) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    h.setLevel(level)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(request_id)s - %(message)s"))
    h.addFilter(RequestIdFilter())
    return h


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    # ✅ Console handler (Render reads stdout/stderr)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    root.addHandler(console)

    # ✅ Ensure exceptions always show up in console too
    console_err = logging.StreamHandler()
    console_err.setLevel(logging.ERROR)
    console_err.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    root.addHandler(console_err)

    # Optional file logs (useful locally; Render won’t show them)
    logs_dir = Path("logs")
    runtime = _mk_handler(logs_dir / "chatbot.log", logging.INFO)
    errors = _mk_handler(logs_dir / "errors.log", logging.ERROR)
    analytics = _mk_handler(logs_dir / "analytics.log", logging.INFO)

    logging.getLogger("Runtime").addHandler(runtime)
    logging.getLogger("Analytics").addHandler(analytics)
    root.addHandler(errors)

    # Make Flask/Gunicorn loggers propagate to root
    logging.getLogger("gunicorn.error").propagate = True
    logging.getLogger("gunicorn.access").propagate = True
