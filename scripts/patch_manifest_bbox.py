"""Add the bbox of each country (extent of its division points) to an existing manifest.json (plan-019).

Usage: uv run python scripts/patch_manifest_bbox.py data/build-world/web/2026-10-21.0
New exports write the bbox (geoparse/data/web_layout.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

root = Path(sys.argv[1])
m = json.loads((root / "manifest.json").read_text())
rows = duckdb.connect().execute(f"""
    SELECT country, min(lon), min(lat), max(lon), max(lat)
    FROM read_parquet('{root}/country=*/divisions.parquet', hive_partitioning = false) GROUP BY 1""").fetchall()
for c, *b in rows:
    m["countries"][c]["bbox"] = [round(v, 5) for v in b]
assert all("bbox" in v for v in m["countries"].values())
(root / "manifest.json").write_text(json.dumps(m, indent=1))
print(f"{len(rows)} countries")
