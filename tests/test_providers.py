import json
from pathlib import Path

import pytest

from geoparse.decisions.providers import JevProvider, ProviderError, RulesProvider, choice_confidence
from geoparse.decisions.types import Decision, Question

FIX = Path(__file__).parent / "fixtures" / "jev_cache.jsonl"


def test_choice_confidence_formula():
    assert choice_confidence({"a": 1.0, "b": 0.0}) == 1.0
    assert choice_confidence({"a": 0.5, "b": 0.5}) == 0.0
    assert choice_confidence({"a": 0.6, "b": 0.2, "c": 0.2}) == pytest.approx(0.4)


def test_parse_noul_confidence():
    d = JevProvider.parse_noul({"type": "noul", "noul": 0.9}, {}, {"text": "x"})
    assert d.value is True and d.confidence == pytest.approx(0.8)


def test_jev_replay_hit_and_miss(tmp_path):
    rec = json.loads(FIX.read_text().splitlines()[0])
    cache = tmp_path / "c.jsonl"
    cache.write_text(json.dumps(rec) + "\n")
    p = JevProvider(mode="replay", cache_path=cache, api_key="none")
    with pytest.raises(ProviderError):
        p.choose({"query": "not in the cache"}, Question(id="pick_family", instructions="?"), {"a": "A", "b": "B"})
    # The fixture key is the hash of the full request body. Rebuild the body from the stored response is not
    # possible, so check that the cache loaded the record.
    assert rec["key"] in p._cache


def test_rules_provider_dispatch():
    called = {}

    def rule(text, q, options):
        called["id"] = q.id
        return Decision[str](value="b", confidence=0.9, impl="rules-v1")

    p = RulesProvider({"pick_family": rule})
    d = p.choose("x", Question(id="pick_family", instructions="?"), {"a": "A", "b": "B"})
    assert d.value == "b" and called["id"] == "pick_family"
    with pytest.raises(ProviderError):
        p.choose("x", Question(id="unknown", instructions="?"), {"a": "A"})
