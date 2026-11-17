"""Export the files that the browser version needs (plan-007 section 3.2).

Usage:
  uv run python scripts/export_web.py bundle   # web/public/bundle.json
  uv run python scripts/export_web.py data     # web/public/data/*.parquet (from geoparse.duckdb)
  GEOPARSE_SCOPE=world uv run python scripts/export_web.py data --out data/build-world/web
  GEOPARSE_SCOPE=world uv run python scripts/export_web.py data --layout country --out data/build-world/web
  GEOPARSE_SCOPE=world uv run python scripts/export_web.py poi --out data/build-world/web   # only the poi/ files
  uv run python scripts/export_web.py data --layout country --out web/public/countries   # India, for the parity checks

The Python package stays the single source of truth for templates, options, and policy.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import duckdb
import yaml

from geoparse.config import PACKAGE_DIR, REPO_ROOT, build_dir, load_config
from geoparse.data.web_layout import export_country_layout, verify_country_layout
from geoparse.decisions.functions import INSTRUCTIONS, IS_SUBQUERY_CRITERIA, NONE_OPTION, SOURCE_OPTIONS
from geoparse.dsl.schema import CATALOG, DIRECTION_MODES, LAYERS, PREDICATE_DAGS, SOURCES
from geoparse.options import categories, lexicon, options
from geoparse.parse.pipeline import LEADING_FILLERS
from geoparse.templates.model import load_families

WEB = REPO_ROOT / "web" / "public"


def export_bundle() -> None:
    fams = load_families()
    templates = {}
    for f in fams.values():
        for t in f.templates:
            templates[t.id] = {
                "id": t.id, "family": t.family, "description": t.description, "examples": t.examples,
                "slots": {k: v.model_dump() for k, v in t.slots.items()}, "dag": t.dag_json,
            }
    catalog = {name: {"args": [{"name": a.name, "types": list(a.types), "required": a.required,
                                "choices_ref": a.choices_ref} for a in spec.args], "out": spec.out}
               for name, spec in CATALOG.items()}
    aliases = yaml.safe_load((PACKAGE_DIR / "data" / "name_aliases.yaml").read_text()) or {}
    bundle = {
        "version": time.strftime("%Y-%m-%d %H:%M"),
        "config": load_config(),
        "families": {k: {"id": k, "description": v.description} for k, v in fams.items()},
        "templates": templates,
        "options": options(),
        "categories": categories(),
        "lexicon": lexicon(),
        "aliases": {str(k): str(v) for k, v in aliases.items()},
        "instructions": INSTRUCTIONS,
        "is_subquery_criteria": IS_SUBQUERY_CRITERIA,
        "none_option": NONE_OPTION,
        "source_options": SOURCE_OPTIONS,
        "predicate_dags": PREDICATE_DAGS,
        "catalog": catalog,
        "layers": LAYERS,
        "direction_modes": DIRECTION_MODES,
        "sources": SOURCES,
        "leading_fillers": LEADING_FILLERS,
    }
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False))
    print(f"bundle.json: {(WEB / 'bundle.json').stat().st_size / 1e3:.0f} kB, {len(templates)} templates")


def export_data(simplify_out: float, out: Path) -> None:
    """Parquet files for DuckDB-WASM. Geometry as WKB blobs (the WASM engine is DuckDB 1.5)."""
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(build_dir() / "geoparse.duckdb"), read_only=True)
    con.execute("LOAD spatial; SET geometry_always_xy = true;")
    jobs = {
        # Loaded into memory at start-up (small).
        "divisions.parquet": """SELECT id, subtype, class, name, name_en, country, region, ancestors, population,
                                       ST_X(geometry) AS lon, ST_Y(geometry) AS lat FROM divisions ORDER BY id""",
        "names.parquet": "SELECT id, name_norm, name_nospace, kind FROM names ORDER BY name_norm",
        "layers.parquet": "SELECT name, ST_AsWKB(geometry) AS wkb FROM layers",
        "layer_dist.parquet": "SELECT * FROM layer_dist ORDER BY id",
        # Read with HTTP range requests.
        "areas.parquet": f"""SELECT id, subtype, ST_AsWKB(gs) AS gs_wkb,
                                    ST_XMin(gs) AS xmin, ST_YMin(gs) AS ymin, ST_XMax(gs) AS xmax, ST_YMax(gs) AS ymax
                             FROM areas ORDER BY id""",
        "places.parquet": "SELECT id, name, basic_category, cats, confidence, lon, lat FROM places",
    }
    if not con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'places'").fetchone()[0]:
        del jobs["places.parquet"]
    for name, sql in jobs.items():
        t0 = time.time()
        rg = 10000 if name in ("areas.parquet", "places.parquet") else 100000
        con.execute(f"COPY ({sql}) TO '{out / name}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {rg})")
        print(f"{name:20s} {(out / name).stat().st_size / 1e6:8.1f} MB  {time.time() - t0:.1f}s")


def export_country(out: Path) -> None:
    con = duckdb.connect(str(build_dir() / "geoparse.duckdb"), read_only=True)
    con.execute("LOAD spatial; SET geometry_always_xy = true;")
    root = export_country_layout(con, out, load_config()["data"]["overture_release"])
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'places'").fetchone()[0]:
        # Until phase 5 (places by category), the country layout has the places file of the flat layout.
        con.execute(f"""COPY (SELECT id, name, basic_category, cats, confidence, lon, lat FROM places)
                        TO '{root / "places.parquet"}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 10000)""")
        m = json.loads((root / "manifest.json").read_text())
        m["places"] = "places.parquet"
        (root / "manifest.json").write_text(json.dumps(m, indent=1))
    add_poi(root)
    errors = verify_country_layout(con, root)
    for e in errors:
        print("ERROR", e)
    if errors:
        raise SystemExit(1)
    m = json.loads((root / "manifest.json").read_text())
    total = sum(c["total"] for c in m["countries"].values())
    print(f"{root}: {len(m['countries'])} countries {total / 1e6:.1f} MB, global {sum(m['global'].values()) / 1e6:.1f} MB,"
          f" names {m['names']['shards']} shards {m['names']['bytes'] / 1e6:.1f} MB")


def add_poi(root: Path) -> None:
    """Copy the world point datasets (plan-008 phase 5) into the layout and list them in the manifest."""
    poi = build_dir() / "poi"
    if not poi.is_dir():
        return
    (root / "poi").mkdir(exist_ok=True)
    m = json.loads((root / "manifest.json").read_text())
    m["poi"] = {}
    for name, items in load_config()["data"]["poi_datasets"].items():
        dst = root / "poi" / f"{name}.parquet"
        shutil.copyfile(poi / f"{name}.parquet", dst)
        rows = duckdb.sql(f"SELECT count(*) FROM read_parquet('{dst}')").fetchall()[0][0]
        m["poi"][name] = {"file": f"poi/{name}.parquet", "categories": items, "rows": rows, "bytes": dst.stat().st_size}
        print(f"poi/{name}.parquet {rows} rows {dst.stat().st_size / 1e6:.1f} MB")
    (root / "manifest.json").write_text(json.dumps(m, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["bundle", "data", "poi", "all"])
    ap.add_argument("--simplify", type=float, default=0.0005)
    ap.add_argument("--out", type=Path, default=WEB / "data", help="Output directory of the data files.")
    ap.add_argument("--layout", choices=["flat", "country"], default="flat",
                    help="flat: one file for each table. country: files for each country and name shards (plan-008).")
    args = ap.parse_args()
    if args.what in ("bundle", "all"):
        export_bundle()
    if args.what in ("data", "all"):
        if args.layout == "country":
            export_country(args.out)
        else:
            export_data(args.simplify, args.out)
    if args.what == "poi":
        add_poi(args.out / load_config()["data"]["overture_release"])


if __name__ == "__main__":
    main()
