"""One test (or more) for each operator, against the synthetic fixture world."""
from __future__ import annotations

import shapely
from shapely.geometry import shape

from geoparse.dsl.schema import PREDICATE_DAGS


def R(id_=None, name=None, **kw):
    args = {"name": name or id_, **kw}
    if id_:
        args["id"] = id_
    return {"op": "Resolve", "args": args}


def run(world, dag):
    res = world.execute(dag)
    assert res.ok, res.error
    return res


def names(res):
    return sorted(f.name for f in res.features)


def geom(res):
    return shapely.union_all([shape(f.geometry) for f in res.features])


def test_resolve_by_id(world):
    res = run(world, R("st_w"))
    assert names(res) == ["Westa"]
    assert abs(geom(res).area - 8.0) < 1e-9


def test_resolve_by_name(world):
    res = run(world, R(name="Alpha City"))
    assert res.ids == ["l_alpha"]


def test_resolve_photon(world):
    res = run(world, R(name="Main Road, Alpha City", source="photon"))
    assert res.ids == ["osm:W9"]
    assert res.features[0].source == "photon"


def test_lexicon_set(world):
    res = run(world, {"op": "LexiconSet", "args": {"key": "all_states"}})
    assert names(res) == ["Easta", "Westa"]


def test_layer(world):
    res = run(world, {"op": "Layer", "args": {"name": "coastline"}})
    assert res.features[0].geometry["type"] in ("MultiLineString", "LineString")


def test_children(world):
    res = run(world, {"op": "Children", "args": {"of": R("st_w"), "level": "district"}})
    assert names(res) == ["W1", "W2", "W3", "W4"]


def test_children_city_level_uses_city_classes(world):
    res = run(world, {"op": "Children", "args": {"of": R("c_tl"), "level": "city"}})
    assert names(res) == ["Alpha City", "Beta Town"]


def test_children_of_computed_geometry(world):
    dag = {"op": "Children", "args": {"of": {"op": "Buffer", "args": {"of": R("l_alpha"), "distance_m": 1000}},
                                      "level": "district"}}
    res = run(world, dag)
    assert names(res) == ["W1"]


def test_parent(world):
    res = run(world, {"op": "Parent", "args": {"of": R("m_gamma"), "level": "state"}})
    assert names(res) == ["Westa"]


def test_parent_of_photon_point(world):
    res = run(world, {"op": "Parent", "args": {"of": R(name="Main Road, Alpha City", source="photon"), "level": "district"}})
    assert names(res) == ["W1"]


def test_neighbors_same_level(world):
    res = run(world, {"op": "Neighbors", "args": {"of": R("d_w2")}})
    # W2 shares edges with W1, W4 and E1, and corners with W3 and E3. Corners count as a touch.
    assert names(res) == ["E1", "E3", "W1", "W3", "W4"]


def test_neighbors_country(world):
    res = run(world, {"op": "Neighbors", "args": {"of": R("c_tl"), "level": "country"}})
    assert names(res) == ["Otherland"]


def test_filter_coastal(world):
    dag = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": R("c_tl"), "level": "district"}},
                                    "pred": PREDICATE_DAGS["coastal"]}}
    assert names(run(world, dag)) == ["W1", "W3"]


def test_filter_landlocked(world):
    dag = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": R("c_tl"), "level": "district"}},
                                    "pred": PREDICATE_DAGS["landlocked"]}}
    assert names(run(world, dag)) == ["E1", "E2", "E3", "E4", "W2", "W4"]


def test_filter_border(world):
    dag = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": R("c_tl"), "level": "district"}},
                                    "pred": PREDICATE_DAGS["border"]}}
    assert names(run(world, dag)) == ["E2", "E4"]


def test_filter_touches_entity(world):
    dag = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": R("st_w"), "level": "district"}},
                                    "pred": {"op": "Touches", "args": {"target": R("st_e")}}}}
    assert names(run(world, dag)) == ["W2", "W4"]


def test_filter_within_and_intersects(world):
    within = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": R("c_tl"), "level": "district"}},
                                       "pred": {"op": "Within", "args": {"target": R("st_e")}}}}
    assert names(run(world, within)) == ["E1", "E2", "E3", "E4"]
    inter = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": R("c_tl"), "level": "city"}},
                                      "pred": {"op": "Intersects", "args": {"target": R("d_w1")}}}}
    assert names(run(world, inter)) == ["Alpha City"]


def test_filter_within_distance(world):
    # Beta Town (79.5, 13.5) is about 54 km from E2's top edge... and inside E4. Alpha City is far.
    dag = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": R("c_tl"), "level": "city"}},
                                    "pred": {"op": "WithinDistance", "args": {"target": R("d_e4"), "distance_m": 1000}}}}
    assert names(run(world, dag)) == ["Beta Town"]


def test_buffer_area_in_meters(world):
    res = run(world, {"op": "Buffer", "args": {"of": R("l_beta"), "distance_m": 2000}})
    g = geom(res)
    # Area of a 2 km circle in square degrees at about 13.5 N: pi * 4e6 / (111320^2 * cos(13.5))
    import math
    expect = math.pi * 4e6 / (111320 ** 2 * math.cos(math.radians(13.5)))
    assert abs(g.area - expect) / expect < 0.02
    assert g.contains(shapely.Point(79.5, 13.5))


def test_centroid(world):
    res = run(world, {"op": "Centroid", "args": {"of": R("d_w1")}})
    p = geom(res)
    assert abs(p.x - 76.5) < 0.01 and abs(p.y - 11.0) < 0.02


def test_direction_part(world):
    res = run(world, {"op": "Direction", "args": {"of": R("st_w"), "dir": "north", "mode": "part"}})
    b = geom(res).bounds
    assert b == (76.0, 12.0, 78.0, 14.0)


def test_direction_outside(world):
    res = run(world, {"op": "Direction", "args": {"of": R("d_w1"), "dir": "east", "mode": "outside"}})
    b = geom(res).bounds
    assert b == (77.0, 10.0, 78.0, 12.0)


def test_union_dedups(world):
    dag = {"op": "Union", "args": {"a": R("d_w1"), "b": {"op": "Children", "args": {"of": R("st_w"), "level": "district"}}}}
    assert names(run(world, dag)) == ["W1", "W2", "W3", "W4"]


def test_intersect(world):
    dag = {"op": "Intersect", "args": {"a": R("st_w"), "b": {"op": "Buffer", "args": {"of": R("d_e1"), "distance_m": 10000}}}}
    res = run(world, dag)
    assert names(res) == ["Westa"]
    b = geom(res).bounds
    assert 77.85 < b[0] < 77.95 and b[2] == 78.0


def test_difference_member_and_area(world):
    dag = {"op": "Difference", "args": {"a": {"op": "LexiconSet", "args": {"key": "all_states"}}, "b": R("d_w1")}}
    res = run(world, dag)
    assert names(res) == ["Easta", "Westa"]
    westa = next(f for f in res.features if f.name == "Westa")
    assert abs(shape(westa.geometry).area - 6.0) < 1e-6
    dag2 = {"op": "Difference", "args": {"a": {"op": "LexiconSet", "args": {"key": "all_states"}}, "b": R("st_w")}}
    assert names(run(world, dag2)) == ["Easta"]


def test_between(world):
    res = run(world, {"op": "Between", "args": {"a": R("d_w1"), "b": R("d_e2")}})
    g = geom(res)
    assert g.contains(shapely.Point(78.0, 11.0))
    assert not g.contains(shapely.Point(76.5, 11.0))


def test_along_layer_within(world):
    res = run(world, {"op": "Along", "args": {"line": {"op": "Layer", "args": {"name": "coastline"}},
                                              "distance_m": 5000, "within": R("st_w")}})
    b = geom(res).bounds
    assert b[0] == 76.0 and 76.04 < b[2] < 76.06


def test_along_entity_boundary(world):
    res = run(world, {"op": "Along", "args": {"line": R("d_w1"), "distance_m": 1000}})
    g = geom(res)
    assert g.contains(shapely.Point(77.0, 11.0)) and not g.contains(shapely.Point(76.5, 11.0))


def test_features_from_places(world, fake_geocoder):
    res = run(world, {"op": "Features", "args": {"category": "hospital", "within": R("st_w")}})
    # p2 is below the minimum confidence; p3 is outside Westa.
    assert res.ids == ["p1"]
    assert fake_geocoder.calls == []
    res = run(world, {"op": "Features", "args": {"category": "school", "within": R("d_w1")}})
    assert res.ids == ["p4"]


def test_features_from_photon(world, world_config, fake_geocoder):
    world_config["geocoder"]["features_source"] = "photon"
    res = run(world, {"op": "Features", "args": {"category": "hospital", "within": R("st_w")}})
    assert res.ids == ["osm:N1"]
    assert fake_geocoder.calls and fake_geocoder.calls[0]["osm_tag"] == "amenity:hospital"


def test_attr_filter_population(world):
    base = {"op": "Children", "args": {"of": R("c_tl"), "level": "district"}}
    res = run(world, {"op": "AttrFilter", "args": {"set": base, "attr": "population", "op": "gt", "value": 2_000_000}})
    assert names(res) == ["E3", "W1", "W3"]
    assert any("no population" in n for n in res.notes)
    res = run(world, {"op": "AttrFilter", "args": {"set": base, "attr": "population", "op": "lt", "value": 900_000}})
    assert names(res) == ["E2", "W4"]


def test_attr_filter_area(world):
    base = {"op": "Children", "args": {"of": R("c_tl"), "level": "state"}}
    res = run(world, {"op": "AttrFilter", "args": {"set": base, "attr": "area", "op": "gt", "value": 1000}})
    assert names(res) == ["Easta", "Westa"]


def test_policy_union_territories(world, world_config):
    world_config["policy"]["union_territories"] = ["TL-EA"]
    world_config["policy"]["union_territories_are_states"] = False
    res = run(world, {"op": "Children", "args": {"of": R("c_tl"), "level": "state"}})
    assert names(res) == ["Westa"]


def test_invalid_dag_is_rejected(world):
    res = world.execute({"op": "Children", "args": {"of": R("c_tl"), "level": "galaxy"}})
    assert not res.ok and "admin_levels" in res.error


def test_features_on_empty_region(world, fake_geocoder):
    empty = {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": R("st_e"), "level": "district"}},
                                      "pred": PREDICATE_DAGS["coastal"]}}
    res = run(world, {"op": "Features", "args": {"category": "hospital", "within": empty}})
    assert res.features == [] and any("empty" in n for n in res.notes)
    assert fake_geocoder.calls == []
