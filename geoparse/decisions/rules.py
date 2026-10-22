"""Rule implementations for RulesProvider ("rules-v1").

Each rule reads the structured inputs in Question.context that the decision functions put there.
These rules are a baseline for tests and offline use. They are not tuned.
"""
from __future__ import annotations

from typing import Any

from geoparse.decisions.types import Decision, Question
from geoparse.options import best_keyword_option, keyword_hits, option_keywords, options

IMPL = "rules-v1"


def _dec(value: Any, conf: float, **trace) -> Decision:
    return Decision(value=value, confidence=conf, impl=IMPL, trace=trace)


def _best(scores: dict[str, float]) -> tuple[str, float]:
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top = ranked[0]
    margin = top[1] - ranked[1][1] if len(ranked) > 1 else 1.0
    return top[0], max(0.0, min(1.0, 0.5 + margin / 2))


def pick_family(text, q: Question, options_: dict[str, str]) -> Decision[str]:
    scores = {f: max((s for t, s in q.context["template_scores"].items() if q.context["template_family"][t] == f), default=-1)
              for f in options_}
    v, c = _best(scores)
    return _dec(v, c, scores=scores)


def pick_template(text, q: Question, options_: dict[str, str]) -> Decision[str]:
    scores = {t: q.context["template_scores"].get(t, -1) for t in options_}
    v, c = _best(scores)
    return _dec(v, c, scores=scores)


def pick_split(text, q: Question, options_: dict[str, str]) -> Decision[str]:
    scores = {k: q.context["split_scores"][k] for k in options_}
    v, c = _best(scores)
    return _dec(v, c, scores=scores)


def fill_closed_slot(text, q: Question, options_: dict[str, str]) -> Decision[str]:
    ref = q.context["options_ref"]
    seg = q.context["segment"]
    if ref == "categories" and q.context.get("step") == "group":
        from geoparse.options import categories

        scores = {g: max((keyword_hits(seg, item["keywords"]) for item in categories()[g]["items"].values()), default=0)
                  for g in options_ if g != "none"}
        if "none" in options_:
            scores["none"] = 0
    elif ref == "categories":
        kws = option_keywords("categories")
        scores = {k: keyword_hits(seg, kws.get(k, [])) for k in options_}
    else:
        kws = option_keywords(ref)
        scores = {k: keyword_hits(seg, kws.get(k, [])) for k in options_}
        # Prefer the longer keyword match (for example "north-east" over "north").
        scores = {k: v + 0.01 * max((len(w) for w in kws.get(k, []) if keyword_hits(seg, [w])), default=0) if v else 0
                  for k, v in scores.items()}
    if max(scores.values(), default=0) <= 0:
        if "none" in options_:
            return _dec("none", 0.9, scores=scores)
        return _dec(next(iter(options_)), 0.0, scores=scores)
    v, c = _best(scores)
    return _dec(v, max(c, 0.6), scores=scores)


def bind_anchor(text, q: Question, options_: dict[str, str]) -> Decision[str]:
    spans = q.context["spans"]
    if any(s["label"] in ("street", "landmark") for s in spans) or len(spans) != 1:
        return _dec("whole", 0.8)
    return _dec("s0", 0.8)


def is_subquery(text, q: Question) -> Decision[bool]:
    t = q.context["text"]
    if q.context.get("gazetteer_exact"):
        return _dec(False, 0.9)
    hits = sum(keyword_hits(t, sum(option_keywords(ref).values(), [])) for ref in ("admin_levels", "predicates"))
    if q.context.get("has_distance") or hits:
        return _dec(True, 0.8)
    connectors = ["except", "excluding", "between", "around", "near", "within", "border", "bordering", "and"]
    if keyword_hits(t, connectors):
        return _dec(True, 0.6)
    return _dec(False, 0.7)


STREET_WORDS = ["road", "rd", "street", "st", "marg", "lane", "highway", "station", "metro", "airport", "temple",
                "fort", "palace", "gate", "gateway", "bridge", "mall", "hospital", "college", "university", "park",
                "circle", "chowk", "junction", "stadium", "beach", "lake", "tower", "minar", "charminar", "majestic"]


def select_source(text, q: Question, options_: dict[str, str]) -> Decision[str]:
    t = q.context["text"]
    if keyword_hits(t, STREET_WORDS):
        return _dec("photon", 0.8)
    if q.context.get("gazetteer_top_score", 0) >= 1.0:
        return _dec("overture", 0.8)
    return _dec("photon", 0.6)


def disambiguate(text, q: Question, options_: dict[str, str]) -> Decision[str]:
    scores = q.context["scores"]
    v, c = _best({k: scores[k] for k in options_})
    return _dec(v, c, scores=scores)


DEFAULT_RULES = {
    "pick_family": pick_family,
    "pick_template": pick_template,
    "pick_template_flat": pick_template,
    "pick_split": pick_split,
    "fill_closed_slot": fill_closed_slot,
    "bind_anchor": bind_anchor,
    "is_subquery": is_subquery,
    "select_source": select_source,
    "disambiguate": disambiguate,
}


def template_score(literals: int, closed_segments: dict[str, list[str]], segments: dict[str, str]) -> float:
    """Specificity of one pattern match: literal words matched, plus keyword purity of closed segments."""
    score = float(literals)
    for seg_name, slots in closed_segments.items():
        seg = segments[seg_name]
        words = len(seg.split())
        refs = [r for r in slots if r]
        hits = max((keyword_hits(seg, sum(option_keywords(r).values(), [])) for r in refs), default=0)
        if len(refs) > 1:
            hits = keyword_hits(seg, sum((sum(option_keywords(r).values(), []) for r in refs), []))
        score += 2.0 * hits / max(words, 1) - (words - hits) * 1.0
    return score


__all__ = ["DEFAULT_RULES", "template_score", "options", "best_keyword_option"]
