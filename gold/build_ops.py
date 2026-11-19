"""Operator tests for the template review (plan-025 phase 12): DAGs written in the source, no template.

The expected result comes from the Python executor on the world data. web/scripts/exec_parity.ts (SETS=ops) runs
the same DAGs in the browser version. A name in the DAG text is resolved with the gazetteer (top candidate with the
view of the record); `ne-...` is the id of a natural feature.

Build: GEOPARSE_SCOPE=world uv run python -m gold.build_ops
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from geoparse.dsl.schema import PREDICATE_DAGS, validate
from geoparse.execute.data import get_store
from geoparse.execute.executor import Executor
from gold.build_gold import geometry_summary

GOLD_DIR = Path(__file__).resolve().parent
IN, ES, NP, EU, KA = [68, 8, 97, 37], [-9.3, 36, 3.3, 43.8], [80, 26, 88.2, 30.5], [-10, 36, 30, 60], [74, 11.5, 78.6, 18.5]

# (gap of reports/template-review.md, query, view, DAG with names in angle brackets)
RECORDS = [
    ("G1", "border between Spain and Portugal", ES, {"op": "SharedBorder", "args": {"a": "<Spain>", "b": "<Portugal>"}}),
    ("G1", "10 km zone along the border of India and Pakistan", IN,
     {"op": "Along", "args": {"line": {"op": "SharedBorder", "args": {"a": "<India>", "b": "<Pakistan>"}}, "distance_m": 10000}}),
    ("G2", "rivers in Karnataka", KA, {"op": "Naturals", "args": {"kind": "river", "within": "<Karnataka>"}}),
    ("G2", "mountain ranges of Nepal", NP, {"op": "Naturals", "args": {"kind": "range", "within": "<Nepal>"}}),
    ("G3", "countries along the Danube", EU, {"op": "Neighbors", "args": {"of": "<ne-river-Q1653>", "level": "country"}}),
    ("G4", "Karnataka within the Western Ghats", KA, {"op": "Intersect", "args": {"a": "<Karnataka>", "b": "<ne-range-Q4527>"}}),
    ("G5", "districts of Maharashtra within 50 km of Goa", IN,
     {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": "<Maharashtra>", "level": "district"}},
                               "pred": {"op": "Touches", "args": {"target": {"op": "Buffer", "args": {"of": "<Goa>", "distance_m": 50000}}}}}}),
    ("G6", "5 largest districts of Karnataka", KA,
     {"op": "Top", "args": {"set": {"op": "Children", "args": {"of": "<Karnataka>", "level": "district"}}, "by": "area", "n": 5, "order": "largest"}}),
    ("G6", "the smallest state of India", IN,
     {"op": "Top", "args": {"set": {"op": "Children", "args": {"of": "<India>", "level": "state"}}, "by": "area", "n": 1, "order": "smallest"}}),
    ("G7", "coastal countries that border India", IN,
     {"op": "Filter", "args": {"set": {"op": "Neighbors", "args": {"of": "<India>", "level": "country"}}, "pred": PREDICATE_DAGS["coastal"]}}),
    ("G8", "states that border both Karnataka and Kerala", IN,
     {"op": "Common", "args": {"a": {"op": "Neighbors", "args": {"of": "<Karnataka>", "level": "state"}},
                               "b": {"op": "Neighbors", "args": {"of": "<Kerala>", "level": "state"}}}}),
    ("G9", "riverside districts of Karnataka", KA,
     {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": "<Karnataka>", "level": "district"}}, "pred": PREDICATE_DAGS["on_river"]}}),
    ("G9", "mountain districts of Uttarakhand", IN,
     {"op": "Filter", "args": {"set": {"op": "Children", "args": {"of": "<Uttarakhand>", "level": "district"}}, "pred": PREDICATE_DAGS["in_mountains"]}}),
    ("Along", "5 km along the Ganges", IN, {"op": "Along", "args": {"line": "<ne-river-Q5089>", "distance_m": 5000}}),
]


def resolve(node, view):
    if isinstance(node, str) and node.startswith("<"):
        name = node[1:-1]
        if name.startswith("ne-"):
            return {"op": "Resolve", "args": {"name": name, "source": "overture", "id": name}}
        c = get_store().search(name, fuzzy=False, limit=1, view=view)
        if not c:
            raise ValueError(f"{name!r} not found")
        return {"op": "Resolve", "args": {"name": name, "source": "overture", "id": c[0].id}}
    if isinstance(node, dict):
        return {k: resolve(v, view) for k, v in node.items()}
    return node


def main() -> None:
    ex = Executor()
    out = []
    for i, (gap, q, view, src) in enumerate(RECORDS):
        dag = resolve(src, view)
        errors = validate(dag)
        if errors:
            raise RuntimeError(f"{q!r}: {errors}")
        res = ex.execute(dag, with_geometry=False, view=view)
        if not res.ok:
            raise RuntimeError(f"{q!r}: {res.error}")
        rec = {"id": f"o{i + 1:03d}", "query": q, "gap": gap, "view": view, "dag": dag, "expected_ids": res.ids,
               "expected_names": sorted({f.name for f in res.features if f.name})[:40]}
        if res.kind == "geometry":
            rec["expected_geometry"] = geometry_summary(ex.execute(dag, with_geometry=True, view=view))
        out.append(rec)
        print(f"{rec['id']} {gap:5s} {q!r:55s} n={len(res.ids)} {rec['expected_names'][:6]}{' geometry ' + str(rec.get('expected_geometry')) if res.kind == 'geometry' else ''}")
    (GOLD_DIR / "ops.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))


if __name__ == "__main__":
    main()
