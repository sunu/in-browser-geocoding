"""Parse pipeline: query -> template -> slots -> DAG, with recursion for region slots.

Procedure for one level (plan-001 section 4.3):
 1. Find every template whose split patterns match the text, and drop splits that fail a hard check
    (a distance slot must parse as a distance, a closed-slot segment must contain a known keyword).
 2. pick_family, then pick_template, among the templates that matched.
 3. pick_split among the candidate splits of the chosen template.
 4. For each region slot: lexicon first; else is_subquery; a sub-query recurses (depth limit).
 5. Fill closed slots. The independent decisions of one level run in parallel threads.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel, Field

from geoparse.config import load_config
from geoparse.decisions.functions import Decider
from geoparse.decisions.rules import template_score
from geoparse.decisions.types import Span, Split
from geoparse.dsl.schema import PREDICATE_DAGS, substitute, validate
from geoparse.options import (choices, keyword_hits, lexicon, option_keywords, parse_distance, parse_value,
                              norm)
from geoparse.templates.model import CLOSED_TYPES, OPEN_TYPES, Template, load_families, match_pattern

SIMPLE_FAMILIES = {"lookup", "modifier"}
# Families whose anchors can go to the geocoder. "features" is here because plan-002 routes POIs to Photon.
GEOCODER_FAMILIES = {"lookup", "modifier", "features"}

LEADING_FILLERS = [
    "show me the", "show me", "show the", "show", "find me", "find the", "find", "list the", "list all", "list",
    "give me the", "give me", "get me", "get", "map of the", "map of", "map", "where is the", "where is",
    "where are the", "where are", "what are the", "what are", "which are the", "all the", "all of the", "the",
]


FILLER_WORDS = ["the", "all", "a", "an", "any", "some", "of the"]


def _generic_words() -> list[str]:
    words = list(FILLER_WORDS) + ["of", "in", "and", "that", "which", "with"]
    for ref in ("admin_levels", "predicates"):
        words += sum(option_keywords(ref).values(), [])
    return words


class Unsupported(BaseModel):
    reason: str
    decision: str | None = None
    depth: int = 0
    text: str = ""


class ParseResult(BaseModel):
    query: str
    ok: bool
    dag: dict[str, Any] | None = None
    unsupported: Unsupported | None = None
    family: str | None = None
    template: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    path: str | None = None  # simple or complex
    trace: list[dict[str, Any]] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)

    @property
    def n_model_calls(self) -> int:
        return sum(1 for t in self.trace if t["impl"] not in ("deterministic",) and t["decision"] != "extract_spans")


class _Stop(Exception):
    def __init__(self, u: Unsupported):
        self.u = u


def normalize_query(q: str) -> str:
    q = q.strip().rstrip("?.! ").strip()
    q = re.sub(r"\s+", " ", q)
    low = q.lower()
    changed = True
    while changed:
        changed = False
        for f in LEADING_FILLERS:
            if low.startswith(f + " ") and len(low) > len(f) + 1:
                q = q[len(f) + 1:]
                low = q.lower()
                changed = True
                break
    return q


def lexicon_match(text: str) -> str | None:
    t = norm(text)
    t = re.sub(r"^the ", "", t)
    for key, entry in lexicon().items():
        if t in [norm(a) for a in entry["aliases"]]:
            return key
    return None


def _slot_default(sd) -> Any:
    v = sd.default
    if isinstance(v, str) and v.startswith("policy."):
        return float(load_config()["policy"][v.split(".", 1)[1]])
    return v


class Parser:
    def __init__(self, decider: Decider | None = None, store=None, config: dict[str, Any] | None = None,
                 two_step: bool = True, prune_by_pattern: bool = True, max_workers: int = 32):
        self.base_decider = decider or Decider()
        self.cfg = config or load_config()
        self.max_depth = int(self.cfg["decisions"]["max_depth"])
        self.two_step = two_step
        self.prune = prune_by_pattern
        self.families = load_families()
        self.templates = {t.id: t for f in self.families.values() for t in f.templates}
        self._store = store
        self.pool = ThreadPoolExecutor(max_workers=max_workers)

    @property
    def store(self):
        if self._store is None:
            from geoparse.execute.data import get_store

            self._store = get_store()
        return self._store

    # ------------------------------------------------------------ public

    def parse(self, query: str) -> ParseResult:
        dec = self.base_decider.fork()
        t0 = time.time()
        res = ParseResult(query=query, ok=False)
        try:
            dag, info = self._parse_level(dec, normalize_query(query), depth=0)
            errors = validate(dag, choices())
            if errors:
                raise _Stop(Unsupported(reason="invalid DAG: " + "; ".join(errors)))
            res.ok, res.dag = True, dag
            res.family, res.template, res.slots = info["family"], info["template"], info["slots"]
            res.path = "simple" if info["family"] in SIMPLE_FAMILIES and _plain_anchors(dag) else "complex"
        except _Stop as s:
            res.unsupported = s.u
            dec.logger.unsupported(run_id=dec.run_id, query=query, reason=s.u.reason, trace=dec.trace)
        res.trace = dec.trace
        res.timings["parse_s"] = round(time.time() - t0, 3)
        return res

    # ------------------------------------------------------------ one level

    def candidates(self, text: str) -> dict[str, list[dict[str, Any]]]:
        """Template id -> list of valid split matches."""
        out: dict[str, list[dict[str, Any]]] = {}
        for t in self.templates.values():
            seen = set()
            for pat in t.patterns:
                for m in match_pattern(pat, text):
                    if not self._valid(t, m):
                        continue
                    key = tuple(sorted(m["segments"].items()))
                    if key in seen:
                        continue
                    seen.add(key)
                    m["score"] = self._score(t, m)
                    out.setdefault(t.id, []).append(m)
        # Splits that differ only in the grouping of closed slots are the same split. Keep the best one.
        for tid, ms in out.items():
            t = self.templates[tid]
            best: dict[tuple, dict[str, Any]] = {}
            for m in ms:
                seg_of = {s: seg for seg, fed in m["feeds"].items() for s in fed}
                key = tuple(sorted((n, norm(m["segments"][seg_of[n]])) for n, sd in t.slots.items()
                                   if n in seg_of and sd.type not in CLOSED_TYPES))
                if key not in best or m["score"] > best[key]["score"]:
                    best[key] = m
            out[tid] = list(best.values())
        return out

    def _valid(self, t: Template, m: dict[str, Any]) -> bool:
        for seg_name, text in m["segments"].items():
            fed = m["feeds"][seg_name]
            types = {t.slots[s].type for s in fed if s in t.slots}
            if "distance" in types and parse_distance(text) is None:
                return False
            if "value" in types and parse_value(text) is None:
                return False
            if types & OPEN_TYPES:
                w = norm(text).split()
                if not w or w[0] in ("and", "or", "of", "in", "with", "except") or w[-1] in ("and", "or", "of", "in", "with"):
                    return False
                # A place cannot be only level, predicate, and stop words ("states", "coastal districts").
                if keyword_hits(text, _generic_words()) >= len(w) and not lexicon_match(text):
                    return False
            closed = [t.slots[s] for s in fed if s in t.slots and t.slots[s].type in CLOSED_TYPES]
            if closed:
                # Every word of a closed-slot segment must be a keyword of its options (or a filler word).
                kws = sum((sum(option_keywords(sd.options_ref).values(), []) for sd in closed), []) + FILLER_WORDS
                if keyword_hits(text, kws) < len(norm(text).split()):
                    return False
        return True

    def _score(self, t: Template, m: dict[str, Any]) -> float:
        closed = {}
        for seg, fed in m["feeds"].items():
            refs = [t.slots[s].options_ref for s in fed if s in t.slots and t.slots[s].type in CLOSED_TYPES]
            if refs:
                closed[seg] = refs
        bonus = 0.0
        for seg, fed in m["feeds"].items():
            if any(t.slots[s].type in ("distance", "value") for s in fed if s in t.slots):
                bonus += 1.0
        for seg, fed in m["feeds"].items():
            # Lexicon first: a segment that is a named set is a strong sign of a correct split.
            if any(t.slots[s].type in OPEN_TYPES for s in fed if s in t.slots) and lexicon_match(m["segments"][seg]):
                bonus += 2.0
        if t.family == "lookup":
            return -0.5
        return template_score(m["literals"], closed, m["segments"]) + bonus

    def _parse_level(self, dec: Decider, text: str, depth: int) -> tuple[dict[str, Any], dict[str, Any]]:
        lex = lexicon_match(text)
        if lex:
            return ({"op": "LexiconSet", "args": {"key": lex}},
                    {"family": "lookup", "template": "lookup_place", "slots": {"anchor": {"lex": lex, "text": text}}})
        spans = dec.extract_spans(text, depth=depth).value
        cands = self.candidates(text)
        if not self.prune:
            cands = {tid: cands.get(tid, []) for tid in self.templates}
        if not any(cands.values()):
            raise _Stop(Unsupported(reason="no template pattern matches the text", depth=depth, text=text))
        tscores = {tid: max((m["score"] for m in ms), default=-9) for tid, ms in cands.items()}
        tfam = {tid: self.templates[tid].family for tid in cands}
        ctx = {"template_scores": tscores, "template_family": tfam}

        if self.two_step:
            fams = {f: self.families[f].description for f in self.families if any(tfam[t] == f for t in cands)}
            fd = dec.pick_family(text, spans, fams, depth=depth, context=ctx)
            if dec.below("pick_family", fd):
                raise _Stop(Unsupported(reason=f"low confidence for pick_family ({fd.confidence:.2f})", decision="pick_family", depth=depth, text=text))
            family = fd.value
            topts = {tid: self._template_option(tid) for tid in cands if tfam[tid] == family}
            td = dec.pick_template(text, spans, family, topts, depth=depth, context=ctx)
        else:
            topts = {tid: self._template_option(tid) for tid in cands}
            td = dec.pick_template_flat(text, spans, topts, depth=depth, context=ctx)
        if dec.below("pick_template", td):
            raise _Stop(Unsupported(reason=f"low confidence for pick_template ({td.confidence:.2f})", decision="pick_template", depth=depth, text=text))
        tpl = self.templates[td.value]
        matches = cands.get(tpl.id, [])
        if not matches:
            raise _Stop(Unsupported(reason=f"template {tpl.id} has no valid split", decision="pick_split", depth=depth, text=text))

        splits = [Split(parts=m["segments"]) for m in matches]
        sd = dec.pick_split(text, tpl.description, splits, depth=depth, labels=self._labels(tpl, matches[0]),
                            context={"split_scores": {f"s{i}": m["score"] for i, m in enumerate(matches)}})
        if dec.below("pick_split", sd):
            raise _Stop(Unsupported(reason=f"low confidence for pick_split ({sd.confidence:.2f})", decision="pick_split", depth=depth, text=text))
        match = next(m for m in matches if m["segments"] == sd.value.parts)

        values, slots = self._fill(dec, tpl, match, text, spans, depth)
        dag = substitute(tpl.dag_json, values)
        return dag, {"family": tpl.family, "template": tpl.id, "slots": slots}

    def _template_option(self, tid: str) -> str:
        t = self.templates[tid]
        ex = "; ".join(f"'{e}'" for e in t.examples[:2])
        return f"{t.description}. Examples: {ex}" if ex else t.description

    def _labels(self, tpl: Template, match: dict[str, Any]) -> dict[str, str]:
        labels = {}
        for seg, fed in match["feeds"].items():
            parts = []
            for s in fed:
                sd = tpl.slots.get(s)
                parts.append({"region": "place or area", "anchor": "place", "admin_level": "level",
                              "predicate": "property", "direction": "direction", "category": "category",
                              "attr": "quantity", "op": "comparison", "distance": "distance",
                              "value": "number"}.get(sd.type if sd else "", s))
            labels[seg] = " and ".join(dict.fromkeys(parts))
        return labels

    # ------------------------------------------------------------ slot filling

    def _fill(self, dec: Decider, tpl: Template, match: dict[str, Any], text: str, spans: list[Span],
              depth: int) -> tuple[dict[str, Any], dict[str, Any]]:
        seg_of = {s: seg for seg, fed in match["feeds"].items() for s in fed}
        values: dict[str, Any] = {}
        slots: dict[str, Any] = {}
        jobs = {}
        level_hint = None

        for name, sd in tpl.slots.items():
            seg = seg_of.get(name)
            seg_text = match["segments"].get(seg) if seg else None
            if sd.type == "distance":
                v = parse_distance(seg_text) if seg_text else None
                slots[name] = v
                values[name] = v if v is not None else _slot_default(sd)
            elif sd.type == "value":
                values[name] = slots[name] = parse_value(seg_text) if seg_text else _slot_default(sd)
            elif sd.type in CLOSED_TYPES:
                if seg_text is None:
                    slots[name] = sd.default
                    values[name] = None if sd.type == "admin_level" and sd.default == "none" else sd.default
                    continue
                jobs[name] = self.pool.submit(dec.fill_closed_slot, seg_text, sd.type, sd.options_ref, depth=depth,
                                              query=text, allow_none=sd.optional)

        # The admin level of the query is a type hint for the anchors of some templates.
        if "level" in jobs:
            lv = jobs["level"].result()
            level_hint = lv.value if lv.value != "none" else None
        for name, sd in tpl.slots.items():
            if sd.type in OPEN_TYPES:
                seg_text = match["segments"][seg_of[name]]
                hint = level_hint if tpl.id in ("neighbors",) else None
                jobs[name] = self.pool.submit(self._region, dec, tpl, seg_text, spans, text, depth, hint)

        for name, fut in jobs.items():
            sd = tpl.slots[name]
            try:
                r = fut.result()
            except _Stop:
                for f in jobs.values():
                    f.cancel()
                raise
            if sd.type in OPEN_TYPES:
                values[name], slots[name] = r
                continue
            if dec.below("fill_closed_slot", r):
                raise _Stop(Unsupported(reason=f"low confidence for slot {name} ({r.confidence:.2f})",
                                        decision="fill_closed_slot", depth=depth, text=text))
            slots[name] = r.value
            if sd.type == "predicate":
                values[name] = PREDICATE_DAGS[r.value]
            elif sd.type == "admin_level" and r.value == "none":
                values[name] = None
            else:
                values[name] = r.value
        return values, slots

    def _region(self, dec: Decider, tpl: Template, text: str, spans: list[Span], query: str, depth: int,
                type_hint: str | None) -> tuple[dict[str, Any], Any]:
        text = re.sub(r"^(the|a|an)\s+", "", text.strip(), flags=re.I)
        lex = lexicon_match(text)
        if lex:
            return {"op": "LexiconSet", "args": {"key": lex}}, {"lex": lex, "text": text}
        sd = tpl.slots
        is_region = any(s.type == "region" for s in sd.values()) and tpl.family != "lookup"
        exact = self.store.search(text, type_hint=type_hint, fuzzy=False, limit=3)
        if is_region:
            d = dec.is_subquery(text, depth=depth, context={"gazetteer_exact": bool(exact),
                                                             "has_distance": parse_distance(text) is not None
                                                             or bool(re.search(r"\d", text))})
            if dec.below("is_subquery", d):
                raise _Stop(Unsupported(reason=f"low confidence for is_subquery ({d.confidence:.2f})",
                                        decision="is_subquery", depth=depth, text=text))
            if d.value:
                if depth + 1 > self.max_depth:
                    raise _Stop(Unsupported(reason="depth limit", depth=depth, text=text))
                sub_dag, info = self._parse_level(dec, text, depth + 1)
                return sub_dag, {"q": text, "t": info["template"], "s": info["slots"]}
        return self._anchor(dec, tpl, text, spans, query, depth, type_hint, exact), text

    def _anchor(self, dec: Decider, tpl: Template, text: str, spans: list[Span], query: str, depth: int,
                type_hint: str | None, exact) -> dict[str, Any]:
        # Spans inside this slot text.
        inside = [s for s in spans if s.label not in ("distance", "facility type") and s.text in text]
        allow_geocoder = depth == 0 and tpl.family in GEOCODER_FAMILIES
        ctx_text = None
        name = text
        if allow_geocoder:
            cands = exact or self.store.search(text, type_hint=type_hint, limit=3)
            top = cands[0] if cands else None
            sd = dec.select_source(text, {"gazetteer_match": top.description if top else None,
                                          "gazetteer_top_score": top.score if top else 0.0}, depth=depth)
            if dec.below("select_source", sd):
                raise _Stop(Unsupported(reason=f"low confidence for select_source ({sd.confidence:.2f})",
                                        decision="select_source", depth=depth, text=text))
            if sd.value == "photon":
                return {"op": "Resolve", "args": {"name": text, "source": "photon"}}
        # If the whole text is an exact name in the gazetteer, it is the anchor. Else choose among the spans.
        if not exact and (len(inside) > 1 or (len(inside) == 1 and inside[0].text != text)):
            b = dec.bind_anchor(query, text, inside, depth=depth)
            if b.value.label != "whole":
                name = b.value.text
                rest = text.replace(name, " ").strip(" ,")
                ctx_text = rest or None
        cands = self.store.search(name, type_hint=type_hint, context=ctx_text, limit=6)
        if not cands:
            raise _Stop(Unsupported(reason=f"cannot resolve {name!r} in the local extract", depth=depth, text=text))
        cands = merge_nested(cands)
        chosen = cands[0]
        if len(cands) > 1 and cands[0].score - cands[1].score < 0.15:
            close = [c for c in cands if cands[0].score - c.score < 0.3]
            d = dec.disambiguate(name, close, query=query, depth=depth)
            if dec.below("disambiguate", d):
                raise _Stop(Unsupported(reason=f"low confidence for disambiguate ({d.confidence:.2f})",
                                        decision="disambiguate", depth=depth, text=text))
            chosen = d.value
        args = {"name": name, "source": "overture", "id": chosen.id}
        if type_hint:
            args["type_hint"] = type_hint
        if ctx_text:
            args["context"] = ctx_text
        return {"op": "Resolve", "args": args}


def merge_nested(cands: list) -> list:
    """Merge candidates with the same name where one contains the other (a city and its district, a
    locality and its macrohood). The choice between them is a policy (subtype prior), not a decision."""
    out = []
    for c in cands:
        same = [o for o in out if norm(o.name) == norm(c.name) and (o.id in c.ancestors or c.id in o.ancestors)]
        if not same:
            out.append(c)
    return out


def _plain_anchors(dag: dict[str, Any]) -> bool:
    """True if the DAG has exactly one Resolve and no set operators (simple path)."""
    n = 0

    def walk(node):
        nonlocal n
        if isinstance(node, dict) and "op" in node:
            if node["op"] == "Resolve":
                n += 1
            for v in node.get("args", {}).values():
                walk(v)

    walk(dag)
    return n == 1
