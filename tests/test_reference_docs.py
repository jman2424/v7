"""docs/reference/http-routes.md is generated; it must match the registered routes."""
from pathlib import Path

from scripts.generate_route_map import OUTPUT, render


def test_route_reference_matches_the_application(app):
    committed = OUTPUT.read_text(encoding="utf-8")
    assert committed == render(app), "Run: python scripts/generate_route_map.py"


def test_module_index_is_current_and_every_module_is_described():
    from scripts import generate_module_index as index
    assert index.undocumented() == []
    assert index.OUTPUT.read_text(encoding="utf-8") == index.render(), "Run: python scripts/generate_module_index.py"
