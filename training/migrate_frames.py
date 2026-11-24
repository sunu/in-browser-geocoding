"""Convert paraphrase frames of templates that changed in plan-036 (lists of places, the any/all quantifier).

  neighbors_both ; level ; a ; b  ->  neighbors ; level ; quant = <word> ; of = <a ... b>
  shared_border ; [distance] ; a ; b  ->  shared_border ; [distance] ; places = <a ... b>
  union ; a ; b  and  union3 ; a ; b ; c  ->  union ; places = <a ... c>  (plan-038)

plan-039 (`--parts`): a list span in a region slot becomes its parts ("A | B"), and a qualified name "X in Y" or
"X, Y" becomes X with `<slot>.within = Y`. The parts come from the list split of the parser: the cut with the fewest
parts where each part is an exact name (in a union also a sub-query part). A text with a list separator and no such cut
is dropped (typos: the parts are not clear). A qualified name is changed only if the data has X inside Y. Run it in the
world scope (GEOPARSE_SCOPE=world), so that the names of other countries are exact names.

A neighbors_both paraphrase without a quantifier word ("countries that touch X and Y") is dropped: with no word, "and"
reads as "any" (plan-036), so its label would be wrong. A record is also dropped if the text between the two places is
not a list separator ("where X meets Y").

Usage: uv run python -m training.migrate_frames [--file training/data/paraphrase.jsonl] [--parts]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from collections import Counter

from geoparse.t5.frames import PART_SEP, Frame, find_span, merge_union_slots

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
    if f is not None and f.template in ("union", "union3") and "places" not in f.slots:
        new = merge_union_slots(f, rec["query"])
        if new is f:
            return None
        return {**rec, "frame": new.to_text(), "template": "union", "sub_slots": []}
    if f is None or f.template not in ("neighbors_both", "shared_border") or "places" in f.slots:
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


def split_parts(rec: dict, parser, dec) -> dict | None:
    """plan-039: list spans as parts and qualified names with `within`. None: drop the record (the parts are not clear)."""
    from geoparse.parse.pipeline import LIST_MARKER, LIST_SEP, SPACE_LIST_TEMPLATES, SUB_LIST_TEMPLATES, _level_words
    from geoparse.options import keyword_hits

    f = Frame.from_text(rec["frame"])
    tpl = parser.templates.get(f.template) if f is not None else None
    if tpl is None:
        return rec
    slots, sub_parts = {}, []
    for k, v in f.slots.items():
        sd = tpl.slots.get(k)
        if sd is None or sd.type not in ("region", "anchor") or PART_SEP in v or k in rec.get("sub_slots", []):
            slots[k] = v
            continue
        text = re.sub(r"^(the|whole|entire|all of|all of the|whole of)\s+", "", v.strip(), flags=re.I)
        is_list = LIST_SEP.search(text) or LIST_MARKER.match(text) or (f.template in SPACE_LIST_TEMPLATES and " " in text)
        if not is_list and not re.search(r"\sin\s", text):
            slots[k] = v
            continue
        # A qualified name first: the exact search reads "Jayanagar, Bengaluru" as Jayanagar with a context.
        if ("," in text or re.search(r"\sin\s", text)) and not re.search(r"\b(and|or)\b|&|\+", text, re.I):
            q = parser._qualified(dec, text, 0, exact=True)
            ctx = q["args"].get("context") if q else None
            if ctx and "," not in ctx and find_span(rec["query"], q["args"]["name"]) and find_span(rec["query"], ctx):
                slots[k], slots[f"{k}.within"] = q["args"]["name"], ctx
                continue
        # One name with "&" or "n" for "and" ("Jammu & Kashmir").
        if any(parser.store.search(x, fuzzy=False, limit=1, view=None)
               for x in {text, re.sub(r"\s+(?:&|n)\s+", " and ", text, flags=re.I)} if "," not in x):
            slots[k] = v
            continue
        if not is_list:
            slots[k] = v
            continue
        lst = parser._list_parts(dec, text, f.template in SPACE_LIST_TEMPLATES, False)
        if lst is None and f.template in SUB_LIST_TEMPLATES:
            lst = parser._list_parts(dec, text, False, True)
            # Only a cut of names and sub-queries, not the fallback cut with unknown parts.
            is_sub = lambda p: bool(keyword_hits(p, _level_words(), typo=False)) or bool(re.search(r"\d", p))
            if lst and not all(is_sub(p) or parser.store.search(p, fuzzy=False, limit=1, view=None) for p in lst[0]):
                lst = None
        if lst is None:
            if f.template in SUB_LIST_TEMPLATES or not keyword_hits(text, _level_words(), typo=False):
                return None
            slots[k] = v  # a sub-query with a list inside ("coastal districts of Kerala and Goa")
            continue
        parts = lst[0]
        # A part with a comma (a qualified name in the cut: "Tripura, Rajasthan") or a sub-query part with a separator
        # ("the Scandinavian countries and the city bordering X") is not clear.
        if not all(find_span(rec["query"], p) for p in parts) or any("," in p or LIST_SEP.search(p) and not
                                                                       parser.store.search(p, fuzzy=False, limit=1, view=None) for p in parts):
            return None
        slots[k] = PART_SEP.join(parts)
        sub_parts += [p for p in parts if keyword_hits(p, _level_words(), typo=False) or re.search(r"\d", p)]
    out = {**rec, "frame": Frame(template=f.template, slots=slots).to_text()}
    if sub_parts:
        out["sub_parts"] = sub_parts
    return out


def main_parts(path: Path) -> None:
    from geoparse.decisions.functions import Decider
    from geoparse.decisions.log import NullLogger
    from geoparse.parse.pipeline import Parser

    parser = Parser(Decider(logger=NullLogger(), use_ner=False), use_t5=False)
    dec = parser.base_decider.fork()
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    out, dropped, changed = [], [], Counter()
    for r in recs:
        m = split_parts(r, parser, parser.base_decider.fork())
        if m is None:
            dropped.append(r)
            continue
        if m["frame"] != r["frame"]:
            changed["within" if ".within" in m["frame"] else "parts"] += 1
        out.append(m)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    path.with_suffix(".dropped.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in dropped))
    print(f"{len(recs)} records: changed {dict(changed)}, dropped {len(dropped)}, {len(out)} kept")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(ROOT / "training" / "data" / "paraphrase.jsonl"))
    ap.add_argument("--parts", action="store_true", help="plan-039: list parts and `within`")
    args = ap.parse_args()
    path = Path(args.file)
    if args.parts:
        main_parts(path)
        return
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    out, dropped, changed = [], {"neighbors_both": 0, "shared_border": 0, "union": 0, "union3": 0}, 0
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
