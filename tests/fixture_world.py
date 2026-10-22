"""A small synthetic world with the same schema as geoparse.duckdb.

Layout (lon, lat). Country Testland (TL) is the box 76..80 x 10..14.

    lat 14 +---------+---------+---------+---------+---------+
           |   W3    |   W4    |   E3    |   E4    |         |
    lat 12 +---------+---------+---------+---------+ Other-  |
           |   W1    |   W2    |   E1    |   E2    | land    |
    lat 10 +---------+---------+---------+---------+---------+
          76        77        78        79        80        82
    coast at lon 76         state Westa = W*, state Easta = E*

Alpha City is a city in W1 (with area), Gamma Nagar is a macrohood in Alpha City.
Beta Town is a town in E4 (point only). The coastline is the line lon = 76.
The land border of Testland is the line lon = 80.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

COUNTRY = "TL"

LEXICON = {
    "west_zone": {"aliases": ["west zone"], "members": [{"code": "TL-WA", "id": "st_w"}], "notes": ""},
    "all_states": {"aliases": ["all states"], "members": [{"code": "TL-WA", "id": "st_w"}, {"code": "TL-EA", "id": "st_e"}], "notes": ""},
}


def box(x0, y0, x1, y1):
    return f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"


def rows():
    # id, subtype, class, name, country, region, ancestors, population, polygon or None, point
    out = [
        ("c_tl", "country", None, "Testland", COUNTRY, None, ["c_tl"], 50_000_000, box(76, 10, 80, 14), (78, 12)),
        ("c_ot", "country", None, "Otherland", "OT", None, ["c_ot"], 1_000_000, box(80, 10, 82, 14), (81, 12)),
        ("st_w", "region", None, "Westa", COUNTRY, "TL-WA", ["c_tl", "st_w"], 30_000_000, box(76, 10, 78, 14), (77, 12)),
        ("st_e", "region", None, "Easta", COUNTRY, "TL-EA", ["c_tl", "st_e"], None, box(78, 10, 80, 14), (79, 12)),
    ]
    dists = {
        "W1": ("st_w", (76, 10, 77, 12), 4_000_000), "W2": ("st_w", (77, 10, 78, 12), 1_000_000),
        "W3": ("st_w", (76, 12, 77, 14), 2_500_000), "W4": ("st_w", (77, 12, 78, 14), 500_000),
        "E1": ("st_e", (78, 10, 79, 12), None), "E2": ("st_e", (79, 10, 80, 12), 800_000),
        "E3": ("st_e", (78, 12, 79, 14), 3_000_000), "E4": ("st_e", (79, 12, 80, 14), 900_000),
    }
    for name, (st, (x0, y0, x1, y1), pop) in dists.items():
        out.append((f"d_{name.lower()}", "county", None, name, COUNTRY, "TL-WA" if st == "st_w" else "TL-EA",
                    ["c_tl", st, f"d_{name.lower()}"], pop, box(x0, y0, x1, y1), ((x0 + x1) / 2, (y0 + y1) / 2)))
    out += [
        ("l_alpha", "locality", "city", "Alpha City", COUNTRY, "TL-WA", ["c_tl", "st_w", "d_w1", "l_alpha"], 2_000_000,
         box(76.4, 10.9, 76.6, 11.1), (76.5, 11.0)),
        ("l_beta", "locality", "town", "Beta Town", COUNTRY, "TL-EA", ["c_tl", "st_e", "d_e4", "l_beta"], 50_000, None, (79.5, 13.5)),
        ("m_gamma", "macrohood", None, "Gamma Nagar", COUNTRY, "TL-WA", ["c_tl", "st_w", "d_w1", "l_alpha", "m_gamma"], None,
         box(76.45, 10.95, 76.5, 11.0), (76.47, 10.97)),
    ]
    return out


def build(path: Path) -> Path:
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    con.execute("INSTALL spatial; LOAD spatial; SET geometry_always_xy = true;")
    con.execute("""
        CREATE TABLE divisions (id VARCHAR, subtype VARCHAR, class VARCHAR, admin_level INTEGER, name VARCHAR,
            name_en VARCHAR, alt_names VARCHAR[], country VARCHAR, region VARCHAR, parent_id VARCHAR,
            ancestors VARCHAR[], population INTEGER, wikidata VARCHAR, local_type VARCHAR, geometry GEOMETRY('OGC:CRS84'))
    """)
    con.execute("CREATE TABLE areas (id VARCHAR, subtype VARCHAR, geometry GEOMETRY('OGC:CRS84'), gs GEOMETRY('OGC:CRS84'))")
    for id_, subtype, cls, name, country, region, anc, pop, poly, (x, y) in rows():
        con.execute("INSERT INTO divisions VALUES (?, ?, ?, NULL, ?, ?, [], ?, ?, ?, ?, ?, NULL, NULL, ST_SetCRS(ST_Point(?, ?), 'OGC:CRS84'))",
                    [id_, subtype, cls, name, name, country, region, anc[-2] if len(anc) > 1 else None, anc, pop, x, y])
        if poly:
            con.execute("INSERT INTO areas VALUES (?, ?, ST_SetCRS(ST_GeomFromText(?), 'OGC:CRS84'), ST_SetCRS(ST_GeomFromText(?), 'OGC:CRS84'))",
                        [id_, subtype, poly, poly])
    con.execute("""
        CREATE TABLE names AS
        SELECT id, lower(name) AS name_norm, replace(lower(name), ' ', '') AS name_nospace, 'primary' AS kind FROM divisions
    """)
    con.execute("CREATE TABLE layers (name VARCHAR, geometry GEOMETRY('OGC:CRS84'))")
    con.execute("INSERT INTO layers VALUES ('coastline', ST_SetCRS(ST_GeomFromText('MULTILINESTRING((76 10, 76 14))'), 'OGC:CRS84'))")
    con.execute("INSERT INTO layers VALUES ('country_boundary', ST_SetCRS(ST_GeomFromText('MULTILINESTRING((80 10, 80 14))'), 'OGC:CRS84'))")
    con.close()
    return path
