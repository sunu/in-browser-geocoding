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
from geoparse.decisions.providers import ProviderError
from geoparse.decisions.rules import template_score
from geoparse.decisions.types import Span, Split
from geoparse.dsl.schema import PREDICATE_DAGS, substitute, validate
from geoparse.options import (choices, keyword_hits, lexicon, option_keywords, parse_distance, parse_value,
                              norm)
from geoparse.templates.model import CLOSED_TYPES, OPEN_TYPES, Template, load_families, match_pattern

SIMPLE_FAMILIES = {"lookup", "modifier"}
# Families whose anchors can go to the geocoder. "features" is here because plan-002 routes POIs to Photon.
GEOCODER_FAMILIES = {"lookup", "modifier", "features"}
# Templates whose optional parent (first name) without text is the countries around another slot (second name).
AROUND_DEFAULT = {"children_touching": ("parent", "other"), "children_near": ("parent", "other")}
# A number with a distance unit in a text ("10 km around Whitefield"; not "Sector 5").
HAS_DISTANCE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:km|kms|kilometres?|kilometers?|m|metres?|meters?|mi|miles?)\b", re.I)
# Templates where the admin level can be empty (an unknown level word). The executor uses the data.
STRUCTURE_LEVEL = {"children", "children_with_predicate"}

LEADING_FILLERS = [
    "show me the", "show me", "show the", "show", "find me", "find the", "find", "list the", "list all", "list",
    "give me the", "give me", "get me", "get", "map of the", "map of", "map", "where is the", "where is",
    "where are the", "where are", "what are the", "what are", "which are the", "all the", "all of the", "the",
    "everything", "anything",
]


# Structural limits for split candidates. These are not vocabulary lists of slot values.
MAX_CLOSED_WORDS = 6
CLAUSE_WORDS = {"of", "in", "that", "which", "and", "or", "except", "between", "who"}
STOP_WORDS = {"the", "a", "an", "all", "any", "some", "of", "in", "and", "that", "which", "with", "me", "show"}


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
                 two_step: bool = True, prune_by_pattern: bool = True, max_workers: int = 32,
                 use_t5: bool | None = None, use_patterns: str | None = None, t5_dir: str | None = None,
                 geocoder=None):
        self.base_decider = decider or Decider()
        self.cfg = config or load_config()
        self.max_depth = int(self.cfg["decisions"]["max_depth"])
        self.two_step = two_step
        self.prune = prune_by_pattern
        self.families = load_families()
        self.templates = {t.id: t for f in self.families.values() for t in f.templates}
        self._store = store
        # Geocoder for the Photon boost of close candidates (plan-012 section 3.2). None: no boost.
        self.geocoder = geocoder
        self.pool = ThreadPoolExecutor(max_workers=max_workers)
        self.t5_cfg = self.cfg.get("t5", {})
        self.use_patterns = str(self.t5_cfg.get("use_patterns", "fallback")) if use_patterns is None else use_patterns
        self.t5 = None
        if (self.t5_cfg.get("enabled") if use_t5 is None else use_t5):
            try:
                from geoparse.t5.model import get_t5

                self.t5 = get_t5(t5_dir)
            except (FileNotFoundError, ImportError):
                self.t5 = None
        if self.t5 is None:
            self.use_patterns = "always"

    @property
    def store(self):
        if self._store is None:
            from geoparse.execute.data import get_store

            self._store = get_store()
        return self._store

    # ------------------------------------------------------------ public

    def parse(self, query: str, view: list[float] | None = None) -> ParseResult:
        """view: map view (xmin, ymin, xmax, ymax) for the ranking of candidates. None: data.bbox."""
        dec = self.base_decider.fork()
        dec.view = list(view) if view else None
        dec.view_country = self.store.view(dec.view, self.cfg)[1]
        dec.data_level_words = self.store.level_words(dec.view_country)
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
        except ProviderError as e:
            # A provider failure (network, quota) is not a parse decision. Report it; do not guess.
            res.unsupported = Unsupported(reason=f"decision provider error: {e}")
        res.trace = dec.trace
        res.timings["parse_s"] = round(time.time() - t0, 3)
        return res

    # ------------------------------------------------------------ one level

    def candidates(self, text: str, spans: list[Span] | None = None, dec: Decider | None = None,
                   depth: int = 0) -> dict[str, list[dict[str, Any]]]:
        """Template id -> list of valid split matches. `spans` (from extract_spans) mark place names."""
        places = tuple(norm(s.text) for s in (spans or [])
                       if s.label in ("location", "landmark", "street") and s.score >= 0.5 and norm(s.text))
        out: dict[str, list[dict[str, Any]]] = {}
        t5_matches, t5_unsupported = self._t5_matches(text, dec, depth)
        if t5_unsupported:
            return {"_t5_unsupported": []}
        for m in t5_matches:
            out.setdefault(m["template"], []).append(m)
        # Patterns: "always", "fallback" (only if T5 gives no usable frame), or "never".
        patterns_on = self.use_patterns == "always" or (self.use_patterns == "fallback" and not t5_matches)
        for t in self.templates.values():
            if not patterns_on:
                break
            seen = set()
            literal = [m for pat in t.patterns for m in match_pattern(pat, text)]
            for m in literal:
                m["_places"] = places
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
                                   if n in seg_of and sd.type in OPEN_TYPES))
                # A T5 frame wins over a pattern match with the same open spans (its spans are more precise).
                if key not in best or (m.get("source") == "t5") > (best[key].get("source") == "t5") or (
                        (m.get("source") == "t5") == (best[key].get("source") == "t5") and m["score"] > best[key]["score"]):
                    best[key] = m
            out[tid] = list(best.values())
        return out

    def _t5_matches(self, text: str, dec: Decider | None = None, depth: int = 0) -> list[dict[str, Any]]:
        """Candidate splits from the T5 model, as split matches. Empty if T5 is not enabled or not built."""
        if self.t5 is None:
            return [], False
        from geoparse.t5.frames import UNSUPPORTED, frame_to_match, group_frames

        frames, dt = self.t5.frames(text, k=int(self.t5_cfg.get("beams", 4)))
        groups = group_frames(frames, text, self.templates, float(self.t5_cfg.get("margin", 2.0)))
        if dec is not None:
            import math

            from geoparse.decisions.types import Decision

            d = Decision[list](value=[f.to_text() for f in groups], impl=f"t5:{self.t5.dir.name}",
                               confidence=math.exp(frames[0].score) if frames else 0.0,
                               trace={"beam": [(f.to_text(), round(f.score, 4)) for f in frames]})
            dec._record("generate_frames", depth, {"text": text}, None, d, dt)
        import math

        unsupported = bool(frames) and frames[0].template == UNSUPPORTED and \
            math.exp(frames[0].score) >= float(self.t5_cfg.get("unsupported_p", 0.5))
        out = []
        for f in groups:
            m = frame_to_match(f, text)
            m["template"] = f.template
            # Rule score: T5 frames rank above pattern matches, in beam order.
            m["score"] = 20.0 + f.score
            out.append(m)
        return out, unsupported

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
                if all(x in STOP_WORDS for x in w):
                    return False
            closed = [t.slots[s] for s in fed if s in t.slots and t.slots[s].type in CLOSED_TYPES]
            if closed:
                # Structural check only. The decision model judges the meaning of the words.
                # A closed-slot segment is a short phrase, not a clause with its own place or relation.
                w = norm(text).split()
                if w and w[0] in ("which", "what"):
                    w = w[1:]
                if len(w) > MAX_CLOSED_WORDS or any(x in CLAUSE_WORDS for x in w):
                    return False
                # A closed-slot segment must not contain a place name found by the NER model.
                if any(p in norm(text) for p in m.get("_places", ())):
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
        qual = self._qualified(dec, text, depth)
        if qual:
            return qual, {"family": "lookup", "template": "lookup_place", "slots": {"anchor": qual["args"]["name"]}}
        spans = dec.extract_spans(text, depth=depth).value
        cands = self.candidates(text, spans, dec, depth)
        if "_t5_unsupported" in cands:
            raise _Stop(Unsupported(reason="the T5 model classifies the text as unsupported",
                                    decision="generate_frames", depth=depth, text=text))
        if not self.prune:
            cands = {tid: cands.get(tid, []) for tid in self.templates}
        if not any(cands.values()):
            raise _Stop(Unsupported(reason="no template pattern matches the text", depth=depth, text=text))
        tscores = {tid: max((m["score"] for m in ms), default=-9) for tid, ms in cands.items()}
        tfam = {tid: self.templates[tid].family for tid in cands}
        ctx = {"template_scores": tscores, "template_family": tfam}

        if self.two_step:
            # Options in rank order (best candidate score first). The local model reads the rank.
            fam_score = {}
            for t in cands:
                fam_score[tfam[t]] = max(fam_score.get(tfam[t], -1e9), tscores.get(t, -1e9))
            fams = {f: self.families[f].description for f in sorted(fam_score, key=lambda f: -fam_score[f])}
            fd = dec.pick_family(text, spans, fams, depth=depth, context=ctx)
            if dec.below("pick_family", fd):
                raise _Stop(Unsupported(reason=f"low confidence for pick_family ({fd.confidence:.2f})", decision="pick_family", depth=depth, text=text))
            family = fd.value
            topts = {tid: self._template_option(tid)
                     for tid in sorted(cands, key=lambda t: -tscores.get(t, -1e9)) if tfam[tid] == family}
            td = dec.pick_template(text, spans, family, topts, depth=depth, context=ctx)
        else:
            topts = {tid: self._template_option(tid) for tid in sorted(cands, key=lambda t: -tscores.get(t, -1e9))}
            td = dec.pick_template_flat(text, spans, topts, depth=depth, context=ctx)
        if dec.below("pick_template", td):
            raise _Stop(Unsupported(reason=f"low confidence for pick_template ({td.confidence:.2f})", decision="pick_template", depth=depth, text=text))
        tpl = self.templates[td.value]
        alt = self._frame_override(dec, text, tpl.id, cands, tscores, depth)
        if alt:
            tpl = self.templates[alt]
        if tpl.id == "natural_in":
            # "Ganga river", "Sahara desert": one natural feature, not the features of a kind in a place.
            top = self.store.search(text, fuzzy=False, limit=1, view=dec.view)
            if top and top[0].subtype == "natural":
                dec.record_step("natural_name", depth, {"text": text}, top[0].id, "rules", {})
                return ({"op": "Resolve", "args": {"name": text, "source": "overture", "id": top[0].id}},
                        {"family": "lookup", "template": "lookup_place", "slots": {"anchor": text}})
        if tpl.family == "lookup" and alt != "lookup_place":
            # Guard (not after the exact-name rule of _frame_override): the lookup template takes the whole text as one name. If the text describes a set
            # of places (and no other template matched), it is not supported. Do not geocode it.
            g = dec.is_subquery(text, depth=depth, context={"gazetteer_exact": bool(self.store.search(text, fuzzy=False, limit=1, view=dec.view)),
                                                             "has_distance": bool(re.search(r"\d", text))})
            if g.value or dec.below("is_subquery", g):
                raise _Stop(Unsupported(reason="the text is not one place name, and no other template matches",
                                        decision="is_subquery", depth=depth, text=text))
        matches = sorted(cands.get(tpl.id, []), key=lambda m: -m["score"])
        if not matches:
            raise _Stop(Unsupported(reason=f"template {tpl.id} has no valid split", decision="pick_split", depth=depth, text=text))

        fills: dict[tuple, Any] = {}
        if len(matches) > 1:
            matches = self._viable_splits(dec, tpl, matches, text, depth, fills)
            if not matches:
                raise _Stop(Unsupported(reason=f"no split of the text gives valid values for the slots of {tpl.id}",
                                        decision="fill_closed_slot", depth=depth, text=text))
        splits = [Split(parts=m["segments"]) for m in matches]
        sd = dec.pick_split(text, tpl.description, splits, depth=depth, labels=self._labels(tpl, matches[0]),
                            context={"split_scores": {f"s{i}": m["score"] for i, m in enumerate(matches)}})
        if dec.below("pick_split", sd):
            raise _Stop(Unsupported(reason=f"low confidence for pick_split ({sd.confidence:.2f})", decision="pick_split", depth=depth, text=text))
        match = next(m for m in matches if m["segments"] == sd.value.parts)

        values, slots = self._fill(dec, tpl, match, text, spans, depth, fills)
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

    def _closed_jobs(self, dec: Decider, tpl: Template, match: dict[str, Any], text: str, depth: int,
                     fills: dict[tuple, Any]) -> dict[str, Any]:
        """Submit (or reuse) the closed-slot decisions of one split. Returns slot name -> future."""
        seg_of = {s: seg for seg, fed in match["feeds"].items() for s in fed}
        jobs = {}
        for name, sd in tpl.slots.items():
            if sd.type not in CLOSED_TYPES or name not in seg_of:
                continue
            seg_text = match["segments"][seg_of[name]]
            key = (seg_text, sd.type, sd.options_ref)
            if key not in fills:
                fills[key] = self.pool.submit(dec.fill_closed_slot, seg_text, sd.type, sd.options_ref, depth=depth,
                                              query=text, allow_none=True)
            jobs[name] = fills[key]
        return jobs

    def _viable_splits(self, dec: Decider, tpl: Template, matches: list[dict[str, Any]], text: str, depth: int,
                       fills: dict[tuple, Any]) -> list[dict[str, Any]]:
        """Keep the splits where the model finds a value for every required closed slot.

        The closed-slot decisions of all candidate splits run in parallel. A split is not viable if a
        required slot gets "none" or a confidence below the threshold. The results are cached in `fills`.
        """
        per_match = [self._closed_jobs(dec, tpl, m, text, depth, fills) for m in matches]
        viable = []
        for m, jobs in zip(matches, per_match):
            ok = True
            for name, fut in jobs.items():
                r = fut.result()
                if dec.below("fill_closed_slot", r) or (r.value == "none" and not _level_free(tpl, name)):
                    ok = False
                    break
            if ok:
                viable.append(m)
        return viable

    def _fill(self, dec: Decider, tpl: Template, match: dict[str, Any], text: str, spans: list[Span],
              depth: int, fills: dict[tuple, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
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
        jobs.update(self._closed_jobs(dec, tpl, match, text, depth, fills if fills is not None else {}))

        # The admin level of the query is a type hint for the anchors of some templates.
        if "level" in jobs:
            lv = jobs["level"].result()
            level_hint = lv.value if lv.value != "none" else None
        around = None
        for name, sd in tpl.slots.items():
            if sd.type in OPEN_TYPES and name not in seg_of:
                if tpl.id in AROUND_DEFAULT and name == AROUND_DEFAULT[tpl.id][0]:
                    around = name
                    continue
                # Optional open slot without text: the default is the country of the map view.
                values[name], slots[name] = self._default_region(sd, dec), None
                continue
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
            if r.value == "none" and not _level_free(tpl, name):
                raise _Stop(Unsupported(reason=f"the text {match['segments'][seg_of[name]]!r} names no known {sd.type}",
                                        decision="fill_closed_slot", depth=depth, text=text))
            slots[name] = r.value
            if r.value == "none":
                values[name] = None if sd.type == "admin_level" else sd.default
                slots[name] = sd.default
                continue
            if sd.type == "predicate":
                values[name] = PREDICATE_DAGS[r.value]
            elif sd.type == "admin_level" and r.value == "none":
                values[name] = None
            else:
                values[name] = r.value
        if around:
            values[around], slots[around] = self._around(dec, tpl.slots[around], values.get(AROUND_DEFAULT[tpl.id][1])), None
        if tpl.id in STRUCTURE_LEVEL and values.get("level") is None and "level" in seg_of:
            # The level from the data only below a country that the text names: an unknown word below a state is
            # a level that the data does not have ("talukas of Maharashtra"), and "talukas" alone is not "states".
            pid = (values.get("parent") or {}).get("args", {}).get("id")
            if "parent" not in seg_of or not pid or self.store.describe([pid]).get(pid, {}).get("subtype") not in ("country", "dependency"):
                raise _Stop(Unsupported(reason=f"the text {match['segments'][seg_of['level']]!r} names no known admin_level",
                                        decision="fill_closed_slot", depth=depth, text=text))
        return values, slots

    def _around(self, dec: Decider, sd, other: Any) -> dict[str, Any]:
        """Default parent of "districts along the Yamuna": the countries whose extent overlaps the extent of the
        other place (the Touches filter then keeps the exact ones). The country of the map view if the other place
        is not one resolved place."""
        oid = other.get("args", {}).get("id") if isinstance(other, dict) and other.get("op") == "Resolve" else None
        codes = self.store.countries_around(oid) if oid else []
        if not codes:
            return self._default_region(sd, dec)
        rows = self.store.cursor().execute(
            "SELECT country, id, name FROM divisions WHERE subtype = 'country' AND country IN (SELECT unnest(?)) ORDER BY country",
            [codes]).fetchall()
        node = None
        for _, id_, name in rows:
            r = {"op": "Resolve", "args": {"name": name, "source": "overture", "id": id_}}
            node = r if node is None else {"op": "Union", "args": {"a": node, "b": r}}
        return node or self._default_region(sd, dec)

    def _default_region(self, sd, dec: Decider) -> dict[str, Any]:
        if sd.default != "country":
            raise _Stop(Unsupported(reason=f"no default for open slot ({sd.default!r})"))
        code = dec.view_country or self.cfg["data"]["country"]
        row = self.store.cursor().execute(
            "SELECT id, name FROM divisions WHERE subtype = 'country' AND country = ?", [code]).fetchone()
        if not row:
            raise _Stop(Unsupported(reason=f"country {code} is not in the extract"))
        return {"op": "Resolve", "args": {"name": row[1], "source": "overture", "id": row[0]}}

    def _frame_override(self, dec: Decider, text: str, tid: str, cands: dict[str, list], tscores: dict[str, float],
                        depth: int) -> str | None:
        """Another candidate template of the T5 frames, if the chosen one does not fit the text:
        1. "A and B" is one place only if it is an exact name ("Trinidad and Tobago"): else the union, if A and B are.
        2. Each admin level word of the text is in a slot of the frame ("coastal regions of Chile" is not along_coast).
           Not for a lookup: a level word after a place name is usually noise ("Konark Sun Temple state").
        3. A direction word and an exact name is one side of the place, if the whole text is not an exact name
           ("Northern India"; T5 reads a capital letter as part of a name). "North Carolina" stays a lookup.
        4. The other way: one side of a place is a lookup if the whole text is an exact name ("Western Ghats")."""
        def covers(t):
            best = max(cands.get(t, []), key=lambda m: m["score"], default=None)
            segs = " ".join(str(v) for v in (best["segments"].values() if best else [])).lower()
            return all(w in segs for w in level_words)

        m = re.fullmatch(r"(.+?)\s+(?:and|&)\s+(.+)", text.strip(), re.I)
        if (tid == "lookup_place" and m and "union" in cands and not self.store.search(text, fuzzy=False, limit=1, view=dec.view)
                and all(self.store.search(x, fuzzy=False, limit=1, view=dec.view) for x in m.groups())):
            dec.record_step("frame_override", depth, {"text": text}, "union", "rules", {"from": tid})
            return "union"
        rest = _direction_rest(text) if tid == "lookup_place" and "direction_part" in cands else None
        if (rest and not self.store.search(text, fuzzy=False, limit=1, view=dec.view)
                and self.store.search(rest, fuzzy=False, limit=1, view=dec.view)):
            dec.record_step("frame_override", depth, {"text": text}, "direction_part", "rules", {"from": tid, "direction_rest": rest})
            return "direction_part"
        name = re.sub(r"^the\s+", "", text.strip(), flags=re.I)
        if (tid == "direction_part" and "lookup_place" in cands and _direction_rest(name)
                and self.store.search(name, fuzzy=False, limit=1, view=dec.view)):
            dec.record_step("frame_override", depth, {"text": text}, "lookup_place", "rules", {"from": tid, "exact_name": name})
            return "lookup_place"
        level_words = [w for w in _level_words() if re.search(rf"\b{re.escape(w)}\b", text, re.I)]
        if tid != "lookup_place" and level_words and cands.get(tid) and not covers(tid):
            alts = sorted((t for t in cands if t != tid and covers(t)), key=lambda t: -tscores.get(t, -1e9))
            if alts:
                dec.record_step("frame_override", depth, {"text": text}, alts[0], "rules", {"from": tid, "level_words": level_words})
                return alts[0]
        return None

    def _region(self, dec: Decider, tpl: Template, text: str, spans: list[Span], query: str, depth: int,
                type_hint: str | None) -> tuple[dict[str, Any], Any]:
        article = bool(re.match(r"^the\s", text.strip(), re.I))
        text = re.sub(r"^(the|a|an|whole|entire|all of|all of the|whole of)\s+", "", text.strip(), flags=re.I)
        if article:
            # "the Godavari": rivers, ranges and seas take "the", districts and cities do not. An exact natural
            # feature is the place.
            nat = [c for c in self.store.search(text, fuzzy=False, limit=5, view=dec.view) if c.subtype == "natural"]
            if nat:
                dec.record_step("natural_name", depth, {"text": text}, nat[0].id, "rules", {"article": True})
                return {"op": "Resolve", "args": {"name": text, "source": "overture", "id": nat[0].id}}, text
        lex = lexicon_match(text)
        if lex:
            return {"op": "LexiconSet", "args": {"key": lex}}, {"lex": lex, "text": text}
        qual = self._qualified(dec, text, depth)
        if qual:
            return qual, text
        sd = tpl.slots
        is_region = any(s.type == "region" for s in sd.values()) and tpl.family != "lookup"
        exact = self.store.search(text, type_hint=type_hint, fuzzy=False, limit=3, view=dec.view)
        rest = _direction_rest(text) if is_region and not exact else None
        if rest and self.store.search(rest, fuzzy=False, limit=1, view=dec.view):
            # "northern France": a direction word and a place name. A subquery, without the model.
            dec.record_step("is_subquery", depth, {"text": text}, True, "rules", {"direction_rest": rest})
            if depth + 1 > self.max_depth:
                raise _Stop(Unsupported(reason="depth limit", depth=depth, text=text))
            sub_dag, info = self._parse_level(dec, text, depth + 1)
            return sub_dag, {"q": text, "t": info["template"], "s": info["slots"]}
        if is_region and not exact and (keyword_hits(text, _level_words(), typo=False) or HAS_DISTANCE.search(text)):
            # "coastal districts of Odisha", "10 km around Whitefield": a set by a level or a distance, not a place
            # name. A sub-query, without the model.
            dec.record_step("is_subquery", depth, {"text": text}, True, "rules", {"level_or_distance": True})
            if depth + 1 > self.max_depth:
                raise _Stop(Unsupported(reason="depth limit", depth=depth, text=text))
            sub_dag, info = self._parse_level(dec, text, depth + 1)
            return sub_dag, {"q": text, "t": info["template"], "s": info["slots"]}
        if is_region and exact and not keyword_hits(text, _level_words(), typo=False):
            # The whole text is an exact place name ("Western Ghats", "Northern Ireland", "Central Delhi"): a place, not
            # a sub-query, also with a direction word.
            dec.record_step("is_subquery", depth, {"text": text}, False, "rules", {"exact_name": True})
            return self._anchor(dec, tpl, text, spans, query, depth, type_hint, exact), text
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
        scope = self.cfg.get("geocoder", {}).get("anchor_scope", "simple_and_features")
        allow_geocoder = scope == "all" or (depth == 0 and tpl.family in GEOCODER_FAMILIES)
        ctx_text = None
        name = text
        if allow_geocoder:
            cands = exact or self.store.search(text, type_hint=type_hint, limit=3, view=dec.view)
            top = cands[0] if cands else None
            sd = dec.select_source(text, {"gazetteer_match": top.description if top else None,
                                          "gazetteer_top_score": top.score if top else 0.0,
                                          "gazetteer_top_subtype": top.subtype if top else None}, depth=depth)
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
        cands = self.store.search(name, type_hint=type_hint, context=ctx_text, limit=6, view=dec.view)
        if not cands:
            raise _Stop(Unsupported(reason=f"cannot resolve {name!r} in the local extract", depth=depth, text=text))
        cands = self._photon_boost(dec, name, merge_nested(cands), depth)
        chosen = cands[0]
        if len(cands) > 1 and cands[0].score - cands[1].score < self.cfg["policy"]["ranking"]["close_margin"]:
            close = [c for c in cands if cands[0].score - c.score < float(self.cfg["policy"]["ranking"]["candidate_window"])]
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

    def _qualified(self, dec: Decider, text: str, depth: int) -> dict[str, Any] | None:
        """A place name with the names of places that contain it, after commas ("Paris, Texas", "San Francisco,
        California, USA"). The Resolve of the best candidate of the first name that is inside one exact match of
        each later name; None if there is no such candidate ("Kerala, Tamil Nadu" is a union)."""
        parts = [p.strip() for p in text.split(",")]
        exact_only = False
        if len(parts) == 1:
            # "Springfield in Illinois": exact names only, and not a set ("districts in Kerala", "hospitals in Pune").
            m = re.fullmatch(r"(.+?)\s+in\s+(.+)", text.strip(), re.I)
            if not m or keyword_hits(m.group(1), _set_words(), typo=False):
                return None
            parts, exact_only = [m.group(1), m.group(2)], True
        if not 2 <= len(parts) <= 3 or not all(parts) or any(re.search(r"\band\b|&", p, re.I) for p in parts):
            return None
        outer = []
        for p in parts[1:]:
            ids = {c.id for c in self.store.search(p, fuzzy=False, limit=5, view=dec.view)}
            if not ids:
                return None
            outer.append(ids)
        # A candidate inside the outer places is in their countries: search only there (the browser then loads only
        # these countries, not the countries of all places named "Paris").
        countries = sorted({d["country"] for d in self.store.describe(sorted(set().union(*outer))).values() if d["country"]})
        context = ", ".join(parts[1:])
        # Exact names first; fuzzy names only if no exact name is inside ("Sanfransisco, California").
        for fuzzy in ((False,) if exact_only else (True, "only")):
            for c in self.store.search(parts[0], context=context, limit=20, fuzzy=fuzzy, view=dec.view, countries=countries):
                if all(ids & set(c.ancestors) for ids in outer):
                    dec.record_step("qualified_name", depth, {"text": text}, c.id, "rules",
                                    {"name": parts[0], "context": context, "fuzzy": fuzzy})
                    return {"op": "Resolve", "args": {"name": parts[0], "source": "overture", "id": c.id, "context": context}}
        return None

    def _photon_boost(self, dec: Decider, name: str, cands: list, depth: int) -> list:
        """If the two best candidates are close, add a score to the candidates that match Photon results."""
        rk = self.cfg["policy"]["ranking"]
        if self.geocoder is None or len(cands) < 2 or cands[0].score - cands[1].score >= rk["close_margin"]:
            return cands
        kw: dict[str, Any] = {"limit": int(rk["photon_limit"])}
        if dec.view:
            kw["location"] = ((dec.view[0] + dec.view[2]) / 2, (dec.view[1] + dec.view[3]) / 2)
        try:
            feats = self.geocoder.search(name, **kw)
        except Exception as e:  # noqa: BLE001 - the boost is optional; continue without it
            dec.record_step("photon_boost", depth, {"name": name}, None, "rules", {"error": str(e)[:200]})
            return cands
        ranks = self.store.match_points([c.id for c in cands], [(f.lon, f.lat) for f in feats])
        boosts = {i: rk["photon_boost"][r - 1] for i, r in ranks.items() if r <= len(rk["photon_boost"])}
        dec.record_step("photon_boost", depth, {"name": name}, boosts, "rules",
                        {"photon": [f.label for f in feats], "ranks": ranks})
        if not boosts:
            return cands
        out = [c.model_copy(update={"score": round(c.score + boosts.get(c.id, 0.0), 4)}) for c in cands]
        out.sort(key=lambda c: (-c.score, c.id))
        return out


def _level_words() -> list[str]:
    """The keywords of the admin levels ("districts", "states")."""
    return [k for ks in option_keywords("admin_levels").values() for k in ks]


def _set_words() -> list[str]:
    """Words of a set or a part, not of a place name: admin levels, categories, predicates, directions, natural kinds."""
    refs = ("admin_levels", "categories", "predicates", "directions", "natural_kinds")
    return [k for ref in refs for ks in option_keywords(ref).values() for k in ks]


def _direction_rest(text: str) -> str | None:
    """The text after a leading direction word of 4 or more letters ("northern France" -> "France")."""
    kws = sorted((k for ks in option_keywords("directions").values() for k in ks if len(k) >= 4), key=len, reverse=True)
    for k in kws:
        m = re.match(rf"{re.escape(k)}\s+(.+)$", text.strip(), re.I)
        if m:
            return m.group(1)
    return None


def _level_free(tpl: Template, name: str) -> bool:
    """A slot that can be empty. In these templates the executor finds the admin level from the data
    ("voivodeships of Poland": the level of the divisions below Poland)."""
    sd = tpl.slots[name]
    return sd.optional or (sd.type == "admin_level" and tpl.id in STRUCTURE_LEVEL)


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
