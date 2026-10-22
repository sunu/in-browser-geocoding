"""Add option-key labels to the paraphrase records (plan-006 section 3.3).

A paraphrase keeps the slot names of its seed, so a closed slot of the paraphrase has the option key of
the same slot in the seed. The seed records come from synthetic v1 (git 0281dfc), whose closed-slot spans
are exact words of the generator vocabulary. The key of a seed span is a reverse lookup in that vocabulary.

Usage: uv run python -m training.label_paraphrases --seeds <synthetic_v1.jsonl>
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from geoparse.t5.frames import Frame
from geoparse.templates.model import all_templates
from training.gen_synthetic import ATTR, CAT_KEY, DIR_OUT, DIR_PART, LEVEL, OP, PRED_POST, PRED_PRE

DATA = "training/data"


def reverse_vocab() -> dict[str, dict[str, str]]:
    rev: dict[str, dict[str, str]] = {"admin_level": {}, "predicate": {}, "direction": {}, "category": {},
                                      "attr": {}, "op": {}}
    for k, ws in LEVEL.items():
        for w in ws:
            rev["admin_level"][w.lower()] = "none" if k == "other" else k
    for d in (PRED_PRE, PRED_POST):
        for k, ws in d.items():
            for w in ws:
                rev["predicate"][w.lower()] = k
    for d in (DIR_PART, DIR_OUT):
        for k, ws in d.items():
            for w in ws:
                rev["direction"][w.lower()] = k
    for w, k in CAT_KEY.items():
        rev["category"][w.lower()] = k
    for w in ATTR:
        rev["attr"][w.lower()] = "population"
    for k, ws in OP.items():
        for w in ws:
            rev["op"][w.lower()] = k
    return rev


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", required=True)
    args = ap.parse_args()
    templates = all_templates()
    rev = reverse_vocab()
    seeds = {}
    for line in open(args.seeds):
        r = json.loads(line)
        seeds[r["query"]] = Frame.from_text(r["frame"])
    out, stats = [], Counter()
    for line in open(f"{DATA}/paraphrase.jsonl"):
        r = json.loads(line)
        sf = seeds.get(r["seed_query"])
        f = Frame.from_text(r["frame"])
        if sf is None or f is None or f.template == "unsupported":
            stats["no seed" if sf is None else "unsupported"] += 1
            r["closed_keys"] = {}
            out.append(r)
            continue
        tpl = templates[f.template]
        keys = {}
        for name, span in sf.slots.items():
            sd = tpl.slots.get(name)
            if sd is None or sd.type not in rev:
                continue
            k = rev[sd.type].get(span.lower())
            if k is None:
                stats[f"unmapped {sd.type}"] += 1
                continue
            if name in f.slots:
                keys[name] = k
        r["closed_keys"] = keys
        stats["labeled"] += 1
        out.append(r)
    open(f"{DATA}/paraphrase.jsonl", "w").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    print(dict(stats))


if __name__ == "__main__":
    main()
