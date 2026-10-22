"""Calibration of the local model on the validation questions (plan-006 section 3.4).

Reports accuracy and expected calibration error (ECE, 10 bins of the top probability) for each decision.
Usage: uv run python -m training.calibration [--model models/local/current]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from geoparse.config import REPO_ROOT
from geoparse.decisions.providers import LocalClassifierProvider


def ece(items: list[tuple[float, bool]], bins: int = 10) -> float:
    total = len(items)
    err = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, c) for p, c in items if (lo < p <= hi) or (b == 0 and p == 0)]
        if sel:
            err += len(sel) / total * abs(sum(p for p, _ in sel) / len(sel) - sum(c for _, c in sel) / len(sel))
    return err


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(REPO_ROOT / "models" / "local" / "current"))
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "local-calibration.json"))
    args = ap.parse_args()
    lp = LocalClassifierProvider(args.model)
    rows = [json.loads(l) for l in open(REPO_ROOT / "training" / "data" / "decisions.jsonl")]
    rows = [r for r in rows if r["split"] == "val"]
    by = defaultdict(list)
    for r in rows:
        probs = lp.probs(r["decision"], r["instructions"], r["state"], r["options"])
        best = max(probs, key=probs.get)
        b = r["decision"] if r["decision"].startswith("fill") else r["decision"].split(".")[0]
        by[b].append((probs[best], best == r["label"]))
    report = {}
    allitems = []
    for b, items in sorted(by.items()):
        allitems += items
        report[b] = {"n": len(items), "acc": round(sum(c for _, c in items) / len(items), 4), "ece": round(ece(items), 4)}
        print(f"{b:36s} n={len(items):5d} acc={report[b]['acc']:.3f} ece={report[b]['ece']:.3f}")
    report["all"] = {"n": len(allitems), "acc": round(sum(c for _, c in allitems) / len(allitems), 4),
                     "ece": round(ece(allitems), 4)}
    print("all", report["all"])
    open(args.out, "w").write(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
