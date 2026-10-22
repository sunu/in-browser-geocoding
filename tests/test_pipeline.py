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


def _parser(provider, **kw):
    from geoparse.parse.pipeline import Parser

    return Parser(Decider(default=provider, logger=NullLogger(), use_ner=False, **kw))


@pytest.fixture(scope="module")
def rules_parser():
    return _parser("rules")


@pytest.fixture(scope="module")
def jev_parser():
    return _parser("jev", jev_mode="replay", jev_cache=str(ROOT / "tests" / "fixtures" / "jev_cache.jsonl"))


@pytest.mark.parametrize("gid", CASES)
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
