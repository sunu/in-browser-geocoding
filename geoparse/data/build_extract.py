"""Build the local India extract (or the world extract) as GeoParquet.

Usage: uv run python -m geoparse.data.build_extract [--skip-overture]
       GEOPARSE_SCOPE=world uv run python -m geoparse.data.build_extract   # data/build-world

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
import numpy as np
import shapely
import yaml

from geoparse.config import PACKAGE_DIR, build_dir, load_config, scope
from geoparse.execute.data import norm_name


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2'; SET geometry_always_xy = true;")
    return con


def build_divisions(con, cfg, out: Path) -> None:
    d = cfg["data"]
    base = f"{d['overture_s3']}/{d['overture_release']}/theme=divisions"
    if scope(cfg) == "world":
        where = "true"
    else:
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

    con.execute(f"COPY divisions TO '{out / 'divisions.parquet'}' (FORMAT parquet, COMPRESSION zstd)")

    t0 = time.time()
    # One area per division. Prefer the land polygon. The extra countries keep the land polygon too.
    # Two passes: the window function reads no geometry, so the world build stays in memory.
    src = f"read_parquet('{base}/type=division_area/*')"
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE area_pick AS
        SELECT id FROM (
            SELECT id, division_id, row_number() OVER (
                PARTITION BY division_id ORDER BY is_land DESC, is_territorial ASC) AS rn
            FROM {src} WHERE ({where})
        )
        WHERE rn = 1 AND division_id IN (SELECT id FROM divisions)
    """)
    con.execute(f"""
        COPY (
            SELECT division_id, subtype, is_land, is_territorial, geometry
            FROM {src} WHERE ({where}) AND id IN (SELECT id FROM area_pick)
        ) TO '{out / 'division_area.parquet'}' (FORMAT parquet, COMPRESSION zstd)
    """)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out / 'division_area.parquet'}')").fetchone()[0]
    print(f"division_area: {n} rows, {time.time() - t0:.1f}s")


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
    xmin, ymin, xmax, ymax = [-180.0, -90.0, 180.0, 90.0] if scope(cfg) == "world" else d["bbox"]
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


LAYER_DIST_SUBTYPES = ("country", "dependency", "region", "county", "localadmin", "locality")
# World build: distances above this value (degrees) are stored as this value. All tolerances are smaller.
LAYER_DIST_CAP = 0.5


def _chunks(geom, n: int = 64) -> list:
    """Split lines into short pieces, so that the STRtree can index them."""
    out = []
    for part in shapely.get_parts(geom):
        c = shapely.get_coordinates(part)
        for i in range(0, max(len(c) - 1, 1), n - 1):
            if len(c[i:i + n]) >= 2:
                out.append(shapely.linestrings(c[i:i + n]))
    return out


def build_world_layers(con, out: Path) -> None:
    """World layers: full coastline, and all land borders between countries (one layer).

    layer_dist is computed with an STRtree of short line pieces. The SQL version compares each area with
    the full layer and is too slow for the world.
    """
    coast = [shapely.from_wkb(bytes(w)) for (w,) in con.execute(
        f"SELECT ST_AsWKB(geometry) FROM read_parquet('{out / 'coastline.parquet'}')").fetchall()]
    coast_line = shapely.multilinestrings([p for g in coast for p in shapely.get_parts(g)])

    rows = con.execute("""
        SELECT d.country, ST_AsWKB(a.gs) FROM areas a JOIN divisions d USING (id)
        WHERE d.subtype IN ('country', 'dependency')""").fetchall()
    polys = [shapely.from_wkb(bytes(w)) for _, w in rows]
    tree = shapely.STRtree(polys)
    borders = []
    for i, p in enumerate(polys):
        near = [j for j in tree.query(p, predicate="dwithin", distance=0.05) if j != i]
        if not near:
            continue
        x0, y0, x1, y1 = p.bounds
        clip = shapely.box(x0 - 0.1, y0 - 0.1, x1 + 0.1, y1 + 0.1)
        others = shapely.union_all([shapely.clip_by_rect(polys[j], *clip.bounds) for j in near])
        b = shapely.intersection(shapely.boundary(p), shapely.buffer(others, 0.05))
        borders += [g for g in shapely.get_parts(b) if g.geom_type in ("LineString", "MultiLineString")]
    border_line = shapely.multilinestrings([p for g in borders for p in shapely.get_parts(g)])

    con.execute("CREATE TABLE layers (name VARCHAR, geometry GEOMETRY)")
    for name, g in (("coastline", coast_line), ("country_boundary", border_line)):
        con.execute("INSERT INTO layers VALUES (?, ST_GeomFromWKB(?))", [name, shapely.to_wkb(g)])

    trees = {name: shapely.STRtree(_chunks(g)) for name, g in (("coastline", coast_line), ("country_boundary", border_line))}
    subtypes = ", ".join(f"'{s}'" for s in LAYER_DIST_SUBTYPES)
    con.execute("CREATE TABLE layer_dist (id VARCHAR, coastline DOUBLE, country_boundary DOUBLE)")
    cur = con.cursor().execute(f"SELECT id, ST_AsWKB(gs) FROM areas WHERE subtype IN ({subtypes})")
    while batch := cur.fetchmany(50000):
        ids = np.array([r[0] for r in batch], dtype=object)
        geoms = shapely.from_wkb([bytes(r[1]) for r in batch])
        cols = {"id": ids}
        for name, t in trees.items():
            d = np.full(len(batch), LAYER_DIST_CAP)
            (idx, _), dist = t.query_nearest(geoms, max_distance=LAYER_DIST_CAP, return_distance=True, all_matches=False)
            d[idx] = np.minimum(d[idx], dist)
            cols[name] = d
        con.register("ld_batch", cols)
        con.execute("INSERT INTO layer_dist SELECT id, coastline, country_boundary FROM ld_batch")
        con.unregister("ld_batch")
    print(f"layer_dist: {con.execute('SELECT count(*) FROM layer_dist').fetchone()[0]} rows")


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
    t1 = time.time()
    # The name key comes from geoparse.execute.data.norm_name (also used at query time).
    con.create_function("norm_name", norm_name, ["VARCHAR"], "VARCHAR", side_effects=False)
    con.execute("""
        CREATE TEMP TABLE raw_names AS
        SELECT id, name AS n, 'primary' AS kind FROM divisions
        UNION ALL SELECT id, name_en, 'en' FROM divisions WHERE name_en IS NOT NULL AND name_en <> name
        UNION ALL SELECT id, unnest(alt_names), 'alt' FROM divisions
    """)
    con.execute("CREATE TEMP TABLE name_keys AS SELECT n, norm_name(n) AS k FROM (SELECT DISTINCT n FROM raw_names WHERE n IS NOT NULL)")
    con.execute("""
        CREATE TABLE names AS
        SELECT DISTINCT r.id, k.k AS name_norm, replace(k.k, ' ', '') AS name_nospace, r.kind
        FROM raw_names r JOIN name_keys k USING (n) WHERE k.k <> ''
    """)
    print(f"names: {con.execute('SELECT count(*) FROM names').fetchone()[0]} rows, {time.time() - t1:.1f}s")
    t1 = time.time()
    if scope(cfg) == "world":
        build_world_layers(con, out)
    else:
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
        con.execute("""
            CREATE TABLE layer_dist AS
            SELECT a.id,
                   ST_Distance(a.gs, (SELECT geometry FROM layers WHERE name = 'coastline')) AS coastline,
                   ST_Distance(a.gs, (SELECT geometry FROM layers WHERE name = 'country_boundary')) AS country_boundary
            FROM areas a WHERE a.subtype IN ('country', 'region', 'county', 'locality')
        """)
    print(f"layers and layer distances in {time.time() - t1:.1f}s")
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
    world = scope(cfg) == "world"
    print(f"scope: {scope(cfg)}, output: {out}")
    if not args.db_only:
        con = connect()
        if not args.skip_overture:
            build_divisions(con, cfg, out)
        # The world build has no places (plan-008). The lexicon comes from the country build.
        if not args.skip_places and not world:
            build_places(con, cfg, out)
        build_coastline(con, cfg, out)
        if not world:
            build_lexicon(con, out)
        con.close()
    build_db(cfg, out)
    for f in sorted(list(out.glob("*.parquet")) + list(out.glob("*.duckdb"))):
        print(f"{f.name:24s} {f.stat().st_size / 1e6:8.1f} MB")


if __name__ == "__main__":
    main()
