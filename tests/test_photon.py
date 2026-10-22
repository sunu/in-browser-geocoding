from pathlib import Path

import pytest

from geoparse.execute.geocoder import GeocoderError, PhotonGeocoder

FIX = Path(__file__).parent / "fixtures" / "photon"


def test_photon_replay_parses_features():
    g = PhotonGeocoder(cache_dir=FIX, mode="replay")
    feats = g.search("MG Road, Bangalore", limit=5, bbox=(68.0, 6.5, 97.5, 37.2))
    assert feats and feats[0].id.startswith("osm:")
    assert "Bengaluru" in feats[0].label or "Bangalore" in feats[0].label
    hosp = g.search("hospital", limit=50, bbox=(77.6, 12.92, 77.64, 12.95), osm_tag="amenity:hospital")
    assert all(f.osm_value == "hospital" for f in hosp)


def test_photon_replay_miss_raises():
    g = PhotonGeocoder(cache_dir=FIX, mode="replay")
    with pytest.raises(GeocoderError):
        g.search("a query that is not recorded")
