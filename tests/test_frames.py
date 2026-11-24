import pytest

from geoparse.t5.frames import Frame, check_frame, distance_m, find_span, frame_to_match, group_frames, value_num
from geoparse.templates.model import all_templates

T = all_templates()


def test_round_trip():
    t = "children_with_predicate ; level = districts ; pred = near the sea ; parent = Gujarat"
    f = Frame.from_text(t)
    assert f.template == "children_with_predicate" and f.slots["pred"] == "near the sea"
    assert f.to_text() == t
    assert Frame.from_text("unsupported").template == "unsupported"
    assert Frame.from_text("buffer ; target") is None


@pytest.mark.parametrize("text,m", [("2 km", 2000), ("0.5 km", 500), ("2000 m", 2000), ("1 mi", 1609.344)])
def test_distance(text, m):
    assert distance_m(text) == pytest.approx(m)


@pytest.mark.parametrize("text,v", [("30 lakh", 3e6), ("1 million", 1e6), ("500", 500), ("1.5 crore", 1.5e7)])
def test_value(text, v):
    assert value_num(text) == v


def test_bad_quantities():
    assert distance_m("2 kilometres") is None
    assert value_num("ten lakh") is None


def test_find_span_whole_words():
    assert find_span("districts of Kerala", "district") is None
    assert find_span("districts of Kerala", "kerala") == (13, 19)


def test_check_frame():
    q = "hospitals within 2000 metres of MG Road"
    good = Frame.from_text("features_near ; category = hospitals ; distance = 2000 m ; region = MG Road")
    assert check_frame(good, q, T) == []
    bad = Frame.from_text("features_near ; category = hospital ; distance = 2 kilometres ; region = Brigade Road")
    problems = check_frame(bad, q, T)
    assert any("Brigade Road" in p for p in problems) and any("distance" in p for p in problems)
    assert any("missing slot" in p for p in check_frame(Frame.from_text("union ; a = MG Road"), q, T))


def test_group_frames_merges_closed_and_quantity_variants():
    q = "half a km around Charminar"
    fs = [Frame.from_text("buffer ; distance = 0.5 km ; target = Charminar", score=-0.01),
          Frame.from_text("buffer ; distance = 0.6 km ; target = Charminar", score=-0.4),
          Frame.from_text("lookup_place ; anchor = Charminar", score=-1.5),
          Frame.from_text("buffer ; distance = 0.5 km ; target = Hyderabad", score=-0.2)]
    g = group_frames(fs, q, T, margin=2.0)
    assert [f.to_text() for f in g] == ["buffer ; distance = 0.5 km ; target = Charminar", "lookup_place ; anchor = Charminar"]
    assert group_frames(fs, q, T, margin=1.0)[0].slots["distance"] == "0.5 km"


def test_frame_to_match_uses_query_case():
    m = frame_to_match(Frame.from_text("children ; level = districts ; parent = kerala"), "districts of Kerala")
    assert m["segments"] == {"level": "districts", "parent": "Kerala"}


def test_list_and_within_slots():
    # plan-039: list parts with " | ", and a qualifier `<slot>.within`. Each part and the qualifier are spans.
    q = "states of France, Spain or Italy"
    f = Frame.from_text("children ; level = states ; parent = France | Spain | Italy")
    assert check_frame(f, q, T) == []
    assert frame_to_match(f, q.lower())["segments"]["parent"] == "france | spain | italy"
    bad = Frame.from_text("children ; level = states ; parent = France | Germany")
    assert any("Germany" in p for p in check_frame(bad, q, T))
    assert "the same text in two region slots" in check_frame(
        Frame.from_text("union ; places = France | France"), q, T)
    w = Frame.from_text("lookup_place ; anchor = Springfield ; anchor.within = Illinois")
    assert check_frame(w, "Springfield, Illinois", T) == []
    assert frame_to_match(w, "Springfield, Illinois")["within"] == {"anchor": "Illinois"}
    assert any("unknown slot" in p for p in check_frame(
        Frame.from_text("lookup_place ; anchor = Springfield ; level.within = Illinois"), "Springfield, Illinois", T))


def test_group_prefers_the_frame_that_covers_more():
    # plan-039: a near tie in a group goes to the frame that explains more of the query, with the best score.
    q = "states bordering Rajasthan"
    fs = [Frame.from_text("neighbors ; of = Rajasthan", score=-0.069),
          Frame.from_text("neighbors ; level = states ; of = Rajasthan", score=-0.081)]
    g = group_frames(fs, q, T, margin=2.0)
    assert [f.to_text() for f in g] == ["neighbors ; level = states ; of = Rajasthan"] and g[0].score == -0.069
