import pytest

from geoparse.dsl.schema import DagSyntaxError, PREDICATE_DAGS, parse_dag_text, substitute, validate
from geoparse.options import choices


def test_parse_positional_and_keyword():
    d = parse_dag_text("Filter(Children(${parent}, level=${level}), ${pred})")
    assert d == {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": {"$slot": "parent"},
                                                                               "level": {"$slot": "level"}}},
                                          "pred": {"$slot": "pred"}}}


def test_parse_literals():
    d = parse_dag_text("Along(Layer(coastline), 5000, within=Resolve('Kerala'))")
    assert d["args"]["distance_m"] == 5000
    assert d["args"]["line"] == {"op": "Layer", "args": {"name": "coastline"}}
    assert d["args"]["within"]["args"]["name"] == "Kerala"


def test_parse_errors():
    with pytest.raises(DagSyntaxError):
        parse_dag_text("Nope(1)")
    with pytest.raises(DagSyntaxError):
        parse_dag_text("Centroid(1, 2)")


def test_substitute_removes_none():
    d = substitute(parse_dag_text("Neighbors(${of}, level=${level})"),
                   {"of": {"op": "Resolve", "args": {"name": "Kerala"}}, "level": None})
    assert d == {"op": "Neighbors", "args": {"of": {"op": "Resolve", "args": {"name": "Kerala"}}}}


def test_validate_ok_and_errors():
    ok = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": {"op": "Resolve", "args": {"name": "India"}},
                                                                        "level": "state"}},
                                   "pred": PREDICATE_DAGS["landlocked"]}}
    assert validate(ok, choices()) == []
    bad = {"op": "Buffer", "args": {"of": {"op": "Layer", "args": {"name": "coastline"}}, "distance_m": "far", "x": 1}}
    errs = validate(bad, choices())
    assert any("unknown argument x" in e for e in errs)
    assert any("Buffer.of" in e for e in errs)
    assert any("distance_m" in e for e in errs)
    assert validate({"op": "Filter", "args": {"set": {"$slot": "s"}}}, choices())
