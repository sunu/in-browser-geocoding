"""Measure the world web data (plan-008 phase 0).

Usage: GEOPARSE_SCOPE=world uv run python scripts/measure_world.py [--web data/build-world/web]

Reads geoparse.duckdb and the flat export (scripts/export_web.py data --out ...). Writes test layouts to
<web>/_measure and the results to reports/world-data.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import duckdb

from geoparse.config import REPO_ROOT, build_dir

RG = 10000


def mb(n: float) -> float:
    return round(n / 1e6, 2)


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*.parquet"))


def simplification(con) -> list[dict]:
    rows = con.execute("""
        SELECT subtype, count(*), sum(octet_length(ST_AsWKB(geometry))), sum(octet_length(ST_AsWKB(gs))),
               sum(ST_NPoints(geometry)), sum(ST_NPoints(gs))
        FROM areas GROUP BY 1 ORDER BY 3 DESC""").fetchall()
    return [{"subtype": s, "areas": n, "raw_wkb_mb": mb(r), "simplified_wkb_mb": mb(g), "ratio": round(r / g, 1),
             "raw_points": int(rp), "simplified_points": int(gp)} for s, n, r, g, rp, gp in rows]


def by_country(con, web: Path, out: Path) -> dict:
    con.execute(f"CREATE TEMP TABLE dv AS SELECT * FROM read_parquet('{web / 'divisions.parquet'}')")
    world = "ST_MakeEnvelope(-180, -90, 180, 90)"
    jobs = {
        "divisions": f"""SELECT *, country AS c FROM dv
                         ORDER BY subtype, ST_Hilbert(ST_Point(lon, lat), ST_Extent({world}))""",
        "areas": f"""SELECT a.*, d.country AS c FROM read_parquet('{web / 'areas.parquet'}') a JOIN dv d USING (id)
                     ORDER BY a.subtype, ST_Hilbert(ST_Point((xmin + xmax) / 2, (ymin + ymax) / 2), ST_Extent({world}))""",
        "layer_dist": f"""SELECT l.*, d.country AS c FROM read_parquet('{web / 'layer_dist.parquet'}') l JOIN dv d USING (id)
                          ORDER BY l.id""",
    }
    for name, sql in jobs.items():
        con.execute(f"""COPY ({sql}) TO '{out / name}'
                        (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {RG}, PARTITION_BY (c), OVERWRITE_OR_IGNORE)""")
    sizes: dict[str, dict[str, int]] = {}
    for name in jobs:
        for d in (out / name).iterdir():
            sizes.setdefault(d.name.removeprefix("c="), {})[name] = dir_size(d)
    rows = sorted(({"country": c, **{k: mb(v) for k, v in s.items()}, "total_mb": mb(sum(s.values()))}
                   for c, s in sizes.items()), key=lambda r: -r["total_mb"])
    totals = [r["total_mb"] for r in rows]
    return {
        "countries": len(rows),
        "over_25_mb": sum(t > 25 for t in totals),
        "over_50_mb": sum(t > 50 for t in totals),
        "over_100_mb": sum(t > 100 for t in totals),
        "median_mb": sorted(totals)[len(totals) // 2],
        "total_mb": round(sum(totals), 1),
        "largest": rows[:20],
    }


def names_index(con, web: Path, out: Path) -> dict:
    f = out / "names.parquet"
    con.execute(f"""
        COPY (SELECT n.name_norm, n.name_nospace, n.kind, n.id, d.country, d.subtype, d.class, d.population
              FROM read_parquet('{web / 'names.parquet'}') n JOIN dv d USING (id) WHERE n.name_norm <> '' ORDER BY n.name_norm, d.population DESC NULLS LAST)
        TO '{f}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {RG})""")
    meta = con.execute(f"""
        SELECT row_group_id, any_value(stats_min_value) FILTER (WHERE path_in_schema = 'name_norm'),
               any_value(stats_max_value) FILTER (WHERE path_in_schema = 'name_norm'),
               sum(total_compressed_size), any_value(row_group_num_rows)
        FROM parquet_metadata('{f}') GROUP BY 1 ORDER BY 1""").fetchall()
    size = f.stat().st_size
    rg_bytes = sum(m[3] for m in meta)
    sample = [r[0] for r in con.execute(f"SELECT name_norm FROM '{f}' USING SAMPLE reservoir(2000 ROWS) REPEATABLE (0)").fetchall()]
    sample += ["springfield", "san jose", "victoria", "london", "paris", "mumbai", "santa maria", "saint martin"]

    def hits(pred) -> tuple[int, int]:
        m = [x for x in meta if pred(x[1], x[2])]
        return len(m), sum(x[3] for x in m)

    exact = [hits(lambda lo, hi, s=s: lo <= s <= hi) for s in sample]
    prefix = [hits(lambda lo, hi, p=s[:3]: lo[:3] <= p <= hi[:3]) for s in sample if len(s) >= 3]

    def summary(xs):
        n = sorted(x[0] for x in xs)
        b = sorted(x[1] for x in xs)
        return {"row_groups_median": n[len(n) // 2], "row_groups_p95": n[int(len(n) * 0.95)], "row_groups_max": n[-1],
                "mb_median": mb(b[len(b) // 2]), "mb_p95": mb(b[int(len(b) * 0.95)]), "mb_max": mb(b[-1])}

    empty = con.execute(f"""SELECT count(*), count(DISTINCT id) FILTER (WHERE id NOT IN (
        SELECT id FROM read_parquet('{web / 'names.parquet'}') WHERE name_norm <> ''))
        FROM read_parquet('{web / 'names.parquet'}') WHERE name_norm = ''""").fetchone()
    return {
        "empty_name_norm_rows": empty[0], "divisions_without_latin_name": empty[1],
        "file_mb": mb(size), "row_groups": len(meta), "footer_mb": mb(size - rg_bytes),
        "rows": sum(m[4] for m in meta),
        "exact_lookup": summary(exact), "prefix3_lookup": summary(prefix),
        "named_examples": {s: dict(zip(("row_groups", "bytes"), hits(lambda lo, hi, s=s: lo <= s <= hi))) for s in sample[-8:]},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", type=Path, default=build_dir() / "web")
    args = ap.parse_args()
    out = args.web / "_measure"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    con = duckdb.connect(str(build_dir() / "geoparse.duckdb"), read_only=True)
    con.execute("LOAD spatial; SET geometry_always_xy = true;")
    res = {
        "flat_files_mb": {f.name: mb(f.stat().st_size) for f in sorted(args.web.glob("*.parquet"))},
        "simplification": simplification(con),
        "by_country": by_country(con, args.web, out),
        "names_index": names_index(con, args.web, out),
    }
    p = REPO_ROOT / "reports" / "world-data.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
