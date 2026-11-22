"""Closed option lists, keyword matching, and parsers for distance and number slots."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

import yaml

from geoparse.config import PACKAGE_DIR, load_config
from geoparse.dsl.schema import DIRECTION_MODES, LAYERS, QUANTIFIERS, RANK_BY, RANK_ORDERS, SOURCES


@lru_cache(maxsize=1)
def options() -> dict[str, Any]:
    return yaml.safe_load((PACKAGE_DIR / "data" / "options.yaml").read_text())


@lru_cache(maxsize=1)
def categories() -> dict[str, Any]:
    data = json.loads((PACKAGE_DIR / "data" / "categories.json").read_text())
    data.pop("_doc", None)
    return data


@lru_cache(maxsize=1)
def lexicon() -> dict[str, Any]:
    return json.loads((PACKAGE_DIR / "data" / "lexicon.json").read_text())


def category_leaves() -> dict[str, dict[str, Any]]:
    return {k: v for g in categories().values() for k, v in g["items"].items()}


def option_descriptions(ref: str) -> dict[str, str]:
    """Option key to description, in a fixed order."""
    if ref == "categories":
        return {k: v["description"] for k, v in categories().items()}
    return {k: v["description"] for k, v in options()[ref].items()}


def option_keywords(ref: str) -> dict[str, list[str]]:
    if ref == "categories":
        return {k: v["keywords"] for k, v in category_leaves().items()}
    return {k: v.get("keywords", []) for k, v in options()[ref].items()}


def choices() -> dict[str, list[str]]:
    """Valid values for each closed argument in the DAG validator."""
    o = options()
    return {
        "admin_levels": [k for k in o["admin_levels"] if k != "none"],
        "directions": list(o["directions"]),
        "predicates": list(o["predicates"]),
        "attrs": list(o["attrs"]),
        "ops": list(o["ops"]),
        "categories": list(category_leaves()),
        "lexicon": list(lexicon()),
        "layers": LAYERS,
        "direction_modes": DIRECTION_MODES,
        "sources": SOURCES,
        "natural_kinds": list(o["natural_kinds"]),
        "rank_by": RANK_BY,
        "rank_orders": RANK_ORDERS,
        "quantifiers": QUANTIFIERS,
    }


# ---------------------------------------------------------------- keyword matching


def _edit1(a: str, b: str) -> bool:
    """True if a and b differ by at most one edit (insert, delete, substitute, or swap)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s<>=&+-]", " ", text.lower())).strip()


def keyword_hits(text: str, keywords: list[str], typo: bool = True) -> int:
    """Number of words in `text` covered by keywords. With typo, words of 5 or more letters can have one typo."""
    t = norm(text)
    words = t.split()
    covered = set()
    for kw in sorted(keywords, key=len, reverse=True):
        kws = kw.split()
        n = len(kws)
        for i in range(len(words) - n + 1):
            if any(j in covered for j in range(i, i + n)):
                continue
            ok = all(w == k or (typo and len(k) >= 5 and _edit1(w, k)) for w, k in zip(words[i:i + n], kws))
            if ok:
                covered.update(range(i, i + n))
    return len(covered)


def best_keyword_option(text: str, ref: str) -> tuple[str | None, int]:
    best, best_n = None, 0
    for key, kws in option_keywords(ref).items():
        n = keyword_hits(text, kws)
        if n > best_n:
            best, best_n = key, n
    return best, best_n


# ---------------------------------------------------------------- distance and value parsers

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
              "ten": 10, "fifteen": 15, "twenty": 20, "fifty": 50, "hundred": 100, "half": 0.5, "a": 1}
_UNITS = {
    "km": 1000, "kms": 1000, "kilometer": 1000, "kilometers": 1000, "kilometre": 1000, "kilometres": 1000, "k": 1000,
    "m": 1, "mtr": 1, "mtrs": 1, "meter": 1, "meters": 1, "metre": 1, "metres": 1,
    "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
}
_NUM = r"(\d+(?:[.,]\d+)?|" + "|".join(_NUM_WORDS) + r")"
DISTANCE_RE = re.compile(rf"^(?:a\s+)?{_NUM}\s*(?:-\s*)?({'|'.join(sorted(_UNITS, key=len, reverse=True))})\.?(?:\s+radius)?$", re.I)
DISTANCE_SEARCH = re.compile(rf"\b{_NUM}\s*(?:-\s*)?({'|'.join(sorted(_UNITS, key=len, reverse=True))})\b", re.I)


def _num(s: str) -> float:
    s = s.lower()
    if s in _NUM_WORDS:
        return float(_NUM_WORDS[s])
    return float(s.replace(",", ""))


def parse_distance(text: str) -> float | None:
    """'2 km' -> 2000.0. Returns None if the text is not one distance."""
    m = DISTANCE_RE.match(text.strip())
    if not m:
        return None
    return _num(m.group(1)) * _UNITS[m.group(2).lower()]


_SCALE = {"thousand": 1e3, "k": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "million": 1e6,
          "millions": 1e6, "mn": 1e6, "m": 1e6, "crore": 1e7, "crores": 1e7, "cr": 1e7, "billion": 1e9}
VALUE_RE = re.compile(r"^(\d+(?:[.,]\d+)*|one|two|three|four|five|ten|a)\s*(" + "|".join(sorted(_SCALE, key=len, reverse=True)) + r")?$", re.I)


def parse_value(text: str) -> float | None:
    """'1 million' -> 1000000.0, '10 lakh' -> 1000000.0, '500,000' -> 500000.0."""
    m = VALUE_RE.match(text.strip())
    if not m:
        return None
    n = m.group(1).lower()
    if n == "a" and not m.group(2):
        return None  # "a" is a number only with a scale word ("a million")
    base = float(_NUM_WORDS[n]) if n in _NUM_WORDS else float(n.replace(",", ""))
    return base * _SCALE.get((m.group(2) or "").lower(), 1)


def default_distance_m() -> float:
    return float(load_config()["policy"]["default_near_m"])
