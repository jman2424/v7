"""Tenant data stores. ``Storage`` is the persistence layer every store reads through."""
from __future__ import annotations

from .storage import Storage

__all__ = ["Storage"]
