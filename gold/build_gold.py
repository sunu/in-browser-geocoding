"""Build gold/gold.jsonl from gold/gold_src.yaml.

For each record: the gold DAG (from the template and the gold slots), and expected_ids (from the
execution of the gold DAG on the local extract). Records whose DAG needs the geocoder get
expected_ids = null, because the gold suite must not depend on the network.

Usage: uv run python gold/build_gold.py [--no-execute] [--set gold|heldout|world]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from geoparse.dsl.schema import PREDICATE_DAGS, substitute, validate
from geoparse.execute.data import get_store
from geoparse.execute.executor import Executor
from geoparse.options import choices
from geoparse.parse.pipeline import _slot_default
from geoparse.templates.model import CLOSED_TYPES, OPEN_TYPES, all_templates

GOLD_DIR = Path(__file__).resolve().parent


def gold_dag(t: str, s: dict[str, Any], src: dict[str, str] | None = None, view: list[float] | None = None,
             pins: dict[str, str] | None = None) -> dict[str, Any]:
    """pins: slot name to Overture id, for an anchor whose top gazetteer candidate is not the gold place."""
    tpl = all_templates()[t]
    store = get_store()
    values: dict[str, Any] = {}
    level = s.get("level")
    for name, sd in tpl.slots.items():
        v = s.get(name, sd.default)
        if sd.type in OPEN_TYPES:
            def one(v, pin=None):
                if isinstance(v, dict) and "lex" in v:
                    return {"op": "LexiconSet", "args": {"key": v["lex"]}}
                if isinstance(v, dict) and "q" in v:
                    return gold_dag(v["t"], v["s"], view=view)
                if (src or {}).get(name, "overture") == "photon":
                    return {"op": "Resolve", "args": {"name": v, "source": "photon"}}
                hint = level if t == "neighbors" and level not in (None, "none") else None
                cands = [] if pin else store.search(v, type_hint=hint, view=view)
                if not cands and not pin:
                    raise ValueError(f"gold anchor {v!r} not found")
                args = {"name": v, "source": "overture", "id": pin or cands[0].id}
                if hint:
                    args["type_hint"] = hint
                return {"op": "Resolve", "args": args}

            if isinstance(v, list):
                # A list of places: the Union of the names, in the order of the text.
                node = None
                for x in v:
                    node = one(x) if node is None else {"op": "Union", "args": {"a": node, "b": one(x)}}
                values[name] = node
            else:
                values[name] = one(v, (pins or {}).get(name))
        elif sd.type == "predicate":
            values[name] = PREDICATE_DAGS[v]
        elif sd.type == "admin_level" and v == "none":
            values[name] = None
        elif sd.type == "distance":
            policy_default = v is None or (isinstance(v, str) and v.startswith("policy."))
            values[name] = _slot_default(sd) if policy_default else float(v)
        elif sd.type == "quantifier":
            values[name] = None if v in (None, "any") else v  # `any` is the operator default (no argument)
        elif sd.type in CLOSED_TYPES or sd.type == "value":
            values[name] = v
    dag = substitute(tpl.dag_json, values)
    errs = validate(dag, choices())
    if errs:
        raise ValueError(f"gold DAG invalid for template {t}: {errs}")
    return dag


def geometry_summary(res) -> dict[str, Any] | None:
    """Area (km2, approximate) and centroid of a geometry result, for comparison with a tolerance."""
    import math

    import shapely
    from shapely.geometry import shape

    geoms = [shape(f.geometry) for f in res.features if f.geometry]
    if not geoms:
        return None
    g = shapely.union_all(geoms)
    c = g.centroid
    k = 111.32 ** 2 * math.cos(math.radians(c.y))
    return {"area_km2": round(g.area * k, 3), "centroid": [round(c.x, 5), round(c.y, 5)]}


def depth_of(s: dict[str, Any]) -> int:
    d = 0
    for v in s.values():
        for x in v if isinstance(v, list) else [v]:
            if isinstance(x, dict) and "q" in x:
                d = max(d, 1 + depth_of(x["s"]))
    return d


def needs_network(dag: Any) -> bool:
    if isinstance(dag, dict):
        from geoparse.config import load_config

        local_features = load_config()["geocoder"].get("features_source", "places") == "places"
        if (dag.get("op") == "Features" and not local_features) or (
                dag.get("op") == "Resolve" and dag["args"].get("source") == "photon"):
            return True
        return any(needs_network(v) for v in dag.get("args", {}).values())
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-execute", action="store_true")
    ap.add_argument("--set", default="gold", help="gold, heldout, world, world_heldout, world_heldout2, world_heldout3, world_heldout4, world_heldout5, world_heldout6 or world_heldout7 (world sets: GEOPARSE_SCOPE=world)")
    args = ap.parse_args()
    src = yaml.safe_load((GOLD_DIR / f"{args.set}_src.yaml").read_text())
    # The world set: {views: {cc: bbox}, records: [... {cc: ...}]}. Each record gets the view of its country.
    views = src.get("views", {}) if isinstance(src, dict) else {}
    src = src["records"] if isinstance(src, dict) else src
    templates = all_templates()
    ex = Executor()
    out = []
    for i, r in enumerate(src):
        t = r["t"]
        view = views.get(r.get("cc"))
        dag = gold_dag(t, r["s"], r.get("src"), view, r.get("ids"))
        rec = {
            "id": f"{ {'gold': 'g', 'heldout': 'h', 'world': 'w', 'world_heldout': 'x', 'world_heldout2': 'y', 'world_heldout3': 'z', 'world_heldout4': 'n', 'world_heldout5': 'v', 'world_heldout6': 'u', 'world_heldout7': 't'}[args.set]}{i + 1:03d}", "query": r["q"], "lang": "en", "family": templates[t].family, "template": t,
            "slots": r["s"], "src": r.get("src", {}), "depth": depth_of(r["s"]), "dag": dag,
            "expected_ids": None, "notes": r.get("n", ""),
        }
        if view:
            rec["cc"], rec["view"] = r["cc"], view
        if not args.no_execute and not needs_network(dag):
            res = ex.execute(dag, with_geometry=False, view=view)
            if not res.ok:
                raise RuntimeError(f"{rec['id']} {r['q']!r}: {res.error}")
            rec["expected_ids"] = res.ids
            rec["expected_names"] = sorted({f.name for f in res.features if f.name})[:40]
            # A geometry, or a set of computed areas with no IDs (Intersect of a strip and a place): compare the shape.
            if res.kind == "geometry" or (res.features and not res.ids):
                rec["expected_geometry"] = geometry_summary(ex.execute(dag, with_geometry=True, view=view))
        out.append(rec)
        print(f"{rec['id']} d{rec['depth']} {t:24s} {r['q']!r:60s} n={len(rec['expected_ids']) if rec['expected_ids'] is not None else '-'}")
    with (GOLD_DIR / f"{args.set}.jsonl").open("w") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"{len(out)} records")


if __name__ == "__main__":
    main()
