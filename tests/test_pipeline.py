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
