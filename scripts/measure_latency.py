"""Measure live parse latency with Jev (no cache). Runs each query once, one at a time."""
import json
import statistics
import sys
import time
from pathlib import Path

from geoparse.decisions.functions import Decider
from geoparse.decisions.log import NullLogger
from geoparse.parse.pipeline import Parser

ROOT = Path(__file__).resolve().parents[1]
recs = [json.loads(l) for l in (ROOT / "gold" / "gold.jsonl").read_text().splitlines()]
d0 = [r for r in recs if r["depth"] == 0][::4]
d1 = [r for r in recs if r["depth"] == 1]
parser = Parser(Decider(default="jev", logger=NullLogger(), jev_mode="live"))
parser.parse("Kerala")  # load GLiNER and the store
rows = []
for r in d0 + d1:
    t0 = time.time()
    p = parser.parse(r["query"])
    dt = time.time() - t0
    jev = [t for t in p.trace if t["impl"] == "jev"]
    cost = sum((t["trace"].get("cost") or 0) for t in jev)
    rows.append({"depth": r["depth"], "latency_s": dt, "calls": len(jev), "cost": cost, "ok": p.ok})
    print(f"d{r['depth']} {dt:5.2f}s calls={len(jev):2d} ${cost:.6f} {r['query']}")
for d in (0, 1):
    rs = [x for x in rows if x["depth"] == d]
    lat = sorted(x["latency_s"] for x in rs)
    print(f"depth {d}: n={len(rs)} median {statistics.median(lat):.2f}s p90 {lat[int(0.9 * (len(lat) - 1))]:.2f}s max {lat[-1]:.2f}s "
          f"mean calls {statistics.mean(x['calls'] for x in rs):.1f} mean cost ${statistics.mean(x['cost'] for x in rs):.6f}")
