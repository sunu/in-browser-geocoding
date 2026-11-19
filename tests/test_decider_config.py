"""Per-decision provider policy (plan-006 section 3.1)."""
import copy

from geoparse.config import load_config
from geoparse.decisions.functions import Decider
from geoparse.decisions.log import NullLogger
from geoparse.decisions.providers import JevProvider, RulesProvider


def _decider(providers: dict[str, str]) -> Decider:
    cfg = copy.deepcopy(load_config())
    cfg["decisions"]["providers"] = providers
    return Decider(config=cfg, logger=NullLogger(), use_ner=False, jev_mode="replay")


def test_most_specific_key_wins():
    d = _decider({"fill_closed_slot": "rules", "fill_closed_slot.category": "jev", "pick_template": "rules"})
    assert d.provider_name("fill_closed_slot.admin_level") == "rules"
    assert d.provider_name("fill_closed_slot.category") == "jev"
    assert d.provider_name("fill_closed_slot.category.group") == "jev"
    assert d.provider_name("pick_template_flat") == "rules"
    assert isinstance(d.provider("fill_closed_slot.category.group"), JevProvider)
    assert isinstance(d.provider("fill_closed_slot.op"), RulesProvider)


def test_default_overrides_config():
    cfg = copy.deepcopy(load_config())
    d = Decider(config=cfg, default="rules", logger=NullLogger(), use_ner=False)
    assert all(d.provider_name(k) == "rules" for k in cfg["decisions"]["providers"])


def test_providers_are_created_lazily():
    d = _decider({"pick_family": "jev", "is_subquery": "local"})
    # The local model is not loaded until a local decision is asked.
    assert "local" not in d._impls
    d.provider("pick_family")
    assert set(d._impls) == {"jev"}


def test_rules_provider_dispatches_on_full_decision_name():
    from geoparse.decisions.types import Decision, Question

    seen = []
    p = RulesProvider({"fill_closed_slot": lambda t, q, o: seen.append(q.id) or Decision[str](value="a", confidence=1, impl="r")})
    p.choose("x", Question(id="fill_closed_slot.category.group", instructions="?"), {"a": "A", "b": "B"})
    assert seen == ["fill_closed_slot.category.group"]


def test_local_falls_back_to_jev_without_model(monkeypatch, tmp_path):
    import warnings

    monkeypatch.setenv("GEOPARSE_LOCAL_DIR", str(tmp_path / "missing"))
    d = _decider({"pick_family": "local"})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        p = d.provider("pick_family")
    assert isinstance(p, JevProvider) and any("local decision model" in str(x.message) for x in w)


def _local_available():
    from geoparse.config import REPO_ROOT

    return (REPO_ROOT / "models" / "local" / "current").exists()


import pytest  # noqa: E402


@pytest.mark.skipif(not _local_available(), reason="local model not built")
def test_local_provider_answers_closed_slots():
    from geoparse.decisions.functions import Decider as D

    d = _decider({"fill_closed_slot": "local"})
    r = d.fill_closed_slot("near the sea", "predicate", "predicates", allow_none=True)
    assert r.value == "coastal" and r.impl.startswith("local:")
    r = d.fill_closed_slot("petrol bunks", "category", "categories", allow_none=True)
    assert r.value == "fuel"


def test_level_words_skip_the_model():
    # A keyword of one level with no typo gives that level ("counties" is one typo from "countries").
    d = _decider({"fill_closed_slot": "jev"}).fork()
    levels = {"country": "", "state": "", "district": "", "city": "", "village": "", "union_territory": ""}
    assert d._level_word("counties", levels) == "district"
    assert d._level_word("prefectures", levels) == "state"
    assert d._level_word("local government areas", levels) == "district"
    assert d._level_word("states and districts", levels) is None
    assert d._level_word("municipalities", levels) == "city"
    d.view_country = "MX"
    assert d._level_word("municipalities", levels) == "district"
    r = d.fill_closed_slot("counties", "admin_level", "admin_levels")
    assert (r.value, r.impl) == ("district", "keyword")


def test_street_word_typo_needs_a_weak_gazetteer_match():
    from geoparse.decisions.rules import select_source
    from geoparse.decisions.types import Question

    def src(text, score):
        return select_source(text, Question(id="select_source", instructions="", context={"text": text, "gazetteer_top_score": score}),
                             {"overture": "", "photon": ""}).value

    assert src("Minas Gerais", 1.4) == "overture"
    assert src("Minas Gerais", 0.5) == "photon"
    assert src("Qutub Minar", 1.4) == "photon"
