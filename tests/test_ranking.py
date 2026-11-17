"""Ranking of gazetteer candidates: map view and Photon boost (plan-012 section 3.2)."""
from __future__ import annotations

from geoparse.decisions.functions import Decider
from geoparse.decisions.log import NullLogger
from geoparse.decisions.types import Candidate
from geoparse.execute.geocoder import GeoFeature, GeocoderError
from tests.conftest import FakeGeocoder


def _parser(store, geocoder):
    from geoparse.parse.pipeline import Parser

    return Parser(Decider(default="rules", logger=NullLogger(), use_ner=False), store=store, use_t5=False,
                  geocoder=geocoder)


def _cands():
    return [Candidate(id="st_w", name="Westa", source="overture", subtype="region", description="", score=1.0),
            Candidate(id="st_e", name="Easta", source="overture", subtype="region", description="", score=0.95)]


def _feat(lon, lat):
    return GeoFeature(id="osm:R1", name="X", lon=lon, lat=lat, osm_key="place", osm_value="state")


def test_view_removes_score_outside_the_view(world_store):
    near = world_store.search("Alpha City", view=[76, 10, 77, 12])[0]
    far = world_store.search("Alpha City", view=[0, 0, 1, 1])[0]
    assert near.id == far.id == "l_alpha"
    assert round(near.score - far.score, 4) == 0.15


def test_view_country_is_nearest_admin_point(world_store):
    from geoparse.config import load_config

    assert world_store.view([80.5, 11.5, 81.5, 12.5], load_config())[1] == "OT"
    assert world_store.view(None, load_config())[1] == load_config()["data"]["country"]


def test_photon_boost_reorders_close_candidates(world_store):
    geo = FakeGeocoder({"Easta": [_feat(79, 12)]})
    p = _parser(world_store, geo)
    dec = p.base_decider.fork()
    out = p._photon_boost(dec, "Easta", _cands(), 0)
    assert [c.id for c in out] == ["st_e", "st_w"] and out[0].score == 1.15
    step = [t for t in dec.trace if t["decision"] == "photon_boost"][0]
    assert step["value"] == {"st_e": 0.2}


def test_photon_boost_not_called_when_far_apart_or_without_geocoder(world_store):
    geo = FakeGeocoder({"Easta": [_feat(79, 12)]})
    p = _parser(world_store, geo)
    cands = _cands()
    cands[1] = cands[1].model_copy(update={"score": 0.5})
    assert p._photon_boost(p.base_decider.fork(), "Easta", cands, 0) == cands and geo.calls == []
    assert _parser(world_store, None)._photon_boost(p.base_decider.fork(), "Easta", _cands(), 0) == _cands()


def test_photon_boost_continues_on_geocoder_error(world_store):
    class Failing(FakeGeocoder):
        def search(self, q, **kw):
            raise GeocoderError("timeout")

    p = _parser(world_store, Failing())
    dec = p.base_decider.fork()
    assert p._photon_boost(dec, "Easta", _cands(), 0) == _cands()
    assert dec.trace[-1]["trace"]["error"] == "timeout"
