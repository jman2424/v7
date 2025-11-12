"""
GeoStore tests — nearest branch, postcode prefix coverage, and distance math.
"""

from __future__ import annotations
import math
import pytest
from retrieval.geo_store import GeoStore

@pytest.fixture()
def sample_branches(tmp_path):
    data = [
        {"id": "e1", "name": "East Branch", "postcode": "E1 1AA", "lat": 51.5151, "lon": -0.0672},
        {"id": "n1", "name": "North Branch", "postcode": "N1 1AA", "lat": 51.5465, "lon": -0.1024},
        {"id": "se1", "name": "South Branch", "postcode": "SE1 0AA", "lat": 51.5055, "lon": -0.0901}
    ]
    p = tmp_path / "branches.json"
    import json
    p.write_text(json.dumps(data))
    return data

def test_haversine_distance_accuracy():
    from retrieval.geo_store import haversine_km
    london_bridge = (51.5079, -0.0877)
    tower_hill = (51.509, -0.0767)
    d = haversine_km(*london_bridge, *tower_hill)
    assert 0.5 < d < 1.5  # within 1 km expected range

def test_nearest_branch(sample_branches, tmp_path):
    g = GeoStore(branches=sample_branches)
    res = g.nearest(51.514, -0.07)
    assert res["id"] == "e1"
    assert res["distance_km"] < 2.0

def test_postcode_prefix_search():
    g = GeoStore(branches=[
        {"id": "e1", "postcode": "E1 1AA"},
        {"id": "e2", "postcode": "E2 4BB"},
        {"id": "n1", "postcode": "N1 7CC"}
    ])
    e_prefix = g.covered_prefixes("E")
    n_prefix = g.covered_prefixes("N")
    assert "E1" in e_prefix and "E2" in e_prefix
    assert "N1" in n_prefix

def test_out_of_range_returns_none():
    g = GeoStore(branches=[
        {"id": "north", "postcode": "N1 1AA", "lat": 51.55, "lon": -0.1}
    ])
    res = g.nearest(48.0, 2.0, radius_km=10)
    assert res is None

def test_geojson_export(tmp_path, sample_branches):
    g = GeoStore(branches=sample_branches)
    geojson = g.to_geojson()
    assert "features" in geojson and len(geojson["features"]) == len(sample_branches)
    for f in geojson["features"]:
        assert "geometry" in f and "coordinates" in f["geometry"]
