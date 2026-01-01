"""
app package entrypoint.

Gunicorn / Render will import:
  app:create_app

So this file MUST expose create_app at package level.
"""

from __future__ import annotations

# Re-export the real factory
from app.app_factory import create_app  # noqa: F401

__all__ = ["create_app"]
