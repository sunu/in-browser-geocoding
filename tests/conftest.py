from __future__ import annotations

import copy

import pytest

from geoparse.config import load_config
from geoparse.execute.data import Store
from geoparse.execute.executor import Executor
from geoparse.execute.geocoder import GeoFeature

from tests import fixture_world


class FakeGeocoder:
    """Geocoder that returns fixed points. No network."""

    name = "fake"

    def __init__(self, points: dict[str, list[GeoFeature]] | None = None):
        self.points = points or {}
        self.calls: list[dict] = []

    def search(self, q, *, limit=5, bbox=None, osm_tag=None, location=None):
        self.calls.append({"q": q, "bbox": bbox, "osm_tag": osm_tag})
        feats = self.points.get(osm_tag or q, [])
        if bbox:
            x0, y0, x1, y1 = bbox
            feats = [f for f in feats if x0 <= f.lon <= x1 and y0 <= f.lat <= y1]
        return feats[:limit]


@pytest.fixture(scope="session")
def world_store(tmp_path_factory) -> Store:
    path = fixture_world.build(tmp_path_factory.mktemp("world") / "world.duckdb")
    return Store(path)


@pytest.fixture
def world_config():
    cfg = copy.deepcopy(load_config())
    cfg["data"]["country"] = fixture_world.COUNTRY
    cfg["data"]["bbox"] = [70, 5, 90, 20]
    cfg["policy"]["output_simplify_deg"] = 0
    return cfg


@pytest.fixture
def fake_geocoder():
    pts = {
        "amenity:hospital": [
            GeoFeature(id="osm:N1", name="Alpha Hospital", lon=76.5, lat=11.0, osm_key="amenity", osm_value="hospital"),
            GeoFeature(id="osm:N2", name="Far Hospital", lon=79.5, lat=13.5, osm_key="amenity", osm_value="hospital"),
        ],
        "Main Road, Alpha City": [
            GeoFeature(id="osm:W9", name="Main Road", lon=76.55, lat=11.05, osm_key="highway", osm_value="primary"),
        ],
    }
    return FakeGeocoder(pts)


@pytest.fixture
def world(world_store, world_config, fake_geocoder, monkeypatch):
    import importlib

    # geoparse.execute is also the name of a public function, so import the module by its path.
    ex_mod = importlib.import_module("geoparse.execute.executor")
    opt_mod = importlib.import_module("geoparse.options")

    monkeypatch.setattr(ex_mod, "lexicon", lambda: fixture_world.LEXICON)
    monkeypatch.setattr(opt_mod, "lexicon", lambda: fixture_world.LEXICON)
    return Executor(store=world_store, geocoder=fake_geocoder, config=world_config)
