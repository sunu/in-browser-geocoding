"""Parse frames: the output format of the T5 candidate generator (plan-005 section 3.1).

Text form:  <template> ; <slot> = <value> ; <slot> = <value>
Special frame: "unsupported".

A region slot can hold a list, with " | " between the parts (plan-039): `parent = France | Spain`. A region slot can
have a qualifier `<slot>.within`: `anchor = Springfield ; anchor.within = Illinois`.

Open and closed slots are exact spans of the query. Quantities are a number in digits and a unit or a
scale word. Code converts them: distance to meters, value to a plain number.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

UNSUPPORTED = "unsupported"
PART_SEP = " | "
WITHIN = ".within"
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


def slot_parts(value: str) -> list[str]:
    """The parts of a list slot value; one part if the value is not a list."""
    return [p.strip() for p in value.split(PART_SEP)]


def find_span(query: str, span: str) -> tuple[int, int] | None:
    """Character range of `span` in `query` (case-insensitive, whole words). None if it is not in the query."""
    if not span.strip():
        return None
    m = re.search(r"(?<!\w)" + re.escape(span.strip()) + r"(?!\w)", query, re.I)
    return (m.start(), m.end()) if m else None


def merge_union_slots(frame: Frame, query: str) -> Frame:
    """A frame of the old union templates (union ; a ; b, union3 ; a ; b ; c) as union ; places = the text from the
    first to the last part (plan-038: one union template with a list). For training.migrate_frames."""
    if frame.template not in ("union", "union3") or "places" in frame.slots:
        return frame
    spans = [find_span(query, frame.slots[k]) for k in ("a", "b", "c") if k in frame.slots]
    if len(spans) < 2 or not all(spans):
        return frame
    places = query[min(r[0] for r in spans):max(r[1] for r in spans)]
    return frame.model_copy(update={"template": "union", "slots": {"places": places}})


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
        if name.endswith(WITHIN):
            base = t.slots.get(name[:-len(WITHIN)])
            if base is None or base.type not in ("region", "anchor") or name[:-len(WITHIN)] not in frame.slots:
                problems.append(f"unknown slot {name}")
            elif find_span(query, value) is None:
                problems.append(f"span {value!r} is not in the query")
        elif sd is None:
            problems.append(f"unknown slot {name}")
        elif sd.type == "distance":
            if distance_m(value) is None:
                problems.append(f"bad distance {value!r}")
        elif sd.type == "value":
            if value_num(value) is None:
                problems.append(f"bad value {value!r}")
        elif sd.type in ("region", "anchor") and PART_SEP in value:
            parts = slot_parts(value)
            problems += [f"span {p!r} is not in the query" for p in parts if find_span(query, p) is None]
        elif find_span(query, value) is None:
            problems.append(f"span {value!r} is not in the query")
    # The same text in two region slots or list parts ("union ; a = England and Wales ; b = England and Wales"), more
    # times than the query has it ("Kerala and Kerala" has two).
    texts = Counter(p.strip().lower() for k, v in frame.slots.items()
                    if k in t.slots and t.slots[k].type in ("region", "anchor") for p in slot_parts(v))
    if any(n > len(re.findall(r"(?<!\w)" + re.escape(x) + r"(?!\w)", query, re.I)) for x, n in texts.items() if n > 1):
        problems.append("the same text in two region slots")
    for name, sd in t.slots.items():
        if name not in frame.slots and sd.type not in ("distance",) and not sd.optional and sd.default is None:
            problems.append(f"missing slot {name}")
    return problems


def frame_to_match(frame: Frame, query: str) -> dict[str, Any]:
    """Convert a frame to the split-match format of the pipeline (segments and feeds, one per slot)."""
    segments, feeds, within = {}, {}, {}
    for name, value in frame.slots.items():
        if name.endswith(WITHIN):
            r = find_span(query, value)
            within[name[:-len(WITHIN)]] = query[r[0]:r[1]] if r else value
            continue
        if name in ("distance", "value"):
            segments[name] = value
        elif PART_SEP in value:
            spans = [find_span(query, p) for p in slot_parts(value)]
            segments[name] = PART_SEP.join(query[r[0]:r[1]] if r else p for r, p in zip(spans, slot_parts(value)))
        else:
            r = find_span(query, value)
            segments[name] = query[r[0]:r[1]] if r else value
        feeds[name] = [name]
    return {"segments": segments, "feeds": feeds, "within": within, "literals": 0, "source": "t5", "t5_score": frame.score}


COVER_MARGIN = 0.5


def covered(frame: Frame, query: str) -> int:
    """The number of query characters in the slot spans of the frame."""
    spans = [find_span(query, p) for k, v in frame.slots.items() for p in slot_parts(v)]
    return len(set().union(*(range(*r) for r in spans if r))) if spans else 0


def group_frames(frames: list[Frame], query: str, templates: dict[str, Any], margin: float) -> list[Frame]:
    """Usable frames, one for each (template, open-slot spans) group, within `margin` of the best score.

    Frames that differ only in closed-slot spans or quantities are one group. One frame of the group gives its closed
    spans and quantities (see COVER_MARGIN). The decision model does not choose quantities.
    """
    groups: dict[tuple, list[Frame]] = {}
    for f in frames:
        if f.template == UNSUPPORTED or check_frame(f, query, templates):
            continue
        t = templates[f.template]
        key = (f.template,) + tuple(sorted((k, v.lower()) for k, v in f.slots.items()
                                           if k.endswith(WITHIN) or k in t.slots and t.slots[k].type in ("region", "anchor")))
        groups.setdefault(key, []).append(f)
    if not groups:
        return []
    # In a group, a frame within COVER_MARGIN of the best score that covers more of the query wins ("neighbors ; of =
    # Rajasthan" loses to "neighbors ; level = states ; of = Rajasthan"). Its score is the best score of the group.
    best = {}
    for key, fs in groups.items():
        top = max(f.score for f in fs)
        pick = max((f for f in fs if f.score >= top - COVER_MARGIN), key=lambda f: (covered(f, query), f.score))
        best[key] = pick.model_copy(update={"score": top}) if pick.score != top else pick
    top = max(f.score for f in best.values())
    return sorted([f for f in best.values() if f.score >= top - margin], key=lambda f: -f.score)
