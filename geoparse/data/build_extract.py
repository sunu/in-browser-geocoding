"""Build the local India extract as GeoParquet.

Usage: uv run python -m geoparse.data.build_extract [--skip-overture]

Outputs (in the build directory):
  divisions.parquet      one row per Overture division (point geometry and attributes)
  division_area.parquet  one area polygon per division (land polygon if there is one)
  coastline.parquet      Natural Earth 10m coastline lines, clipped to the bbox
Also writes geoparse/data/lexicon.json.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import duckdb
import yaml

from geoparse.config import PACKAGE_DIR, build_dir, load_config


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2'; SET geometry_always_xy = true;")
    return con


def build_divisions(con, cfg, out: Path) -> None:
    d = cfg["data"]
    base = f"{d['overture_s3']}/{d['overture_release']}/theme=divisions"
    xmin, ymin, xmax, ymax = d["bbox"]
    bbox_where = f"bbox.xmin < {xmax} AND bbox.xmax > {xmin} AND bbox.ymin < {ymax} AND bbox.ymax > {ymin}"
    extra = ", ".join(f"'{c}'" for c in d["extra_countries"])
    # India: all subtypes. Extra countries: only the country row.
    where = f"(country = '{d['country']}' AND {bbox_where}) OR (subtype = 'country' AND country IN ({extra}))"

    t0 = time.time()
    con.execute(f"""
        CREATE OR REPLACE TABLE divisions AS
        SELECT
            id,
            subtype,
            class,
            admin_level,
            names.primary AS name,
            coalesce(names.common['en'], names.primary) AS name_en,
            list_distinct(list_filter(
                [r.value FOR r IN coalesce(names.rules, [])
                 IF r.language IS NULL OR r.language = 'en'],
                lambda x: x IS NOT NULL)) AS alt_names,
            country,
            region,
            parent_division_id AS parent_id,
            list_distinct(flatten([[h.division_id FOR h IN hs] FOR hs IN coalesce(hierarchies, [])])) AS ancestors,
            population,
            wikidata,
            local_type['en'] AS local_type,
            geometry
        FROM read_parquet('{base}/type=division/*')
        WHERE {where}
    """)
    print(f"divisions: {con.execute('SELECT count(*) FROM divisions').fetchone()[0]} rows, {time.time() - t0:.1f}s")

    t0 = time.time()
    # One area per division. Prefer the land polygon. The extra countries keep the land polygon too.
    con.execute(f"""
        CREATE OR REPLACE TABLE division_area AS
        SELECT division_id, subtype, is_land, is_territorial, geometry
        FROM (
            SELECT a.*, row_number() OVER (
                PARTITION BY a.division_id ORDER BY a.is_land DESC, a.is_territorial ASC) AS rn
            FROM read_parquet('{base}/type=division_area/*') a
            WHERE ({where})
        )
        WHERE rn = 1 AND division_id IN (SELECT id FROM divisions)
    """)
    print(f"division_area: {con.execute('SELECT count(*) FROM division_area').fetchone()[0]} rows, {time.time() - t0:.1f}s")

    con.execute(f"COPY divisions TO '{out / 'divisions.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    con.execute(f"COPY division_area TO '{out / 'division_area.parquet'}' (FORMAT parquet, COMPRESSION zstd)")


def build_places(con, cfg, out: Path) -> None:
    """Slim Overture places extract (plan-004 section 2). One row per place, sorted by Hilbert curve.

    cats: the basic category plus every level of the taxonomy hierarchy, for category matching.
    """
    d = cfg["data"]
    src = f"{d['overture_s3']}/{d['overture_release']}/theme=places/type=place/*"
    xmin, ymin, xmax, ymax = d["bbox"]
    t0 = time.time()
    con.execute(f"""
        COPY (
            SELECT id, names.primary AS name, basic_category,
                   list_distinct(list_filter(list_concat([basic_category], coalesce(taxonomy.hierarchy, [])),
                                             lambda x: x IS NOT NULL)) AS cats,
                   confidence, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
            FROM read_parquet('{src}')
            WHERE bbox.xmin < {xmax} AND bbox.xmax > {xmin} AND bbox.ymin < {ymax} AND bbox.ymax > {ymin}
            ORDER BY ST_Hilbert(geometry, ST_Extent(ST_MakeEnvelope({xmin}, {ymin}, {xmax}, {ymax})))
        ) TO '{out / 'places.parquet'}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)
    """)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out / 'places.parquet'}')").fetchone()[0]
    print(f"places: {n} rows, {time.time() - t0:.1f}s")


def build_coastline(con, cfg, out: Path) -> None:
    d = cfg["data"]
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    zip_path = raw / "ne_10m_coastline.zip"
    if not zip_path.exists():
        print("downloading Natural Earth coastline")
        req = urllib.request.Request(d["natural_earth_coastline"], headers={"User-Agent": "geoparse-build/0.1"})
        with urllib.request.urlopen(req) as r, zip_path.open("wb") as f:
            f.write(r.read())
    xmin, ymin, xmax, ymax = d["bbox"]
    con.execute(f"""
        CREATE OR REPLACE TABLE coastline AS
        SELECT ST_SetCRS(ST_Intersection(geom, ST_MakeEnvelope({xmin}, {ymin}, {xmax}, {ymax})), 'OGC:CRS84') AS geometry
        FROM ST_Read('/vsizip/{zip_path}/ne_10m_coastline.shp')
        WHERE ST_Intersects(geom, ST_MakeEnvelope({xmin}, {ymin}, {xmax}, {ymax}))
    """)
    print(f"coastline: {con.execute('SELECT count(*) FROM coastline').fetchone()[0]} lines")
    con.execute(f"COPY coastline TO '{out / 'coastline.parquet'}' (FORMAT parquet, COMPRESSION zstd)")


def build_lexicon(con, out: Path) -> None:
    src = yaml.safe_load((PACKAGE_DIR / "data" / "lexicon_src.yaml").read_text())
    divs = con.execute(f"""
        SELECT id, subtype, region, country FROM read_parquet('{out / 'divisions.parquet'}')
        WHERE subtype IN ('country', 'region')
    """).fetchall()
    by_code = {}
    for id_, subtype, region, country in divs:
        if subtype == "region" and region:
            by_code[region] = id_
        if subtype == "country":
            by_code[country] = id_
    lexicon = {}
    for key, entry in src.items():
        members = [{"code": c, "id": by_code.get(c)} for c in entry["members"]]
        lexicon[key] = {
            "aliases": entry["aliases"],
            "members": members,
            "notes": entry.get("notes", ""),
        }
    path = PACKAGE_DIR / "data" / "lexicon.json"
    path.write_text(json.dumps(lexicon, indent=2) + "\n")
    missing = sum(1 for e in lexicon.values() for m in e["members"] if m["id"] is None)
    print(f"lexicon: {len(lexicon)} sets, {missing} members not in the extract")


NAME_NORM_SQL = "trim(regexp_replace(regexp_replace(lower({x}), '[^a-z0-9]+', ' ', 'g'), '\\s+', ' ', 'g'))"


def build_db(cfg, out: Path, simplify_deg: float = 0.001) -> None:
    """Build data/build/geoparse.duckdb from the GeoParquet files.

    Tables:
      divisions  attributes and point geometry
      areas      full polygon (geometry) and simplified polygon (gs) for each division
      names      normalized names for the gazetteer
      layers     derived layers: coastline, country_boundary (land border of the country)
    """
    db_path = out / "geoparse.duckdb"
    tmp = out / "geoparse.duckdb.tmp"
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.execute("INSTALL spatial; LOAD spatial; SET geometry_always_xy = true;")
    t0 = time.time()
    con.execute(f"CREATE TABLE divisions AS SELECT * FROM read_parquet('{out / 'divisions.parquet'}')")
    con.execute(f"""
        CREATE TABLE areas AS
        SELECT division_id AS id, subtype, geometry,
               ST_SimplifyPreserveTopology(geometry, {simplify_deg}) AS gs
        FROM read_parquet('{out / 'division_area.parquet'}')
    """)
    print(f"areas simplified in {time.time() - t0:.1f}s")
    nn = NAME_NORM_SQL
    con.execute(f"""
        CREATE TABLE names AS
        WITH raw AS (
            SELECT id, name AS n, 'primary' AS kind FROM divisions
            UNION ALL SELECT id, name_en, 'en' FROM divisions WHERE name_en IS NOT NULL AND name_en <> name
            UNION ALL SELECT id, unnest(alt_names), 'alt' FROM divisions
        )
        SELECT DISTINCT id, {nn.format(x='n')} AS name_norm,
               replace({nn.format(x='n')}, ' ', '') AS name_nospace, kind
        FROM raw WHERE n IS NOT NULL
    """)
    country = cfg["data"]["country"]
    con.execute(f"""
        CREATE TABLE layers AS
        SELECT 'coastline' AS name, ST_Union_Agg(geometry) AS geometry
        FROM read_parquet('{out / 'coastline.parquet'}')
        UNION ALL
        SELECT 'country_boundary', ST_Intersection(
            ST_Boundary((SELECT a.gs FROM areas a JOIN divisions d USING (id) WHERE d.subtype = 'country' AND d.country = '{country}')),
            ST_Buffer((SELECT ST_Union_Agg(a.gs) FROM areas a JOIN divisions d USING (id) WHERE d.subtype = 'country' AND d.country <> '{country}'), 0.05))
    """)
    # Distance (degrees) from each admin area to the layers. The predicates compare it with the policy
    # tolerance at query time. Neighborhoods are not included (too many, and rarely used with predicates).
    t1 = time.time()
    con.execute("""
        CREATE TABLE layer_dist AS
        SELECT a.id,
               ST_Distance(a.gs, (SELECT geometry FROM layers WHERE name = 'coastline')) AS coastline,
               ST_Distance(a.gs, (SELECT geometry FROM layers WHERE name = 'country_boundary')) AS country_boundary
        FROM areas a WHERE a.subtype IN ('country', 'region', 'county', 'locality')
    """)
    print(f"layer distances in {time.time() - t1:.1f}s")
    con.execute("CREATE INDEX layer_dist_id ON layer_dist (id)")
    if (out / "places.parquet").exists():
        t1 = time.time()
        con.execute(f"CREATE TABLE places AS SELECT * FROM read_parquet('{out / 'places.parquet'}')")
        print(f"places table in {time.time() - t1:.1f}s")
    con.execute("CREATE INDEX names_norm ON names (name_norm)")
    con.execute("CREATE INDEX names_nospace ON names (name_nospace)")
    con.execute("CREATE INDEX div_id ON divisions (id)")
    con.execute("CREATE INDEX area_id ON areas (id)")
    con.close()
    tmp.rename(db_path)
    print(f"geoparse.duckdb: {db_path.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-overture", action="store_true", help="Keep the existing Overture files.")
    ap.add_argument("--db-only", action="store_true", help="Only build geoparse.duckdb from the existing files.")
    ap.add_argument("--skip-places", action="store_true", help="Keep the existing places file.")
    args = ap.parse_args()
    cfg = load_config()
    out = build_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    if not args.db_only:
        con = connect()
        if not args.skip_overture:
            build_divisions(con, cfg, out)
        if not args.skip_places:
            build_places(con, cfg, out)
        build_coastline(con, cfg, out)
        build_lexicon(con, out)
        con.close()
    build_db(cfg, out)
    for f in sorted(list(out.glob("*.parquet")) + list(out.glob("*.duckdb"))):
        print(f"{f.name:24s} {f.stat().st_size / 1e6:8.1f} MB")


if __name__ == "__main__":
    main()
