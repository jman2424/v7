"""
Logging setup.

- Console-first logging (Render-safe)
- Optional rotating file logs for local/dev
- Request-ID aware formatter
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import Settings


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def _console_handler(level: int) -> logging.Handler:
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(level)
    h.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s %(request_id)s - %(message)s"
        )
    )
    h.addFilter(RequestIdFilter())
    return h


def _file_handler(path: Path, level: int) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(
        path,
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    h.setLevel(level)
    h.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s %(request_id)s - %(message)s"
        )
    )
    h.addFilter(RequestIdFilter())
    return h


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()

    # 🔒 Prevent handler duplication on reload
    root.handlers.clear()
    root.setLevel(logging.INFO)

    # ✅ ALWAYS log to stdout (Render / Gunicorn)
    root.addHandler(_console_handler(logging.INFO))

    # Optional file logs (safe locally, harmless on Render)
    logs_dir = Path("logs")
    root.addHandler(_file_handler(logs_dir / "errors.log", logging.ERROR))

    logging.getLogger("Analytics").addHandler(
        _file_handler(logs_dir / "analytics.log", logging.INFO)
    )

    # Make Flask/Gunicorn propagate properly
    logging.getLogger("werkzeug").setLevel(logging.INFO)
    logging.getLogger("gunicorn.error").propagate = True
    logging.getLogger("gunicorn.access").propagate = True
