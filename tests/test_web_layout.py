from __future__ import annotations

import json

import duckdb

from geoparse.data.translit import translit_keys
from geoparse.data.web_layout import assign_shards, export_country_layout, verify_country_layout
from tests import fixture_world


def test_assign_shards_keeps_a_key_in_one_shard():
    con = duckdb.connect()
    keys = ["a"] * 3 + ["b"] * 5 + ["c"] + ["d"] * 4 + ["e"] * 2
    con.execute("CREATE TEMP TABLE k AS SELECT unnest(?) AS key, generate_subscripts(?, 1) - 1 AS rn", [keys, keys])
    n = assign_shards(con, "k", 4)
    shards = con.execute("SELECT key, list(DISTINCT shard) FROM k GROUP BY key ORDER BY key").fetchall()
    assert all(len(s) == 1 for _, s in shards)
    assert [s[0] for _, s in shards] == sorted(s[0] for _, s in shards)
    assert n == len({s[0] for _, s in shards}) and n > 1
    assert con.execute("SELECT min(shard), max(shard) FROM k").fetchone() == (0, n - 1)


def test_country_layout_matches_tables(tmp_path):
    path = fixture_world.build(tmp_path / "world.duckdb")
    con = duckdb.connect(str(path))
    con.execute("LOAD spatial")
    con.execute("CREATE TABLE layer_dist AS SELECT id, 0.1 AS coastline, 0.2 AS country_boundary FROM areas")
    # A division with no country goes to country=XX.
    con.execute("""INSERT INTO divisions (id, subtype, name, name_en, ancestors, geometry)
                   VALUES ('x1', 'locality', 'Nowhere', 'Nowhere', ['x1'], ST_SetCRS(ST_Point(0, 0), 'OGC:CRS84'))""")
    con.execute("INSERT INTO names VALUES ('x1', 'nowhere', 'nowhere', 'primary')")
    root = export_country_layout(con, tmp_path / "web", "r1")
    assert verify_country_layout(con, root) == []
    m = json.loads((root / "manifest.json").read_text())
    assert set(m["countries"]) == {"TL", "OT", "XX"}
    assert m["names"]["shards"] == 1
    shard = f"{root}/names/0000.parquet"
    row = con.execute(f"""SELECT s.kind, s.has_area, a.name FROM '{shard}' s
                          JOIN '{root}/global/admin.parquet' a ON a.n = s.region_n WHERE s.key = 'alphacity'""").fetchone()
    assert row == ("primary", True, "Westa")
    assert con.execute(f"SELECT count(*) FROM '{shard}' WHERE key = 'alpha city'").fetchone()[0] == 0
    n_to_id = con.execute(f"""SELECT d.id FROM '{shard}' s JOIN '{root}/country=TL/*divisions.parquet' d USING (n)
                              WHERE s.key = 'alphacity'""").fetchone()[0]
    assert n_to_id == con.execute("SELECT id FROM divisions WHERE name = 'Alpha City'").fetchone()[0]


def test_translit_keys():
    assert translit_keys("Москва", "RU") == ["moskva"]
    assert translit_keys("Київ", "UA") == ["kyiv"]
    assert translit_keys("Θεσσαλονίκη", "GR") == ["thessaloniki"]
    assert translit_keys("厦门市", "CN") == ["xiamenshi", "xiamen"]
    assert translit_keys("東京都", "JP") == []
    assert translit_keys("Delhi", "IN") == []
