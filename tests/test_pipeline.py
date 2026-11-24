"""Pipeline tests on gold records. They need the local extract (data/build/geoparse.duckdb).

The Jev tests replay recorded responses from tests/fixtures/jev_cache.jsonl. No network.
If a request changes (for example a new instruction text), re-record with:
  uv run python -m gold.run_gold --provider jev --jev-mode cached
"""
import json
from pathlib import Path

import pytest

from geoparse.config import build_dir
from geoparse.decisions.functions import Decider
from geoparse.decisions.log import NullLogger

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (build_dir() / "geoparse.duckdb").exists(), reason="local extract not built")

GOLD = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "gold" / "gold.jsonl").read_text().splitlines()}
CASES = ["g001", "g012", "g024", "g035", "g049", "g050", "g058", "g071", "g076", "g085", "g090", "g094"]


def _parser(provider, use_t5=False, **kw):
    from geoparse.parse.pipeline import Parser

    return Parser(Decider(default=provider, logger=NullLogger(), use_ner=False, **kw), use_t5=use_t5)


@pytest.fixture(scope="module")
def rules_parser():
    return _parser("rules")


@pytest.fixture(scope="module")
def jev_parser():
    return _parser("jev", jev_mode="replay", jev_cache=str(ROOT / "tests" / "fixtures" / "jev_cache.jsonl"))


RULES_XFAIL = {"g090": "rules baseline picks children_touching since the vocabulary checks were removed (plan-005)"}


@pytest.mark.parametrize("gid", [pytest.param(g, marks=pytest.mark.xfail(reason=RULES_XFAIL[g], strict=True))
                                 if g in RULES_XFAIL else g for g in CASES])
def test_rules_pipeline_matches_gold(rules_parser, gid):
    from gold.run_gold import canon

    rec = GOLD[gid]
    p = rules_parser.parse(rec["query"])
    assert p.ok, p.unsupported
    assert canon(p.dag) == canon(rec["dag"])


@pytest.mark.parametrize("gid", ["g035", "g085", "g090"])
def test_jev_replay_pipeline_matches_gold(jev_parser, gid):
    from gold.run_gold import canon

    rec = GOLD[gid]
    p = jev_parser.parse(rec["query"])
    assert p.ok, p.unsupported
    assert canon(p.dag) == canon(rec["dag"])
    assert any(t["impl"] == "jev" for t in p.trace)


def test_unsupported_is_returned_not_guessed(rules_parser):
    p = rules_parser.parse("which states touch the sea")
    assert not p.ok and p.unsupported is not None
    assert p.trace


def test_simple_and_complex_path(rules_parser):
    assert rules_parser.parse("2 km around MG Road Bangalore").path == "simple"
    assert rules_parser.parse("Kerala and Tamil Nadu").path == "complex"


def _t5_available():
    try:
        from geoparse.t5.model import model_dir

        d = model_dir()
        import transformers  # noqa: F401

        return d is not None and d.exists()
    except ImportError:
        return False


@pytest.mark.skipif(not _t5_available(), reason="T5 model or runtime not available")
@pytest.mark.parametrize("query,template,parent", [
    ("coastal districts in Gujarat", "children_with_predicate", "Gujarat"),
    ("coastal districts of Odisha", "children_with_predicate", "Odisha"),
])
def test_t5_rules_pipeline(query, template, parent):
    p = _parser("rules", use_t5=True)
    r = p.parse(query)
    assert r.ok, r.unsupported
    assert r.template == template and r.slots["parent"] == parent
    assert any(t["decision"] == "generate_frames" for t in r.trace)


@pytest.mark.skipif(not _t5_available(), reason="T5 model or runtime not available")
def test_t5_unsupported_gate():
    p = _parser("rules", use_t5=True)
    r = p.parse("what is the weather in Pune")
    assert not r.ok and "T5" in r.unsupported.reason


def test_direction_rest():
    from geoparse.parse.pipeline import _direction_rest

    assert _direction_rest("northern France") == "France"
    assert _direction_rest("north-east India") == "India"
    assert _direction_rest("Northampton") is None
    # One- and two-letter direction words ("n", "se") are not used.
    assert _direction_rest("n Karnataka") is None


def test_qualified_name(rules_parser):
    # "A, B": the A inside B. Not a qualified name if no candidate of A is inside B (a union).
    dec = rules_parser.base_decider.fork()
    q = rules_parser._qualified(dec, "Jayanagar, Bengaluru", 0)
    assert q and q["args"]["name"] == "Jayanagar" and q["args"]["context"] == "Bengaluru"
    blr = {c.id for c in rules_parser.store.search("Bengaluru", fuzzy=False, limit=5)}
    jay = rules_parser.store.describe([q["args"]["id"]])[q["args"]["id"]]
    assert blr & set(jay["ancestor_ids"])
    assert rules_parser._qualified(dec, "Kerala, Tamil Nadu", 0) is None
    assert rules_parser._qualified(dec, "Kerala, Goa and Karnataka", 0) is None


def test_qualified_name_with_in(rules_parser):
    # "A in B" (template review G10): exact names only, and never a set ("districts in Kerala").
    dec = rules_parser.base_decider.fork()
    q = rules_parser._qualified(dec, "Jayanagar in Bengaluru", 0)
    assert q and q["args"]["name"] == "Jayanagar" and q["args"]["context"] == "Bengaluru"
    for text in ("districts in Kerala", "hospitals in Pune", "rivers in Kerala", "northern Kerala in India"):
        assert rules_parser._qualified(dec, text, 0) is None, text


def test_list_parts(rules_parser):
    # Lists of places (plan-036): exact names cut at whole-word separators; a leading word gives the quantifier.
    dec = rules_parser.base_decider.fork()
    lp = rules_parser._list_parts
    assert lp(dec, "Kerala and Goa", False) == (["Kerala", "Goa"], "and", None)
    assert lp(dec, "Kerala or Goa", False) == (["Kerala", "Goa"], "or", None)
    assert lp(dec, "Karnataka, Kerala and Goa", False) == (["Karnataka", "Kerala", "Goa"], "and", None)
    assert lp(dec, "both Kerala and Goa", False) == (["Kerala", "Goa"], "and", "all")
    assert lp(dec, "either Kerala or Goa", False) == (["Kerala", "Goa"], "or", "any")
    assert lp(dec, "Kerala n Goa", False) == (["Kerala", "Goa"], "and", None)
    # Commas alone are a qualified name, not a list; a part that is not an exact name stops the list.
    assert lp(dec, "Salt Lake, Kolkata", False) is None
    assert lp(dec, "coastal districts of Kerala and Goa", False) is None
    # A space is a separator only where the template allows it ("India Pakistan border").
    assert lp(dec, "India Pakistan", False) is None
    assert lp(dec, "India Pakistan", True) == (["India", "Pakistan"], "and", None)


def test_list_keeps_names_with_and(rules_parser):
    # "Jammu and Kashmir" is one exact name: the slot is the place, not a list.
    p = rules_parser.parse("districts of Jammu and Kashmir")
    assert p.ok, p.unsupported
    assert p.dag["args"]["of"]["op"] == "Resolve"


def test_frame_coverage(rules_parser):
    # A frame that leaves out a place name of the query loses to a frame that uses all of them (plan-038).
    from geoparse.t5.frames import Frame

    dec = rules_parser.base_decider.fork()
    q = "Kerala, Goa and Karnataka"
    two = Frame(template="union", slots={"a": "Kerala", "b": "Goa"})
    three = Frame(template="union3", slots={"a": "Kerala", "b": "Goa", "c": "Karnataka"})
    assert rules_parser._dropped_names(dec, two, q) == ["Karnataka"]
    assert rules_parser._covering(dec, [two, three], q, 0) == [three]
    # If all frames leave out the name, they all stay, with a note.
    assert rules_parser._covering(dec, [two], q, 0) == [two]
    assert "'Karnataka' is not used in the result" in dec.notes


def test_extend_slot_to_exact_name(rules_parser):
    from geoparse.t5.frames import Frame

    dec = rules_parser.base_decider.fork()
    f = Frame(template="children", slots={"level": "districts", "parent": "Tamil"})
    assert rules_parser._extend_slots(dec, [f], "districts of Tamil Nadu", 0)[0].slots["parent"] == "Tamil Nadu"


def test_same_text_in_two_slots():
    from geoparse.t5.frames import Frame, check_frame
    from geoparse.templates.model import all_templates

    f = Frame(template="intersection", slots={"a": "Kerala", "b": "Kerala"})
    assert "the same text in two region slots" in check_frame(f, "overlap of Kerala and Kerala", all_templates())


def test_frame_list_and_within(rules_parser):
    # plan-039: the parts of a list and the qualifier come from the frame, not from a cut of the text.
    from geoparse.t5.frames import Frame

    dec = rules_parser.base_decider.fork()
    tpl = rules_parser.templates["children"]
    q = "districts of Kerala or Goa"
    dag, info = rules_parser._region(dec, tpl, "Kerala | Goa", [], q, 0, None)
    assert dag["op"] == "Union" and info["conj"] == "or" and [x for x in info["list"]] == ["Kerala", "Goa"]
    look = rules_parser.templates["lookup_place"]
    dag, _ = rules_parser._region(dec, look, "Jayanagar", [], "Jayanagar, Bengaluru", 0, None, within="Bengaluru")
    assert dag["args"]["name"] == "Jayanagar" and dag["args"]["context"] == "Bengaluru"
    ok = Frame(template="lookup_place", slots={"anchor": "Jayanagar", "anchor.within": "Bengaluru"})
    bad = Frame(template="lookup_place", slots={"anchor": "Jayanagar", "anchor.within": "Kerala"})
    assert rules_parser._within_faults(dec, ok) == []
    assert rules_parser._within_faults(dec, bad) == ["no place 'Jayanagar' is inside 'Kerala'"]
