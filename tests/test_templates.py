from geoparse.dsl.schema import CATALOG
from geoparse.parse.pipeline import Parser
from geoparse.templates.model import load_families, match_pattern


class _NoStore:
    def search(self, *a, **k):
        return []


def test_all_templates_load_and_have_valid_dags():
    fams = load_families()
    assert set(fams) == {"lookup", "modifier", "hierarchy", "predicate_filter", "set_algebra", "relational",
                         "features", "attribute"}
    for f in fams.values():
        for t in f.templates:
            d = t.dag_json
            assert d is not None
            if isinstance(d, dict) and "op" in d:
                assert d["op"] in CATALOG


def test_pattern_alternatives_and_optional():
    ms = match_pattern("within [a] {distance} (of|from) {target}", "within a 2 km of Goa")
    assert ms and ms[0]["segments"] == {"distance": "2 km", "target": "Goa"}
    ms = match_pattern("{level} (that|which) (border|borders) {of}", "states which border Kerala")
    assert ms[0]["segments"] == {"level": "states", "of": "Kerala"}


def test_pattern_returns_every_split():
    ms = match_pattern("{a} of {b}", "x of y of z")
    assert sorted(m["segments"]["b"] for m in ms) == ["y of z", "z"]


def test_every_example_matches_its_own_template():
    """Each example in a template must produce a valid split for that template."""
    p = Parser.__new__(Parser)
    p.families = load_families()
    p.templates = {t.id: t for f in p.families.values() for t in f.templates}
    p._store = _NoStore()
    for t in p.templates.values():
        for ex in t.examples:
            cands = p.candidates(ex)
            assert t.id in cands, f"{t.id}: example {ex!r} has no valid split"


def test_closed_segment_must_be_keywords():
    p = Parser.__new__(Parser)
    p.families = load_families()
    p.templates = {t.id: t for f in p.families.values() for t in f.templates}
    cands = p.candidates("districts of states that border Goa")
    # "districts of states" is not a level, so the neighbors template has no split here.
    assert "neighbors" not in cands
    assert "children" in cands
