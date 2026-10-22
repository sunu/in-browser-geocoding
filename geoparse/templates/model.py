"""Template format, loader, and split pattern matcher.

Pattern syntax (one string, matched against the words of the query, case-insensitive):
  {name}             a segment for slot `name` (one or more words)
  {group:s1,s2}      a segment named `group` that feeds the closed slots s1 and s2
  word               a literal word
  (a|b c|d)          one of the alternatives; an alternative can have more than one word
  [a|b]              optional: one of the alternatives, or nothing
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from geoparse.dsl.schema import parse_dag_text

TEMPLATE_DIR = Path(__file__).resolve().parent

OPEN_TYPES = {"region", "anchor"}
CLOSED_TYPES = {"admin_level", "predicate", "direction", "category", "attr", "op"}
PARSED_TYPES = {"distance", "value"}


class SlotDef(BaseModel):
    type: str
    options_ref: str | None = None
    default: Any = None
    optional: bool = False


class Template(BaseModel):
    id: str
    family: str
    description: str
    examples: list[str] = Field(default_factory=list)
    slots: dict[str, SlotDef]
    patterns: list[str]
    dag: str

    @property
    def dag_json(self) -> Any:
        return _parse_dag_cached(self.dag)

    def open_slots(self) -> list[str]:
        return [k for k, s in self.slots.items() if s.type in OPEN_TYPES]


class Family(BaseModel):
    id: str
    description: str
    templates: list[Template]


@lru_cache(maxsize=None)
def _parse_dag_cached(s: str) -> Any:
    return parse_dag_text(s)


@lru_cache(maxsize=None)
def load_families(directory: str | None = None) -> dict[str, Family]:
    d = Path(directory) if directory else TEMPLATE_DIR
    fams: dict[str, Family] = {}
    for p in sorted(d.glob("*.yaml")):
        raw = yaml.safe_load(p.read_text())
        fid = raw["family"]
        templates = [Template(family=fid, **t) for t in raw["templates"]]
        fams[fid] = Family(id=fid, description=raw["description"], templates=templates)
    return fams


def all_templates(directory: str | None = None) -> dict[str, Template]:
    return {t.id: t for f in load_families(directory).values() for t in f.templates}


# ---------------------------------------------------------------- pattern matching

_WORD = re.compile(r"[\w][\w'’.-]*[\w]|[\w]|[,&<>]=?|\+")


def words_of(text: str) -> list[tuple[str, int, int]]:
    """Words with character offsets. Commas, '&', '<' and '>' are separate words."""
    return [(m.group().lower(), m.start(), m.end()) for m in _WORD.finditer(text)]


class Seg(BaseModel):
    kind: str  # "slot" or "lit"
    name: str = ""
    feeds: list[str] = Field(default_factory=list)
    alts: list[list[str]] = Field(default_factory=list)
    optional: bool = False


_PAT_TOKEN = re.compile(r"\{([a-z_]+)(?::([a-z_,]+))?\}|\(([^)]*)\)|\[([^\]]*)\]|(\S+)")


@lru_cache(maxsize=None)
def compile_pattern(pattern: str) -> tuple[Seg, ...]:
    segs = []
    for m in _PAT_TOKEN.finditer(pattern):
        slot, feeds, alts, opt, word = m.groups()
        if slot:
            segs.append(Seg(kind="slot", name=slot, feeds=feeds.split(",") if feeds else [slot]))
        elif alts is not None:
            segs.append(Seg(kind="lit", alts=[a.split() for a in alts.split("|")]))
        elif opt is not None:
            segs.append(Seg(kind="lit", alts=[a.split() for a in opt.split("|")], optional=True))
        else:
            segs.append(Seg(kind="lit", alts=[[word.lower()]]))
    return tuple(segs)


def match_pattern(pattern: str, text: str, max_results: int = 50) -> list[dict[str, Any]]:
    """Return every way the pattern matches the full text.

    Each result is {"segments": {name: text}, "feeds": {name: [slots]}, "literals": n}.
    """
    segs = compile_pattern(pattern)
    words = words_of(text)
    toks = [w for w, _, _ in words]
    results: list[dict[str, Any]] = []

    def span_text(a: int, b: int) -> str:
        return text[words[a][1]:words[b - 1][2]]

    def rec(si: int, wi: int, acc: dict[str, tuple[int, int]], lits: int):
        if len(results) >= max_results:
            return
        if si == len(segs):
            if wi == len(toks):
                results.append({
                    "segments": {k: span_text(a, b) for k, (a, b) in acc.items()},
                    "feeds": {s.name: s.feeds for s in segs if s.kind == "slot" and s.name in acc},
                    "literals": lits,
                })
            return
        seg = segs[si]
        if seg.kind == "lit":
            for alt in seg.alts:
                if toks[wi:wi + len(alt)] == alt:
                    rec(si + 1, wi + len(alt), acc, lits + len(alt))
            if seg.optional:
                rec(si + 1, wi, acc, lits)
            return
        # slot: one or more words
        for end in range(wi + 1, len(toks) + 1):
            acc2 = dict(acc)
            acc2[seg.name] = (wi, end)
            rec(si + 1, end, acc2, lits)

    rec(0, 0, {}, 0)
    return results
