from __future__ import annotations

import json

from geoparse.config import REPO_ROOT
from geoparse.execute.data import norm_name


def test_fixture_matches_norm_name():
    # web/test/core.test.ts checks the same file against the TS normName.
    cases = json.loads((REPO_ROOT / "web" / "test" / "fixtures" / "norm_names.json").read_text())
    assert len(cases) > 30
    assert [k for _, k in cases] == [norm_name(n) for n, _ in cases]


def test_norm_name_examples():
    assert norm_name("Tamil-Nadu ") == "tamil nadu"
    assert norm_name("Łódź") == "lodz"
    assert norm_name("Москва") == "москва"
    assert norm_name("मुंबई") == "मुंबई"
    assert norm_name("St. John's") == "st john s"
