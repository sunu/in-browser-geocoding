"""Parse frames: the output format of the T5 candidate generator (plan-005 section 3.1).

Text form:  <template> ; <slot> = <value> ; <slot> = <value>
Special frame: "unsupported".

Open and closed slots are exact spans of the query. Quantities are a number in digits and a unit or a
scale word. Code converts them: distance to meters, value to a plain number.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

UNSUPPORTED = "unsupported"
DISTANCE_UNITS = {"m": 1.0, "km": 1000.0, "mi": 1609.344}
VALUE_SCALES = {"": 1.0, "thousand": 1e3, "lakh": 1e5, "million": 1e6, "crore": 1e7, "billion": 1e9}
_DIST = re.compile(r"^(\d+(?:\.\d+)?)\s*(m|km|mi)$")
_VAL = re.compile(r"^(\d+(?:\.\d+)?)\s*(thousand|lakh|million|crore|billion)?$")


class Frame(BaseModel):
    template: str
    slots: dict[str, str] = Field(default_factory=dict)
    score: float = 0.0  # log probability from the beam search

    def to_text(self) -> str:
        if self.template == UNSUPPORTED:
            return UNSUPPORTED
        return " ; ".join([self.template] + [f"{k} = {v}" for k, v in self.slots.items()])

    @classmethod
    def from_text(cls, text: str, score: float = 0.0) -> "Frame | None":
        parts = [p.strip() for p in text.strip().split(" ; ")]
        if not parts or not parts[0]:
            return None
        if parts[0] == UNSUPPORTED:
            return cls(template=UNSUPPORTED, score=score)
        slots = {}
        for p in parts[1:]:
            if " = " not in p:
                return None
            k, v = p.split(" = ", 1)
            slots[k.strip()] = v.strip()
        return cls(template=parts[0], slots=slots, score=score)


def distance_m(text: str) -> float | None:
    m = _DIST.match(text.strip())
    return float(m.group(1)) * DISTANCE_UNITS[m.group(2)] if m else None


def value_num(text: str) -> float | None:
    m = _VAL.match(text.strip())
    return float(m.group(1)) * VALUE_SCALES[m.group(2) or ""] if m else None


def find_span(query: str, span: str) -> tuple[int, int] | None:
    """Character range of `span` in `query` (case-insensitive). None if the span is not in the query."""
    i = query.lower().find(span.lower())
    return (i, i + len(span)) if i >= 0 and span.strip() else None


def check_frame(frame: Frame, query: str, templates: dict[str, Any]) -> list[str]:
    """Hard checks in code. Returns a list of problems; empty means the frame is usable."""
    if frame.template == UNSUPPORTED:
        return []
    t = templates.get(frame.template)
    if t is None:
        return [f"unknown template {frame.template}"]
    problems = []
    for name, value in frame.slots.items():
        sd = t.slots.get(name)
        if sd is None:
            problems.append(f"unknown slot {name}")
        elif sd.type == "distance":
            if distance_m(value) is None:
                problems.append(f"bad distance {value!r}")
        elif sd.type == "value":
            if value_num(value) is None:
                problems.append(f"bad value {value!r}")
        elif find_span(query, value) is None:
            problems.append(f"span {value!r} is not in the query")
    for name, sd in t.slots.items():
        if name not in frame.slots and sd.type not in ("distance",) and not sd.optional and sd.default is None:
            problems.append(f"missing slot {name}")
    return problems


def frame_to_match(frame: Frame, query: str) -> dict[str, Any]:
    """Convert a frame to the split-match format of the pipeline (segments and feeds, one per slot)."""
    segments, feeds = {}, {}
    for name, value in frame.slots.items():
        if name in ("distance", "value"):
            segments[name] = value
        else:
            r = find_span(query, value)
            segments[name] = query[r[0]:r[1]] if r else value
        feeds[name] = [name]
    return {"segments": segments, "feeds": feeds, "literals": 0, "source": "t5", "t5_score": frame.score}
