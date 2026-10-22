"""Build the training set for the local cross-encoder (plan-006 section 3.3).

Each output line is one decision question:
  {"decision", "instructions", "state", "options": {key: description}, "label": key,
   "soft": {key: prob} or null, "source", "split": "train" | "val", "query"}

Sources:
  1. synthetic + paraphrase queries with exact labels from the generator (option keys, sub-query slots,
     gold frames). The questions are built exactly as the pipeline builds them.
  2. Jev decisions from the logs (soft labels), except runs on evaluation queries (gold, held-out, LLM dev,
     LLM test).

Usage: uv run python -m training.build_decisions
"""
from __future__ import annotations

import glob
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

from geoparse.config import REPO_ROOT
from geoparse.decisions.functions import INSTRUCTIONS, IS_SUBQUERY_CRITERIA, NONE_OPTION
from geoparse.options import categories, norm, option_descriptions
from geoparse.parse.pipeline import Parser, normalize_query
from geoparse.t5.frames import Frame, frame_to_match, group_frames
from geoparse.templates.model import CLOSED_TYPES, OPEN_TYPES
from training.gen_synthetic import typo_always

DATA = REPO_ROOT / "training" / "data"
CLOSED_REF = {"admin_level": "admin_levels", "predicate": "predicates", "direction": "directions",
              "category": "categories", "attr": "attrs", "op": "ops"}


def split_of(query: str) -> str:
    h = int(hashlib.md5(query.lower().encode()).hexdigest()[:8], 16)
    return "val" if h % 20 == 0 else "train"


def closed_options(ref: str) -> dict[str, str]:
    opts = {k: v for k, v in option_descriptions(ref).items() if k != "none"}
    opts["none"] = NONE_OPTION if ref != "admin_levels" else option_descriptions(ref)["none"]
    return opts


def category_group(leaf: str) -> str:
    for g, v in categories().items():
        if leaf in v["items"]:
            return g
    raise KeyError(leaf)


def ex(decision, state, options, label, query, source, soft=None):
    instr = INSTRUCTIONS.get(decision, INSTRUCTIONS.get(decision.split(".")[0], ""))
    if decision == "is_subquery":
        instr = INSTRUCTIONS["is_subquery"]
    return {"decision": decision, "instructions": instr, "state": state, "options": options, "label": label,
            "soft": soft, "source": source, "split": split_of(query), "query": query}


def from_generator(parser: Parser, beams: dict[str, list], rng: random.Random) -> list[dict]:
    templates = parser.templates
    out = []
    stats = Counter()
    recs = []
    for name in ("synthetic.jsonl", "paraphrase.jsonl"):
        recs += [json.loads(l) for l in (DATA / name).read_text().splitlines() if l.strip()]
    for r in recs:
        q = r["query"]
        text = normalize_query(q)
        gold = Frame.from_text(r["frame"])
        src = r.get("source", "synthetic")
        if gold is None:
            continue
        # Lookup guard: is the whole text one place name?
        crit = {"true": IS_SUBQUERY_CRITERIA["true"], "false": IS_SUBQUERY_CRITERIA["false"]}
        if gold.template == "lookup_place" or (gold.template != "unsupported" and rng.random() < 0.25):
            out.append(ex("is_subquery", {"text": text}, crit, "false" if gold.template == "lookup_place" else "true", q, src))
        if gold.template == "unsupported":
            continue
        tpl = templates[gold.template]
        keys = r.get("closed_keys") or {}
        # Closed slots.
        for name, span in gold.slots.items():
            sd = tpl.slots.get(name)
            if sd is None or sd.type not in CLOSED_TYPES or name not in keys:
                continue
            key = keys[name]
            state = {"text": span}
            if sd.type == "category":
                groups = option_descriptions("categories")
                groups["none"] = NONE_OPTION
                out.append(ex("fill_closed_slot.category.group", state, groups, category_group(key), q, src))
                g = category_group(key)
                items = {k: v["description"] for k, v in categories()[g]["items"].items()}
                out.append(ex("fill_closed_slot.category", state, items, key, q, src))
            else:
                out.append(ex(f"fill_closed_slot.{sd.type}", state, closed_options(CLOSED_REF[sd.type]), key, q, src))
                # A copy with a typo, so that the model reads misspelled closed words ("disctricts").
                if rng.random() < 0.3 and any(len(w) >= 5 for w in span.split()):
                    words = span.split()
                    i = rng.choice([j for j, w in enumerate(words) if len(w) >= 5])
                    words[i] = typo_always(rng, words[i])
                    out.append(ex(f"fill_closed_slot.{sd.type}", {"text": " ".join(words)},
                                  closed_options(CLOSED_REF[sd.type]), key, q, src + "+typo"))
            stats["closed"] += 1
        # Region slots: sub-query or a name?
        subs = set(r.get("sub_slots") or [])
        for name, span in gold.slots.items():
            sd = tpl.slots.get(name)
            if sd is None or sd.type != "region" or tpl.family == "lookup":
                continue
            out.append(ex("is_subquery", {"text": re.sub(r"^(the|a|an)\s+", "", span, flags=re.I)}, crit,
                          "true" if name in subs else "false", q, src))
        # Frame choice from the T5 beams of this query.
        b = beams.get(q)
        if not b:
            continue
        frames = [f for f in (Frame.from_text(t, s) for t, s in b) if f is not None]
        groups = group_frames(frames, text, templates, margin=2.0)
        if not groups:
            stats["no groups"] += 1
            continue

        def open_key(f):
            t = templates[f.template]
            return (f.template,) + tuple(sorted((k, norm(v)) for k, v in f.slots.items()
                                               if k in t.slots and t.slots[k].type in OPEN_TYPES))

        gk = open_key(gold)
        if gk not in {open_key(f) for f in groups}:
            stats["gold not in beam"] += 1
            continue
        fams = {}
        for f in groups:
            fam = templates[f.template].family
            fams[fam] = parser.families[fam].description
        family = tpl.family
        if len(fams) > 1:
            out.append(ex("pick_family", {"query": text}, fams, family, q, src))
        tids = {f.template: parser._template_option(f.template) for f in groups if templates[f.template].family == family}
        if len(tids) > 1:
            out.append(ex("pick_template", {"query": text}, tids, gold.template, q, src))
        same = [f for f in groups if f.template == gold.template]
        if len(same) > 1:
            matches = [frame_to_match(f, text) for f in same]
            labels = parser._labels(tpl, matches[0])
            opts = {f"s{i}": "; ".join(f"{labels.get(k, k)} = '{v}'" for k, v in m["segments"].items())
                    for i, m in enumerate(matches)}
            label = next(f"s{i}" for i, f in enumerate(same) if open_key(f) == gk)
            out.append(ex("pick_split", {"query": text, "template": tpl.description}, opts, label, q, src))
        stats["frame"] += 1
    print("generator:", dict(stats))
    return out


def from_logs(eval_queries: set[str]) -> list[dict]:
    recs = []
    for p in sorted(glob.glob(str(REPO_ROOT / "logs" / "decisions-*.jsonl"))):
        recs += [json.loads(l) for l in open(p)]
    bad_runs = set()
    for r in recs:
        q = (r.get("inputs") or {}).get("query")
        if q and norm(q) in eval_queries:
            bad_runs.add(r["run_id"])
    out = []
    stats = Counter()
    for r in recs:
        if r["impl"] != "jev" or r["run_id"] in bad_runs:
            continue
        d = r["decision"]
        tr = r.get("trace") or {}
        state = tr.get("state")
        if state is None:
            continue
        q = (r.get("inputs") or {}).get("query") or json.dumps(state)
        if d == "is_subquery":
            p = tr.get("p_yes")
            if p is None:
                continue
            out.append(ex(d, state, dict(IS_SUBQUERY_CRITERIA), "true" if p >= 0.5 else "false", q, "jev",
                          soft={"true": p, "false": 1 - p}))
        else:
            opts = r.get("options")
            probs = tr.get("probabilities")
            if not isinstance(opts, dict) or not probs or d not in INSTRUCTIONS:
                continue
            if any(":" in k for k in opts):  # old OSM-tag category keys
                continue
            if set(probs) != set(opts):
                continue
            out.append(ex(d, state, opts, r["output"], q, "jev", soft=probs))
        stats[d] += 1
    print("jev logs (after excluding evaluation runs):", dict(stats), "runs excluded:", len(bad_runs))
    return out


def main() -> None:
    rng = random.Random(17)
    parser = Parser(use_t5=False)
    beams = {}
    for line in (DATA / "beams.jsonl").read_text().splitlines():
        r = json.loads(line)
        beams[r["query"]] = r["beams"]
    eval_queries = set()
    for p in [REPO_ROOT / "gold" / "gold.jsonl", REPO_ROOT / "gold" / "heldout.jsonl", DATA / "llm_dev.jsonl",
              DATA / "llm_test.jsonl"]:
        eval_queries |= {norm(json.loads(l)["query"]) for l in p.read_text().splitlines() if l.strip()}
    rows = from_generator(parser, beams, rng) + from_logs(eval_queries)
    # Remove any example whose query is an evaluation query.
    rows = [r for r in rows if norm(r["query"]) not in eval_queries]
    rng.shuffle(rows)
    (DATA / "decisions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    c = Counter((r["decision"].split(".")[0] if not r["decision"].startswith("fill") else r["decision"], r["split"]) for r in rows)
    for k in sorted(c):
        print(k, c[k])
    print("total", len(rows))


if __name__ == "__main__":
    main()
