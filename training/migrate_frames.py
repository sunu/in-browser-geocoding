"""Convert paraphrase frames of templates that changed in plan-036 (lists of places, the any/all quantifier).

  neighbors_both ; level ; a ; b  ->  neighbors ; level ; quant = <word> ; of = <a ... b>
  shared_border ; [distance] ; a ; b  ->  shared_border ; [distance] ; places = <a ... b>

A neighbors_both paraphrase without a quantifier word ("countries that touch X and Y") is dropped: with no word, "and"
reads as "any" (plan-036), so its label would be wrong. A record is also dropped if the text between the two places is
not a list separator ("where X meets Y").

Usage: uv run python -m training.migrate_frames [--file training/data/paraphrase.jsonl]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from geoparse.t5.frames import Frame

ROOT = Path(__file__).resolve().parents[1]
QUANT_ALL = re.compile(r"\b(both|all three of|all of|each of|in common|common)\b", re.I)
SEP = re.compile(r"^\s*(?:,\s*(?:and\s+|&\s+)?|and\s+|&\s*|as well as\s+)$", re.I)
SPACE = re.compile(r"^\s+$")


def list_span(q: str, a: str, b: str, space_ok: bool) -> str | None:
    """The text from the first to the last of two places, if a list separator joins them."""
    ia, ib = q.find(a), q.find(b)
    if ia < 0 or ib < 0:
        return None
    (i1, s1), (i2, s2) = sorted([(ia, a), (ib, b)])
    mid = q[i1 + len(s1):i2]
    if not (SEP.match(mid) or (space_ok and SPACE.match(mid))):
        return None
    return q[i1:i2 + len(s2)]


def migrate(rec: dict) -> dict | None:
    f = Frame.from_text(rec["frame"])
    if f is None or f.template not in ("neighbors_both", "shared_border"):
        return rec
    q, s = rec["query"], f.slots
    if f.template == "neighbors_both":
        m = QUANT_ALL.search(q)
        span = list_span(q, s.get("a", ""), s.get("b", ""), False)
        if not m or not span:
            return None
        slots = {k: v for k, v in s.items() if k == "level"} | {"quant": m.group(0), "of": span}
        new = Frame(template="neighbors", slots=slots)
        keys = {**rec.get("closed_keys", {}), "quant": "all"}
    else:
        span = list_span(q, s.get("a", ""), s.get("b", ""), True)
        if not span:
            return None
        new = Frame(template="shared_border", slots={k: v for k, v in s.items() if k == "distance"} | {"places": span})
        keys = rec.get("closed_keys", {})
    return {**rec, "frame": new.to_text(), "template": new.template, "closed_keys": keys,
            "sub_slots": [x for x in rec.get("sub_slots", []) if x not in ("a", "b")]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(ROOT / "training" / "data" / "paraphrase.jsonl"))
    args = ap.parse_args()
    path = Path(args.file)
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    out, dropped, changed = [], {"neighbors_both": 0, "shared_border": 0}, 0
    for r in recs:
        m = migrate(r)
        if m is None:
            dropped[r["template"]] += 1
            continue
        changed += m is not r
        out.append(m)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    print(f"{len(recs)} records: {changed} converted, dropped {dropped}, {len(out)} kept")


if __name__ == "__main__":
    main()
