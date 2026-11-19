"""Natural features (plan-026): build helpers, and the gazetteer with the local extract."""
import pytest

from geoparse.config import build_dir
from geoparse.data.build_extract import NATURAL_KINDS, _proper_case


def test_proper_case():
    assert _proper_case("HIMALAYAS") == "Himalayas"
    assert _proper_case("BAY OF BENGAL") == "Bay of Bengal"
    assert _proper_case("Lake Victoria") == "Lake Victoria"


def test_natural_kinds():
    assert NATURAL_KINDS["lake centerline"] == "river"
    assert NATURAL_KINDS["range/mtn"] == "range"
    assert "island" in NATURAL_KINDS.values()


@pytest.mark.skipif(not (build_dir() / "geoparse.duckdb").exists(), reason="local extract not built")
def test_natural_search_and_countries():
    from geoparse.execute.data import Store

    s = Store()
    if not s.cursor().execute("SELECT count(*) FROM divisions WHERE subtype = 'natural'").fetchone()[0]:
        pytest.skip("no natural features in the extract")
    view = [68, 8, 97, 37]
    # "river" is a type hint: the river ranks above the village Ganga.
    top = s.search("Ganga river", limit=3, view=view)[0]
    assert (top.id, top.subtype) == ("ne-river-Q5089", "natural")
    assert s.search("Kerala", limit=1, view=view)[0].subtype == "region"
    assert "IN" in s.countries_around("ne-river-Q5089")
