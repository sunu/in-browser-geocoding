"""Country layout of the web data (plan-008 section 3.1, plan-010 section 3.1, plan-012 section 3.1).

<out>/<release>/
  manifest.json
  global/admin.parquet         attributes of countries, dependencies, regions, counties, localadmin
  global/admin_areas.parquet   polygons of countries and dependencies
  country=XX/regions.parquet   polygons of the regions of a country (named sets of states, without the country files)
  global/layers.parquet        coastline, land borders
  country=XX/divisions.parquet, areas.parquet, layer_dist.parquet
  names/index.json             first key of each shard
  names/NNNN.parquet           name shards, sorted by key (name key without spaces, Unicode code point order)

Divisions with no country go to country=XX.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import duckdb

from geoparse.execute.data import NATURAL_COUNTRY

NO_COUNTRY = "XX"
ROW_GROUP = 10000
WORLD = "ST_Extent(ST_MakeEnvelope(-180, -90, 180, 90))"
# Order of the name kinds. One row for each key and division keeps the best kind.
ADMIN_SUBTYPES = "'country', 'dependency', 'region', 'county', 'localadmin'"
KIND_RANK = "CASE kind WHEN 'primary' THEN 0 WHEN 'en' THEN 1 WHEN 'alt' THEN 2 WHEN 'common' THEN 3 ELSE 4 END"


def assign_shards(con: duckdb.DuckDBPyConnection, table: str, rows_per_shard: int) -> int:
    """Add the column `shard` to `table` (sorted by key, then rn). All rows of one key go to one shard."""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {table}_s AS
        SELECT *, min(rn // {rows_per_shard}) OVER (PARTITION BY key) AS shard0 FROM {table}
    """)
    # Shard numbers without gaps.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {table} AS
        SELECT * EXCLUDE (shard0), dense_rank() OVER (ORDER BY shard0) - 1 AS shard FROM {table}_s
    """)
    con.execute(f"DROP TABLE {table}_s")
    return con.execute(f"SELECT count(DISTINCT shard) FROM {table}").fetchone()[0]


def _copy(con, sql: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP})")


def _partitioned(con, sql: str, tmp: Path, root: Path, name: str) -> None:
    """Write `sql` (with column c) as root/country=<c>/<name>.parquet."""
    shutil.rmtree(tmp, ignore_errors=True)
    con.execute(f"""COPY ({sql}) TO '{tmp}'
                    (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP}, PARTITION_BY (c))""")
    for d in tmp.iterdir():
        files = list(d.glob("*.parquet"))
        assert len(files) == 1, (d, files)
        dest = root / f"country={d.name.removeprefix('c=')}" / f"{name}.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        files[0].rename(dest)
    shutil.rmtree(tmp)


def export_country_layout(con: duckdb.DuckDBPyConnection, out: Path, release: str, shard_bytes: int = 250_000) -> Path:
    root = out / release
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    # One thread: the same data gives the same bytes (the page uses the content hash of each file in its URL, so a
    # file with new bytes is downloaded again).
    con.execute("SET threads = 1")
    t0 = time.time()
    # n: integer id of a division in the web data (UUIDs do not compress). The country files map n to id. The natural
    # features (NATURAL_COUNTRY) come last, so that the n of the other countries do not change (cached country files
    # stay valid).
    # Wikidata populations (build_extract.add_population); databases built before it have no column.
    wd = "wd_population" if con.execute("""SELECT count(*) FROM information_schema.columns
        WHERE table_name = 'divisions' AND column_name = 'wd_population'""").fetchone()[0] else "NULL::INTEGER"
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE dv AS
        SELECT row_number() OVER (ORDER BY coalesce(country, '') = '{NATURAL_COUNTRY}', coalesce(country, '{NO_COUNTRY}'), subtype,
                                  ST_Hilbert(geometry, {WORLD}), id)::INTEGER - 1 AS n,
               id, subtype, class, name, name_en, coalesce(country, '{NO_COUNTRY}') AS country, region, ancestors,
               population, {wd} AS wd_population, wikidata, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM divisions
    """)

    # Files for each country.
    jobs = {
        "divisions": "SELECT *, country AS c FROM dv ORDER BY n",
        "areas": f"""SELECT a.id, a.subtype, ST_AsWKB(a.gs) AS gs_wkb, ST_XMin(a.gs) AS xmin, ST_YMin(a.gs) AS ymin,
                            ST_XMax(a.gs) AS xmax, ST_YMax(a.gs) AS ymax, d.country AS c
                     FROM areas a JOIN dv d USING (id) ORDER BY d.n""",
        "layer_dist": "SELECT l.*, d.country AS c FROM layer_dist l JOIN dv d USING (id) ORDER BY d.n",
        "regions": f"""SELECT d.n, d.id, d.subtype, ST_AsWKB(a.gs) AS gs_wkb, ST_XMin(a.gs) AS xmin, ST_YMin(a.gs) AS ymin,
                              ST_XMax(a.gs) AS xmax, ST_YMax(a.gs) AS ymax, d.country AS c
                       FROM dv d JOIN areas a USING (id) WHERE d.subtype = 'region' ORDER BY d.n""",
    }
    for name, sql in jobs.items():
        _partitioned(con, sql, out / f"_tmp_{name}", root, name)
    print(f"country files: {time.time() - t0:.1f}s")

    # Global files. admin: attributes of the admin divisions (loaded at start-up, also the ancestor names of the
    # name shards). admin_areas: polygons of countries and dependencies (queries across borders; the regions are in
    # the regions file of each country).
    _copy(con, f"""SELECT n, id, subtype, class, name, name_en, country, region, population, wd_population, lon, lat FROM dv
                   WHERE subtype IN ({ADMIN_SUBTYPES}) ORDER BY n""", root / "global" / "admin.parquet")
    _copy(con, """SELECT d.n, d.id, d.subtype, d.country, ST_AsWKB(a.gs) AS gs_wkb, ST_XMin(a.gs) AS xmin,
                         ST_YMin(a.gs) AS ymin, ST_XMax(a.gs) AS xmax, ST_YMax(a.gs) AS ymax
                  FROM dv d JOIN areas a USING (id) WHERE d.subtype IN ('country', 'dependency')
                  ORDER BY d.n""", root / "global" / "admin_areas.parquet")
    _copy(con, "SELECT name, ST_AsWKB(geometry) AS wkb FROM layers", root / "global" / "layers.parquet")
    # Layer distances of countries, dependencies and regions (predicates on them when their country is not loaded).
    _copy(con, """SELECT l.* FROM layer_dist l JOIN dv d USING (id) WHERE d.subtype IN ('country', 'dependency', 'region')
                  ORDER BY l.id""", root / "global" / "admin_layer_dist.parquet")
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'country_shapes'").fetchone()[0]:
        _copy(con, "SELECT country, ST_AsWKB(geometry) AS wkb FROM country_shapes ORDER BY country",
              root / "global" / "country_shapes.parquet")

    # Name shards. The key is the name key without spaces: two names with equal keys have equal keys without
    # spaces, so this one key gives the matches of "name_norm OR name_nospace". One row for each key and division.
    t1 = time.time()
    con.execute("""
        CREATE OR REPLACE TEMP TABLE anc AS
        SELECT x.id,
               any_value(p.n) FILTER (WHERE p.subtype = 'region') AS region_n,
               any_value(p.n) FILTER (WHERE p.subtype = 'county') AS county_n,
               any_value(coalesce(p.name_en, p.name)) FILTER (WHERE p.subtype = 'locality') AS locality_name
        FROM (SELECT id, unnest(ancestors) AS aid FROM dv) x JOIN dv p ON p.id = x.aid AND p.id <> x.id
        GROUP BY x.id
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE keys AS
        WITH best AS (SELECT name_nospace AS key, id, arg_min(kind, {KIND_RANK}) AS kind FROM names GROUP BY 1, 2)
        SELECT b.key, b.kind, d.n, d.country, d.subtype, d.class, d.population,
               round(d.lon * 100)::SMALLINT AS lon100, round(d.lat * 100)::SMALLINT AS lat100, d.name,
               nullif(d.name_en, d.name) AS name_en, a.region_n, a.county_n, a.locality_name,
               EXISTS (SELECT 1 FROM areas x WHERE x.id = b.id) AS has_area,
               row_number() OVER (ORDER BY b.key, d.population DESC NULLS LAST, d.n) - 1 AS rn
        FROM best b JOIN dv d USING (id) LEFT JOIN anc a USING (id)
    """)
    n_rows = con.execute("SELECT count(*) FROM keys").fetchone()[0]
    # Bytes for each row, from a sample written as Parquet.
    sample = out / "_names_sample.parquet"
    _copy(con, "SELECT * EXCLUDE (rn) FROM keys USING SAMPLE reservoir(200000 ROWS) REPEATABLE (0) ORDER BY key", sample)
    per_row = sample.stat().st_size / min(200000, n_rows)
    sample.unlink()
    n_shards = assign_shards(con, "keys", max(1000, int(shard_bytes / per_row)))
    tmp = out / "_tmp_names"
    shutil.rmtree(tmp, ignore_errors=True)
    con.execute(f"""COPY (SELECT * EXCLUDE (rn, shard), shard AS s FROM keys ORDER BY rn) TO '{tmp}'
                    (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP}, PARTITION_BY (s))""")
    names_dir = root / "names"
    names_dir.mkdir()
    shards = []
    for s, first, rows in con.execute("SELECT shard, min(key), count(*) FROM keys GROUP BY 1 ORDER BY 1").fetchall():
        f = names_dir / f"{s:04d}.parquet"
        next((tmp / f"s={s}").glob("*.parquet")).rename(f)
        shards.append({"file": f.name, "first": first, "rows": rows, "bytes": f.stat().st_size})
    shutil.rmtree(tmp)
    (names_dir / "index.json").write_text(json.dumps({"order": "codepoint", "shards": shards}, ensure_ascii=False))
    print(f"names: {n_rows} rows, {n_shards} shards, {time.time() - t1:.1f}s")

    # Manifest.
    countries = {}
    # bbox: extent of the division points of the country. The page uses it to bound the map-view penalty of
    # candidates in countries that it has not loaded.
    bbox = {c: [round(v, 5) for v in b] for c, *b in con.execute(
        "SELECT country, min(lon), min(lat), max(lon), max(lat) FROM dv GROUP BY 1").fetchall()}
    for d in sorted(root.glob("country=*")):
        files = {f.stem: f.stat().st_size for f in d.glob("*.parquet")}
        cc = d.name.removeprefix("country=")
        # total: the files of a full country load (the regions file is only for the named sets).
        countries[cc] = {"bytes": files, "total": sum(v for k, v in files.items() if k != "regions"), "bbox": bbox[cc]}
    manifest = {
        "release": release,
        "global": {f.name: f.stat().st_size for f in (root / "global").glob("*.parquet")},
        "countries": countries,
        "names": {"shards": len(shards), "bytes": sum(s["bytes"] for s in shards), "rows": n_rows},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return root


def verify_country_layout(con: duckdb.DuckDBPyConnection, root: Path) -> list[str]:
    """Compare the country files and the name shards with the tables in geoparse.duckdb. Returns the errors."""
    errors = []
    for name, table in (("divisions", "divisions"), ("areas", "areas"), ("layer_dist", "layer_dist")):
        n_files, n_ids = con.execute(
            f"SELECT count(*), count(DISTINCT id) FROM read_parquet('{root}/country=*/{name}.parquet')").fetchone()
        n_table = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if not n_files == n_ids == n_table:
            errors.append(f"{name}: {n_files} rows, {n_ids} ids in files, {n_table} in {table}")
    idx = json.loads((root / "names" / "index.json").read_text())["shards"]
    firsts = [s["first"] for s in idx]
    if firsts != sorted(firsts):
        errors.append("names: first keys of the shards are not sorted")
    stats = con.execute(f"""
        SELECT count(*), count(DISTINCT key),
               (SELECT count(*) FROM (SELECT key FROM read_parquet('{root}/names/*.parquet', filename = true)
                                      GROUP BY key HAVING count(DISTINCT filename) > 1))
        FROM read_parquet('{root}/names/*.parquet')""").fetchone()
    if stats[2]:
        errors.append(f"names: {stats[2]} keys are in more than one shard")
    expected = con.execute("""
        SELECT count(DISTINCT id) FROM names""").fetchone()[0]
    got = con.execute(f"SELECT count(DISTINCT n) FROM read_parquet('{root}/names/*.parquet')").fetchone()[0]
    if got != expected:
        errors.append(f"names: {got} divisions in the shards, {expected} in names")
    for s in idx:
        lo = con.execute(f"SELECT min(key) FROM '{root}/names/{s['file']}'").fetchone()[0]
        if lo != s["first"]:
            errors.append(f"names: {s['file']} starts with {lo!r}, index says {s['first']!r}")
            break
    return errors
