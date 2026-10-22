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
