"""extract_spans: GLiNER for place names, regex for distances and numbers, then rule trimming.

This is not a System One decision. It sits behind the same Decision type so that the trace and the
logs have one format.
"""
from __future__ import annotations

import re
import time

from geoparse.decisions.types import Decision, Span
from geoparse.options import DISTANCE_SEARCH, _num, _UNITS, option_keywords, options

GLINER_LABELS = ["location", "landmark", "street", "facility type"]
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)*\s*(?:lakh|lakhs|lac|crore|crores|million|thousand|k|mn|cr)?\b", re.I)


def _trim_words() -> set[str]:
    words = set(options()["stopwords"])
    for ref in ("admin_levels", "predicates", "directions"):
        for kws in option_keywords(ref).values():
            words.update(k for k in kws if " " not in k and len(k) > 1)
    return words


def trim_span(text: str, start: int, end: int, trim: set[str]) -> tuple[int, int]:
    """Remove level, predicate, direction, and stop words from the edges of a span."""
    seg = text[start:end]
    words = [(m.start() + start, m.end() + start, m.group().lower()) for m in re.finditer(r"[\w'-]+", seg)]
    while words and words[0][2] in trim:
        words.pop(0)
    while words and words[-1][2] in trim:
        words.pop()
    if not words:
        return start, start
    return words[0][0], words[-1][1]


def extract_spans(query: str, use_model: bool = True, threshold: float = 0.3) -> Decision[list[Span]]:
    t0 = time.time()
    spans: list[Span] = []
    impl = "regex"
    for m in DISTANCE_SEARCH.finditer(query):
        spans.append(Span(text=m.group(), start=m.start(), end=m.end(), label="distance",
                          value=_num(m.group(1)) * _UNITS[m.group(2).lower()]))
    if use_model:
        try:
            from geoparse.parse.gliner_onnx import get_model

            raw = get_model().predict(query, GLINER_LABELS, threshold=threshold)
            impl = "gliner-small-v2.1-int8+regex"
            trim = _trim_words()
            for r in raw:
                if any(not (r.end <= s.start or r.start >= s.end) for s in spans if s.label == "distance"):
                    continue
                s, e = (r.start, r.end) if r.label == "facility type" else trim_span(query, r.start, r.end, trim)
                if e > s:
                    spans.append(Span(text=query[s:e], start=s, end=e, label=r.label, score=r.score))
        except ImportError:
            impl = "regex (gliner unavailable)"
    spans.sort(key=lambda s: s.start)
    return Decision[list[Span]](value=spans, confidence=1.0, impl=impl,
                                trace={"latency_s": round(time.time() - t0, 4)})
