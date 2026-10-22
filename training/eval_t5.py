"""Evaluate the T5 candidate generator alone, and the full pipeline on the LLM test set.

Usage:
  uv run python -m training.eval_t5 --t5 models/t5/t5-small               # T5 alone
  uv run python -m training.eval_t5 --t5 models/t5/t5-small --pipeline jev  # plus full pipeline on llm_test

Core of a frame: template, open-slot texts (lower case), distance in meters, value as a number.
Closed-slot texts are not compared, because Jev maps them to options later.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from geoparse.config import REPO_ROOT
from geoparse.options import norm
from geoparse.t5.frames import Frame, distance_m, value_num
from geoparse.t5.model import T5Parser
from geoparse.templates.model import OPEN_TYPES, all_templates

DATA = REPO_ROOT / "training" / "data"
T = all_templates()


def ntext(s: str) -> str:
    import re

    return re.sub(r"^(the|a|an) ", "", norm(s))


def core_of_frame(f: Frame) -> tuple:
    if f.template == "unsupported":
        return ("unsupported",)
    t = T.get(f.template)
    if t is None:
        return (f.template, "?")
    parts = [f.template]
    for k, sd in sorted(t.slots.items()):
        v = f.slots.get(k)
        if sd.type in OPEN_TYPES:
            parts.append((k, ntext(v) if v else None))
        elif sd.type == "distance":
            parts.append((k, round(distance_m(v), 1) if v and distance_m(v) is not None else None))
        elif sd.type == "value":
            parts.append((k, round(value_num(v), 1) if v and value_num(v) is not None else None))
    return tuple(parts)


def core_of_gold(rec: dict) -> tuple:
    t = T[rec["template"]]
    s = rec["slots"]
    parts = [rec["template"]]
    for k, sd in sorted(t.slots.items()):
        v = s.get(k)
        if sd.type in OPEN_TYPES:
            if isinstance(v, dict):
                v = v.get("text") or v.get("q")
            parts.append((k, ntext(v) if v else None))
        elif sd.type in ("distance", "value"):
            parts.append((k, round(float(v), 1) if v is not None else None))
    return tuple(parts)


def core_of_parse(p) -> tuple:
    if not p.ok:
        return ("unsupported",)
    t = T[p.template]
    parts = [p.template]
    for k, sd in sorted(t.slots.items()):
        v = p.slots.get(k)
        if sd.type in OPEN_TYPES:
            if isinstance(v, dict):
                v = v.get("text") or v.get("q")
            parts.append((k, ntext(v) if v else None))
        elif sd.type in ("distance", "value"):
            parts.append((k, round(float(v), 1) if v is not None else None))
    return tuple(parts)


def load_sets() -> dict[str, list[dict]]:
    sets = {}
    for name in ("gold", "heldout"):
        recs = [json.loads(l) for l in (REPO_ROOT / "gold" / f"{name}.jsonl").read_text().splitlines() if l.strip()]
        sets[name] = [{"query": r["query"], "core": core_of_gold(r), "template": r["template"]} for r in recs]
    for name in ("llm_dev", "llm_test"):
        p = DATA / f"{name}.jsonl"
        if not p.exists():
            continue
        recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        sets[name] = [{"query": r["query"], "core": core_of_frame(Frame.from_text(r["frame"])), "frame": r["frame"],
                       "template": r["template"]} for r in recs]
    return sets


def eval_t5(model: T5Parser, sets: dict[str, list[dict]], k: int) -> dict:
    res = {}
    for name, recs in sets.items():
        top1 = topk = exact = 0
        lat = []
        errors = []
        for r in recs:
            frames, dt = model.frames(r["query"], k=k)
            lat.append(dt)
            cores = [core_of_frame(f) for f in frames]
            top1 += bool(cores) and cores[0] == r["core"]
            topk += r["core"] in cores
            if "frame" in r and frames:
                exact += frames[0].to_text() == r["frame"]
            if not cores or cores[0] != r["core"]:
                errors.append((r["query"], frames[0].to_text() if frames else None, r.get("frame") or r["core"]))
        n = len(recs)
        res[name] = {"n": n, "top1": top1 / n, f"top{k}": topk / n, "exact": exact / n if "frame" in recs[0] else None,
                     "median_ms": 1000 * statistics.median(lat), "errors": errors}
    return res


def eval_pipeline(provider: str, t5_dir: str, recs: list[dict], use_patterns: str, workers: int,
                  overrides: dict[str, str] | None = None) -> dict:
    from geoparse.decisions.functions import Decider
    from geoparse.decisions.log import DecisionLogger
    from geoparse.parse.pipeline import Parser

    import copy

    from geoparse.config import load_config

    # `provider` sets every decision; `overrides` sets single decisions (jev, local, or rules).
    cfg = copy.deepcopy(load_config())
    cfg["decisions"]["providers"] = {k: provider for k in cfg["decisions"]["providers"]}
    cfg["decisions"]["providers"].update(overrides or {})
    parser = Parser(Decider(config=cfg, logger=DecisionLogger(), jev_mode="cached",
                            jev_cache=str(REPO_ROOT / "tests" / "fixtures" / "jev_cache.jsonl")),
                    t5_dir=t5_dir, use_t5=True, use_patterns=use_patterns)
    parser.parse("Kerala")

    def one(r):
        t0 = time.time()
        p = parser.parse(r["query"])
        return r, p, time.time() - t0

    by_t = defaultdict(lambda: [0, 0])
    errors = []
    lat = []
    ok = 0
    with ThreadPoolExecutor(workers) as pool:
        for r, p, dt in pool.map(one, recs):
            c = core_of_parse(p)
            hit = c == r["core"]
            ok += hit
            by_t[r["template"]][0] += hit
            by_t[r["template"]][1] += 1
            lat.append(dt)
            if not hit:
                errors.append((r["query"], r.get("frame"), p.template, p.slots if p.ok else p.unsupported.reason))
    return {"n": len(recs), "acc": ok / len(recs), "by_template": {k: f"{a}/{b}" for k, (a, b) in sorted(by_t.items())},
            "median_s": statistics.median(lat), "errors": errors}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t5", required=True)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--pipeline", choices=["jev", "rules", "local"])
    ap.add_argument("--patterns", default="fallback")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out")
    ap.add_argument("--set", default="llm_test", help="set for the pipeline evaluation")
    ap.add_argument("--override", default="", help="decision=provider list, for example select_source=rules")
    ap.add_argument("--no-t5-alone", action="store_true")
    args = ap.parse_args()
    sets = load_sets()
    model = T5Parser(args.t5)
    report = {"t5": args.t5, "t5_alone": {} if args.no_t5_alone else eval_t5(model, sets, args.k)}
    for name, r in report["t5_alone"].items():
        print(f"T5 alone {name:9s} n={r['n']:4d} top1={r['top1']:.3f} top{args.k}={r[f'top{args.k}']:.3f} "
              f"exact={r['exact']} median={r['median_ms']:.0f} ms")
    if args.pipeline:
        overrides = dict(x.split("=") for x in args.override.split(",") if x)
        pr = eval_pipeline(args.pipeline, args.t5, sets[args.set], args.patterns, args.workers, overrides)
        report[f"pipeline_{args.set}"] = pr
        print(f"pipeline ({args.pipeline}, patterns={args.patterns}, override={args.override or '-'}) {args.set} "
              f"acc={pr['acc']:.3f} median={pr['median_s']:.2f}s")
        print(json.dumps(pr["by_template"]))
    out = Path(args.out or REPO_ROOT / "reports" / f"t5-eval-{Path(args.t5).name}{'-' + args.pipeline + '-' + args.set if args.pipeline else ''}.json")
    out.write_text(json.dumps(report, indent=1, default=str))
    print("wrote", out)


if __name__ == "__main__":
    main()
