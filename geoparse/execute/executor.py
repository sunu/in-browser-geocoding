"""DAG executor.

Each DAG node compiles to one DuckDB SQL statement that creates a temp table (a relation).
All relations have the same columns:
  id VARCHAR, name VARCHAR, subtype VARCHAR, source VARCHAR, geometry GEOMETRY, gs GEOMETRY
`gs` is a simplified geometry for fast predicates. All geometries are in OGC:CRS84 (lon, lat).

Metric operations (buffer, centroid, metric distance) transform to the local UTM zone of the input
centroid, compute there, and transform back. Tolerance tests (coastal, neighbors) use a distance in
degrees that is an upper bound of the tolerance in meters at the latitude of the input.

The `Features` operator calls the geocoder (Photon) with an OSM tag and a bbox, then keeps the points
inside the region. All other operators run in DuckDB on the local extract.
"""
from __future__ import annotations

import json
import math
import re
import time
from typing import Any

import shapely
from pydantic import BaseModel, Field

from geoparse.config import country_policy, load_config
from geoparse.dsl.schema import CATALOG, validate
from geoparse.execute.data import NATURAL_COUNTRY, Store, get_store
from geoparse.execute.geocoder import Geocoder, PhotonGeocoder
from geoparse.options import category_leaves, choices, lexicon

M_PER_DEG = 111_320.0

MACROS = [
    "CREATE OR REPLACE TEMP MACRO crs84(g) AS ST_SetCRS(g, 'OGC:CRS84')",
    "CREATE OR REPLACE TEMP MACRO utm(g) AS 'EPSG:' || (32600 + floor((ST_X(ST_Centroid(g)) + 180) / 6) + 1)::INT",
    "CREATE OR REPLACE TEMP MACRO to_m(g, crs) AS ST_Transform(g, 'OGC:CRS84', crs)",
    "CREATE OR REPLACE TEMP MACRO from_m(g, crs) AS crs84(ST_Transform(g, crs, 'OGC:CRS84'))",
]

REL_COLS = "id, name, subtype, source, geometry, gs"


class ExecutionError(RuntimeError):
    pass


class Feature(BaseModel):
    id: str | None
    name: str | None
    subtype: str | None
    source: str | None
    geometry: dict[str, Any] | None


class Result(BaseModel):
    ok: bool
    kind: str = "set"  # set or geometry
    features: list[Feature] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list)
    error: str | None = None
    sql: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def geojson(self) -> dict[str, Any]:
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": f.id, "properties": {"name": f.name, "subtype": f.subtype, "source": f.source},
             "geometry": f.geometry} for f in self.features]}


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


class Executor:
    def __init__(self, store: Store | None = None, geocoder: Geocoder | None = None,
                 resolver: Any = None, config: dict[str, Any] | None = None):
        self.store = store or get_store()
        self.geocoder = geocoder
        self.resolver = resolver  # optional callable(name, type_hint, context) -> id, used for Resolve without id
        self.cfg = config or load_config()
        self.policy = self.cfg["policy"]

    # ------------------------------------------------------------ public

    def execute(self, dag: dict[str, Any], *, with_geometry: bool = True, view: list[float] | None = None) -> Result:
        """view: map view (xmin, ymin, xmax, ymax). Photon anchors use its center as a location bias."""
        errors = validate(dag, choices())
        if errors:
            return Result(ok=False, error="invalid DAG: " + "; ".join(errors))
        run = _Run(self, view)
        t0 = time.time()
        try:
            rel = run.eval(dag)
            kind = "geometry" if CATALOG[dag["op"]].out == "Geometry" else "set"
            res = run.collect(rel, with_geometry=with_geometry)
            res.kind = kind
        except ExecutionError as e:
            return Result(ok=False, error=str(e), sql=run.sql, notes=run.notes)
        finally:
            run.close()
        res.timings["total_s"] = round(time.time() - t0, 3)
        return res

    def geocoder_or_default(self) -> Geocoder:
        if self.geocoder is None:
            self.geocoder = PhotonGeocoder()
        return self.geocoder


class _Run:
    """State of one execution: a DuckDB cursor with temp tables."""

    def __init__(self, ex: Executor, view: list[float] | None = None):
        self.ex = ex
        self.view = view
        self.policy = ex.policy
        self.con = ex.store.new_session()
        for m in MACROS:
            self.con.execute(m)
        self.n = 0
        tables = {r[0] for r in self.con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        self.has_layer_dist = "layer_dist" in tables
        self.tables = tables
        self.sql: list[str] = []
        self.notes: list[str] = []

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass

    def run(self, sql: str, params: list[Any] | None = None):
        self.sql.append(sql.strip())
        try:
            return self.con.execute(sql, params or [])
        except Exception as e:
            raise ExecutionError(f"SQL error: {e}\n{sql}") from e

    def new_rel(self, select_sql: str, params: list[Any] | None = None) -> str:
        self.n += 1
        name = f"r{self.n}"
        self.run(f"CREATE TEMP TABLE {name} AS SELECT {REL_COLS} FROM ({select_sql})", params)
        return name

    def empty_rel(self) -> str:
        return self.new_rel("SELECT NULL::VARCHAR AS id, NULL::VARCHAR AS name, NULL::VARCHAR AS subtype, "
                            "NULL::VARCHAR AS source, crs84(ST_GeomFromText('POINT EMPTY')) AS geometry, "
                            "crs84(ST_GeomFromText('POINT EMPTY')) AS gs WHERE false")

    # ------------------------------------------------------------ helpers

    def union_geom(self, rel: str, col: str = "geometry") -> str:
        """SQL expression for the union of all geometries of a relation."""
        return f"(SELECT crs84(ST_Union_Agg({col})) FROM {rel})"

    def lat_of(self, rel: str) -> float:
        row = self.run(f"SELECT avg(ST_Y(ST_Centroid(gs))) FROM {rel}").fetchone()
        return float(row[0]) if row and row[0] is not None else 20.0

    def deg(self, meters: float, lat: float) -> float:
        """Upper bound in degrees for a distance in meters at a latitude."""
        return meters / (M_PER_DEG * max(math.cos(math.radians(abs(lat) + 1.0)), 0.2))

    def ids_of(self, rel: str) -> list[str]:
        return [r[0] for r in self.run(f"SELECT id FROM {rel} WHERE id IS NOT NULL").fetchall()]

    def country_of(self, rel: str) -> str:
        """Country of most divisions in a relation; the configured country if it has none."""
        row = self.run(f"SELECT d.country FROM {rel} r JOIN divisions d ON d.id = r.id WHERE d.country IS NOT NULL "
                       "GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1").fetchone()
        return row[0] if row else self.ex.cfg["data"]["country"]

    def level_countries(self, rel: str) -> list[str]:
        """Countries for the level filter of a relation: the countries of its divisions. A natural feature is in no
        country: the countries whose simplified shape is near it (country_shapes)."""
        codes = [r[0] for r in self.run(f"SELECT DISTINCT d.country FROM {rel} r JOIN divisions d ON d.id = r.id "
                                        f"WHERE d.country IS NOT NULL AND d.country <> '{NATURAL_COUNTRY}' ORDER BY 1").fetchall()]
        if codes:
            return codes
        if not self.run(f"SELECT count(*) FROM {rel} WHERE subtype = 'natural'").fetchone()[0]:
            return [self.country_of(rel)]
        tol = float(self.policy["around_tolerance_deg"])
        codes = [r[0] for r in self.run(f"SELECT country FROM country_shapes WHERE ST_DWithin(geometry, "
                                        f"{self.union_geom(rel, 'gs')}, {tol}) ORDER BY 1").fetchall()]
        return codes or [self.country_of(rel)]

    def levels_filter(self, level: str, codes: list[str]) -> str:
        """The level filter of each country, joined with OR."""
        if len(codes) == 1:
            return self.level_filter(level, codes[0])
        return "(" + " OR ".join(f"({self.level_filter(level, c)})" for c in codes) + ")"

    def level_filter(self, level: str, country: str, alias: str = "d") -> str:
        p = country_policy(self.policy, country)
        cond = [f"{alias}.subtype IN ({', '.join(_q(s) for s in p['admin_levels'][level])})"]
        if level == "city":
            cond.append(f"{alias}.class IN ({', '.join(_q(c) for c in p['city_classes'])})")
        if level == "village":
            cond.append(f"{alias}.class IN ({', '.join(_q(c) for c in p['village_classes'])})")
        if level == "union_territory":
            cond.append(f"{alias}.region IN ({', '.join(_q(u) for u in p['union_territories']) or 'NULL'})")
        if level == "state":
            if p["require_region_code"]:
                cond.append(f"{alias}.region IS NOT NULL")
            if not p["union_territories_are_states"] and p["union_territories"]:
                cond.append(f"{alias}.region NOT IN ({', '.join(_q(u) for u in p['union_territories'])})")
        if level != "country":
            cond.append(f"{alias}.country = {_q(country)}")
        else:
            # Overture's disputed areas are country rows with the codes XA to XZ; policy.disputed_kept keeps some (Kosovo).
            keep = ", ".join(_q(c) for c in p["disputed_kept"]) or "NULL"
            cond.append(f"({alias}.subtype <> 'country' OR {alias}.country NOT LIKE 'X%' OR {alias}.country IN ({keep}))")
        return " AND ".join(cond)

    def divisions_rel(self, where: str, params: list[Any] | None = None) -> str:
        # The divisions first, then their areas. Without MATERIALIZED, DuckDB can join all world areas before the
        # filter (minutes for "regions of Italy"). A filter on the areas (a.) joins them in the first step.
        join = "LEFT JOIN areas a ON a.id = d.id" if re.search(r"\ba\.", where) else ""
        return self.new_rel(f"""
            WITH sel AS MATERIALIZED (SELECT d.* FROM divisions d {join} WHERE {where})
            SELECT d.id, coalesce(d.name_en, d.name) AS name, d.subtype, 'overture' AS source,
                   crs84(coalesce(a.geometry, d.geometry)) AS geometry, crs84(coalesce(a.gs, d.geometry)) AS gs
            FROM sel d LEFT JOIN areas a ON a.id = d.id
        """, params)

    # ------------------------------------------------------------ evaluation

    def eval(self, node: Any) -> str:
        op = node["op"]
        fn = getattr(self, f"op_{op}", None)
        if fn is None:
            raise ExecutionError(f"operator {op} is not implemented")
        return fn(**node.get("args", {}))

    def collect(self, rel: str, with_geometry: bool) -> Result:
        simp = float(self.policy.get("output_simplify_deg", 0) or 0)
        g = f"ST_SimplifyPreserveTopology(geometry, {simp})" if simp > 0 else "geometry"
        geom_sql = f"ST_AsGeoJSON({g})" if with_geometry else "NULL"
        rows = self.run(f"SELECT id, name, subtype, source, {geom_sql} FROM {rel} "
                        f"WHERE geometry IS NOT NULL AND NOT ST_IsEmpty(geometry) ORDER BY name").fetchall()
        feats = [Feature(id=r[0], name=r[1], subtype=r[2], source=r[3],
                         geometry=json.loads(r[4]) if isinstance(r[4], str) else r[4]) for r in rows]
        return Result(ok=True, features=feats, ids=sorted({f.id for f in feats if f.id}), sql=self.sql, notes=self.notes)

    # ------------------------------------------------------------ sources

    def op_Resolve(self, name: str, type_hint: str | None = None, context: str | None = None,
                   source: str | None = None, id: str | None = None) -> str:
        if source == "photon":
            return self._resolve_photon(name, id)
        if id is None:
            if self.ex.resolver is not None:
                id = self.ex.resolver(name, type_hint, context)
            else:
                cands = self.ex.store.search(name, type_hint=type_hint, context=context)
                id = cands[0].id if cands else None
            if id is None:
                raise ExecutionError(f"cannot resolve {name!r} in the local extract")
        return self.divisions_rel("d.id = ?", [id])

    def _resolve_photon(self, name: str, id: str | None) -> str:
        if self.view:
            v = self.view
            feats = self.ex.geocoder_or_default().search(name, limit=5, location=((v[0] + v[2]) / 2, (v[1] + v[3]) / 2))
        else:
            feats = self.ex.geocoder_or_default().search(name, limit=5, bbox=tuple(self._bbox_xyxy()))
        if id:
            feats = [f for f in feats if f.id == id] or feats
        if not feats:
            raise ExecutionError(f"the geocoder found no result for {name!r}")
        f = feats[0]
        return self.new_rel("SELECT ? AS id, ? AS name, ? AS subtype, 'photon' AS source, "
                            "crs84(ST_Point(?, ?)) AS geometry, crs84(ST_Point(?, ?)) AS gs",
                            [f.id, f.name, f"{f.osm_key}:{f.osm_value}", f.lon, f.lat, f.lon, f.lat])

    def _bbox_xyxy(self) -> list[float]:
        return list(self.ex.cfg["data"]["bbox"])

    def op_LexiconSet(self, key: str) -> str:
        entry = lexicon()[key]
        ids = [m["id"] for m in entry["members"] if m["id"]]
        missing = [m["code"] for m in entry["members"] if not m["id"]]
        if missing:
            self.notes.append(f"lexicon {key}: members not in the extract: {', '.join(missing)}")
        return self.divisions_rel("d.id IN (SELECT unnest(?))", [ids])

    def layer_geom(self, name: str) -> str:
        return f"(SELECT crs84(geometry) FROM layers WHERE name = {_q(name)})"

    def op_Layer(self, name: str) -> str:
        return self.new_rel(f"SELECT NULL AS id, {_q(name)} AS name, 'layer' AS subtype, 'layer' AS source, "
                            f"{self.layer_geom(name)} AS geometry, {self.layer_geom(name)} AS gs")

    # ------------------------------------------------------------ hierarchy

    def op_Children(self, of: Any, level: str | None = None) -> str:
        parent = self.eval(of)
        # A set of divisions of the asked level ("countries of the Balkans", a named set of countries): the set.
        if level and level != "none":
            subtypes = {r[0] for r in self.run(f"SELECT DISTINCT subtype FROM {parent}").fetchall()}
            if subtypes and subtypes <= set(self.policy["admin_levels"].get(level, [])):
                return parent
        # Several parent countries ("districts along the Danube"), or a natural feature: the level filter of each
        # country.
        codes = self.level_countries(parent)
        country = self.country_of(parent)
        country = country if country in codes else codes[0]
        if level is None or level == "none":
            level = self.child_level(parent, country)
        lf = self.levels_filter(level, codes)
        # A direction part has the id of its source but only a part of its geometry, and a natural feature is not
        # an ancestor of divisions: use the geometry.
        natural = self.run(f"SELECT count(*) FROM {parent} WHERE subtype = 'natural'").fetchone()[0] > 0
        if self.ids_of(parent) and not (isinstance(of, dict) and of.get("op") == "Direction") and not natural:
            return self.divisions_rel(
                f"{lf} AND EXISTS (SELECT 1 FROM {parent} p "
                f"WHERE p.id IS NOT NULL AND p.id <> d.id AND list_contains(d.ancestors, p.id))")
        # A natural feature: the divisions that overlap it ("districts in the Aravalli range"; most of their points are
        # outside a long, narrow range). A computed geometry (a direction part): the division point inside it.
        if natural:
            return self.divisions_rel(f"{lf} AND a.id IS NOT NULL AND ST_Intersects(crs84(a.gs), {self.union_geom(parent, 'gs')})")
        return self.divisions_rel(f"{lf} AND ST_Intersects(crs84(d.geometry), {self.union_geom(parent, 'gs')})")

    def child_level(self, parent: str, country: str) -> str:
        """The level of the highest subtype (region, county, locality) of the divisions inside the parent."""
        levels = country_policy(self.policy, country)["admin_levels"]
        found = {r[0] for r in self.run(f"""
            SELECT DISTINCT d.subtype FROM divisions d, {parent} p WHERE p.id IS NOT NULL AND p.id <> d.id
              AND d.subtype IN ('region', 'county', 'locality') AND list_contains(d.ancestors, p.id)""").fetchall()}
        for subtype in ("region", "county", "locality"):
            if subtype in found:
                return next(k for k, v in levels.items() if v == [subtype])
        raise ExecutionError("cannot find a level for the divisions of the parent")

    def op_Parent(self, of: Any, level: str) -> str:
        child = self.eval(of)
        ids = self.ids_of(child)
        lf = self.level_filter(level, self.country_of(child))
        if ids and self.run(f"SELECT count(*) FROM {child} WHERE source = 'overture'").fetchone()[0]:
            return self.divisions_rel(
                f"{lf} AND d.id IN (SELECT unnest(c.ancestors) FROM divisions c "
                f"WHERE c.id IN (SELECT id FROM {child}))")
        return self.divisions_rel(
            f"{lf} AND a.id IS NOT NULL AND ST_Contains(crs84(a.gs), "
            f"(SELECT ST_PointOnSurface(crs84(ST_Union_Agg(gs))) FROM {child}))")

    def op_Neighbors(self, of: Any, level: str | None = None) -> str:
        src = self.eval(of)
        lat = self.lat_of(src)
        tol = self.deg(float(self.policy["neighbor_tolerance_m"]), lat)
        codes = self.level_countries(src)
        country = self.country_of(src)
        country = country if country in codes else codes[0]
        if level is None or level == "none":
            subtypes = [r[0] for r in self.run(f"SELECT DISTINCT subtype FROM {src}").fetchall()]
            levels = country_policy(self.policy, country)["admin_levels"]
            lvl = next((k for k, v in levels.items() if set(subtypes) <= set(v)), None)
            if lvl is None:
                raise ExecutionError(f"cannot find a level for neighbors of subtypes {subtypes}")
            level = lvl
        return self.divisions_rel(
            f"{self.levels_filter(level, codes)} AND a.id IS NOT NULL "
            f"AND d.id NOT IN (SELECT id FROM {src} WHERE id IS NOT NULL) "
            f"AND ST_DWithin(crs84(a.gs), {self.union_geom(src, 'gs')}, {tol})")

    # ------------------------------------------------------------ filters

    def pred_sql(self, pred: dict[str, Any], alias: str = "s") -> str:
        op, args = pred["op"], pred.get("args", {})
        if op == "Not":
            return f"NOT ({self.pred_sql(args['pred'], alias)})"
        target = args["target"]
        if op == "Touches":
            if target["op"] == "Layer":
                name = target["args"]["name"]
                tol_m = self.policy["coastal_tolerance_m"] if name == "coastline" else self.policy["neighbor_tolerance_m"]
                tol = self.deg(float(tol_m), 20.0)
                # Use the distance from the build when it exists, else compute it.
                pre = f"(SELECT ld.{name} FROM layer_dist ld WHERE ld.id = {alias}.id)" if self.has_layer_dist else "NULL"
                return f"coalesce({pre} <= {tol}, ST_DWithin({alias}.gs, {self.layer_geom(name)}, {tol}))"
            t = self.eval(target)
            tol = self.deg(float(self.policy["neighbor_tolerance_m"]), self.lat_of(t))
            # Each member of the target (no union: the union of many features, for example all rivers, is slow).
            return (f"(EXISTS (SELECT 1 FROM {t} x WHERE ST_DWithin({alias}.gs, crs84(x.gs), {tol})) "
                    f"AND NOT coalesce({alias}.id IN (SELECT id::VARCHAR FROM {t} WHERE id IS NOT NULL), false))")
        if op == "Within":
            t = self.eval(target)
            return f"ST_Intersects(ST_PointOnSurface({alias}.gs), {self.union_geom(t, 'gs')})"
        if op == "Intersects":
            t = self.eval(target)
            return f"EXISTS (SELECT 1 FROM {t} x WHERE ST_Intersects({alias}.gs, crs84(x.gs)))"
        if op == "WithinDistance":
            g = self.layer_geom(target["args"]["name"]) if target["op"] == "Layer" else self.union_geom(self.eval(target), "gs")
            d = float(args["distance_m"])
            return f"ST_DWithin(to_m({alias}.gs, utm({alias}.gs)), to_m({g}, utm({alias}.gs)), {d})"
        raise ExecutionError(f"unknown predicate {op}")

    def op_Filter(self, set: Any, pred: dict[str, Any]) -> str:
        src = self.eval(set)
        cond = self.pred_sql(pred, "s")
        return self.new_rel(f"SELECT s.* FROM {src} s WHERE {cond}")

    def population(self) -> str:
        """The population of the population filters and ranks: Overture's, else Wikidata's (column wd_population of
        build_extract.add_population; databases built before it do not have the column)."""
        has = self.run("""SELECT count(*) FROM information_schema.columns
                          WHERE table_name = 'divisions' AND column_name = 'wd_population'""").fetchone()[0]
        return "coalesce(d.population, d.wd_population)" if has else "d.population"

    def op_AttrFilter(self, set: Any, attr: str, op: str, value: float) -> str:
        src = self.eval(set)
        cmp = {"gt": ">", "lt": "<"}[op]
        if attr == "population":
            expr = f"(SELECT {self.population()} FROM divisions d WHERE d.id = s.id)"
            n_null = self.run(f"SELECT count(*) FROM {src} s WHERE {expr} IS NULL").fetchone()[0]
            if n_null:
                self.notes.append(f"population: {n_null} entities have no population in the extract and are excluded")
        elif attr == "area":
            expr = "(ST_Area(to_m(s.gs, utm(s.gs))) / 1e6)"
        else:
            raise ExecutionError(f"unknown attribute {attr}")
        return self.new_rel(f"SELECT s.* FROM {src} s WHERE {expr} {cmp} ?", [float(value)])

    def op_Naturals(self, kind: str, within: Any = None) -> str:
        where = f"d.subtype = 'natural' AND d.class = {_q(kind)}"
        if within is None:
            return self.divisions_rel(where)
        g = self.union_geom(self.eval(within), "gs")
        return self.divisions_rel(f"{where} AND a.id IS NOT NULL AND ST_Intersects(crs84(a.gs), {g})")

    def op_Top(self, set: Any, by: str, n: float, order: str) -> str:
        src = self.eval(set)
        if by == "population":
            expr = f"(SELECT {self.population()} FROM divisions d WHERE d.id = s.id)"
        else:
            expr = "(ST_Area(to_m(s.gs, utm(s.gs))) / 1e6)"
        direction = "DESC" if order == "largest" else "ASC"
        return self.new_rel(f"SELECT s.* FROM {src} s WHERE {expr} IS NOT NULL ORDER BY {expr} {direction}, s.id LIMIT {int(n)}")

    def op_Common(self, a: Any, b: Any) -> str:
        ra, rb = self.eval(a), self.eval(b)
        return self.new_rel(f"SELECT * FROM {ra} WHERE id IS NOT NULL AND id IN (SELECT id FROM {rb} WHERE id IS NOT NULL)")

    # ------------------------------------------------------------ geometry

    def op_SharedBorder(self, a: Any, b: Any) -> str:
        ra, rb = self.eval(a), self.eval(b)
        tol = self.deg(float(self.policy["neighbor_tolerance_m"]), self.lat_of(ra))
        rel = self.new_rel(f"""
            WITH u AS (SELECT ST_Intersection(ST_Boundary({self.union_geom(ra, 'gs')}),
                                              ST_Buffer({self.union_geom(rb, 'gs')}, {tol})) AS g)
            SELECT NULL AS id, 'shared border' AS name, 'geometry' AS subtype, 'computed' AS source,
                   u.g AS geometry, u.g AS gs
            FROM u WHERE NOT ST_IsEmpty(u.g)
        """)
        if not self.run(f"SELECT count(*) FROM {rel}").fetchone()[0]:
            raise ExecutionError("the two places do not share a border")
        return rel

    def op_Buffer(self, of: Any, distance_m: float) -> str:
        src = self.eval(of)
        g = self.union_geom(src, "gs")
        return self.new_rel(f"""
            WITH u AS (SELECT {g} AS g)
            SELECT NULL AS id, 'buffer' AS name, 'geometry' AS subtype, 'computed' AS source,
                   from_m(ST_Buffer(to_m(u.g, utm(u.g)), {float(distance_m)}, 16), utm(u.g)) AS geometry,
                   from_m(ST_Buffer(to_m(u.g, utm(u.g)), {float(distance_m)}, 16), utm(u.g)) AS gs
            FROM u
        """)

    def op_Centroid(self, of: Any) -> str:
        src = self.eval(of)
        g = self.union_geom(src)
        return self.new_rel(f"""
            WITH u AS (SELECT {g} AS g)
            SELECT NULL AS id, 'centroid' AS name, 'geometry' AS subtype, 'computed' AS source,
                   from_m(ST_Centroid(to_m(u.g, utm(u.g))), utm(u.g)) AS geometry,
                   from_m(ST_Centroid(to_m(u.g, utm(u.g))), utm(u.g)) AS gs
            FROM u
        """)

    def op_Direction(self, of: Any, dir: str, mode: str) -> str:
        src = self.eval(of)
        row = self.run(f"SELECT ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g) FROM (SELECT {self.union_geom(src, 'gs')} AS g)").fetchone()
        if row is None or row[0] is None:
            raise ExecutionError("direction: empty input")
        x0, y0, x1, y1 = row
        w, h = x1 - x0, y1 - y0
        parts = {"north": "n", "south": "s", "east": "e", "west": "w", "northeast": "ne", "northwest": "nw",
                 "southeast": "se", "southwest": "sw", "central": "c"}[dir]
        if mode == "part":
            f = float(self.policy["direction_part_fraction"])
            bx0, by0, bx1, by1 = x0, y0, x1, y1
            if parts == "c":
                m = (1 - f) / 2
                bx0, bx1, by0, by1 = x0 + m * w, x1 - m * w, y0 + m * h, y1 - m * h
            if "n" in parts:
                by0 = y1 - f * h
            if "s" in parts:
                by1 = y0 + f * h
            if "e" in parts:
                bx0 = x1 - f * w
            if "w" in parts:
                bx1 = x0 + f * w
            box = f"crs84(ST_MakeEnvelope({bx0}, {by0}, {bx1}, {by1}))"
            return self.new_rel(f"""
                SELECT id, name, subtype, source, ST_Intersection(geometry, {box}) AS geometry,
                       ST_Intersection(gs, {box}) AS gs
                FROM {src} WHERE ST_Intersects(gs, {box})
            """)
        # outside
        if parts == "c":
            raise ExecutionError("direction 'central' has no outside area")
        s = float(self.policy["direction_outside_scale"])
        bx0, bx1, by0, by1 = x0, x1, y0, y1
        if "n" in parts:
            by0, by1 = y1, y1 + s * h
        if "s" in parts:
            by0, by1 = y0 - s * h, y0
        if "e" in parts:
            bx0, bx1 = x1, x1 + s * w
        if "w" in parts:
            bx0, bx1 = x0 - s * w, x0
        box = f"crs84(ST_MakeEnvelope({bx0}, {by0}, {bx1}, {by1}))"
        g = self.union_geom(src, "gs")
        return self.new_rel(f"""
            SELECT NULL AS id, {_q(dir + ' of')} AS name, 'geometry' AS subtype, 'computed' AS source,
                   ST_Difference({box}, {g}) AS geometry, ST_Difference({box}, {g}) AS gs
        """)

    # ------------------------------------------------------------ set algebra

    def op_Union(self, a: Any, b: Any) -> str:
        ra, rb = self.eval(a), self.eval(b)
        return self.new_rel(f"""
            SELECT * FROM {ra}
            UNION ALL
            SELECT * FROM {rb} WHERE id IS NULL OR id NOT IN (SELECT id FROM {ra} WHERE id IS NOT NULL)
        """)

    def op_Intersect(self, a: Any, b: Any) -> str:
        ra, rb = self.eval(a), self.eval(b)
        g = self.union_geom(rb)
        gs = self.union_geom(rb, "gs")
        return self.new_rel(f"""
            SELECT id, name, subtype, source, ST_Intersection(geometry, {g}) AS geometry,
                   ST_Intersection(gs, {gs}) AS gs
            FROM {ra} WHERE ST_Intersects(gs, {gs})
        """)

    def op_Difference(self, a: Any, b: Any) -> str:
        ra, rb = self.eval(a), self.eval(b)
        g = self.union_geom(rb)
        gs = self.union_geom(rb, "gs")
        # Rows of a that are also in b are removed. The other rows lose the area of b.
        return self.new_rel(f"""
            SELECT id, name, subtype, source,
                   CASE WHEN ST_Intersects(gs, {gs}) THEN ST_Difference(geometry, {g}) ELSE geometry END AS geometry,
                   CASE WHEN ST_Intersects(gs, {gs}) THEN ST_Difference(gs, {gs}) ELSE gs END AS gs
            FROM {ra}
            WHERE id IS NULL OR id NOT IN (SELECT id FROM {rb} WHERE id IS NOT NULL)
        """)

    # ------------------------------------------------------------ relational

    def op_Between(self, a: Any, b: Any) -> str:
        ra, rb = self.eval(a), self.eval(b)
        ga, gb = self.union_geom(ra, "gs"), self.union_geom(rb, "gs")
        return self.new_rel(f"""
            WITH u AS (SELECT {ga} AS a, {gb} AS b)
            SELECT NULL AS id, 'between' AS name, 'geometry' AS subtype, 'computed' AS source,
                   ST_Difference(ST_Difference(ST_ConvexHull(ST_Union(a, b)), a), b) AS geometry,
                   ST_Difference(ST_Difference(ST_ConvexHull(ST_Union(a, b)), a), b) AS gs
            FROM u
        """)

    def op_Along(self, line: Any, distance_m: float, within: Any = None) -> str:
        d = float(distance_m)
        rw = self.eval(within) if within is not None else None
        if line["op"] == "Layer":
            lg = self.layer_geom(line["args"]["name"])
            if rw is None:
                raise ExecutionError("Along a layer needs a 'within' region")
            wg = self.union_geom(rw, "gs")
            pad = self.deg(d, self.lat_of(rw)) * 1.5
            # Clip the layer to the padded bbox of the region first.
            clip = (f"ST_Intersection({lg}, crs84(ST_MakeEnvelope(ST_XMin({wg}) - {pad}, ST_YMin({wg}) - {pad}, "
                    f"ST_XMax({wg}) + {pad}, ST_YMax({wg}) + {pad})))")
        else:
            rl = self.eval(line)
            # A line (a river, a shared border) is the line itself; an area is its boundary.
            g = self.union_geom(rl, "gs")
            clip = f"(SELECT CASE WHEN ST_Dimension(x) = 1 THEN x ELSE ST_Boundary(x) END FROM (SELECT {g} AS x))"
            wg = None
        sql = f"""
            WITH l AS (SELECT {clip} AS g),
                 b AS (SELECT from_m(ST_Buffer(to_m(l.g, utm(l.g)), {d}, 8), utm(l.g)) AS g FROM l WHERE NOT ST_IsEmpty(l.g))
            SELECT NULL AS id, 'along' AS name, 'geometry' AS subtype, 'computed' AS source,
                   {f'ST_Intersection(b.g, {wg})' if wg else 'b.g'} AS geometry,
                   {f'ST_Intersection(b.g, {wg})' if wg else 'b.g'} AS gs
            FROM b
        """
        return self.new_rel(sql)

    # ------------------------------------------------------------ features

    def op_Features(self, category: str, within: Any) -> str:
        source = self.ex.cfg["geocoder"].get("features_source", "places")
        table = self.features_table(category) if source == "places" else None
        if table:
            return self._features_places(category, within, table)
        if source == "places":
            self.notes.append(f"features: no local data for {category}; Photon is used")
        return self._features_photon(category, within)

    def features_table(self, category: str) -> str | None:
        """`places` (all categories of one country), else the world point dataset of the category (plan-008 phase 5)."""
        if "places" in self.tables:
            return "places"
        for name, items in self.ex.cfg["data"].get("poi_datasets", {}).items():
            if category in items and f"poi_{name}" in self.tables:
                return f"poi_{name}"
        return None

    def _features_places(self, category: str, within: Any, table: str) -> str:
        """Features from the local Overture places table (plan-004 section 2)."""
        leaf = category_leaves()[category]
        rw = self.area_of(self.eval(within))
        g = self.union_geom(rw, "gs")
        row = self.run(f"SELECT ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g), ST_IsEmpty(g) FROM (SELECT {g} AS g)").fetchone()
        if row is None or row[0] is None or row[4]:
            self.notes.append("features: the region is empty, so the result is empty")
            return self.empty_rel()
        x0, y0, x1, y1 = row[:4]
        min_conf = float(self.policy.get("places_min_confidence", 0.0))
        limit = int(self.policy.get("max_features", 10000))
        rel = self.new_rel(f"""
            WITH r AS (SELECT {g} AS g)
            SELECT p.id, p.name, ? AS subtype, 'overture_places' AS source,
                   crs84(ST_Point(p.lon, p.lat)) AS geometry, crs84(ST_Point(p.lon, p.lat)) AS gs
            FROM {table} p, r
            WHERE p.lon BETWEEN {x0} AND {x1} AND p.lat BETWEEN {y0} AND {y1}
              AND p.confidence >= {min_conf}
              AND list_has_any(p.cats, ?)
              AND ST_Intersects(r.g, crs84(ST_Point(p.lon, p.lat)))
            LIMIT {limit + 1}
        """, [category, leaf["match"]])
        n = self.run(f"SELECT count(*) FROM {rel}").fetchone()[0]
        if n > limit:
            self.notes.append(f"features: more than {limit} results; the result is cut at {limit + 1}")
        return rel

    def area_of(self, rel: str) -> str:
        """A relation with areas. Point rows (places without an area polygon) get a buffer whose radius is
        set by subtype in the policy config (`point_area_radius_m`)."""
        n_points = self.run(f"SELECT count(*) FROM {rel} WHERE ST_GeometryType(gs) IN ('POINT', 'MULTIPOINT')").fetchone()[0]
        if not n_points:
            return rel
        radii = self.policy.get("point_area_radius_m", {})
        default = float(radii.get("default", 1000))
        case = " ".join(f"WHEN {_q(k)} THEN {float(v)}" for k, v in radii.items() if k != "default")
        r_expr = f"(CASE subtype {case} ELSE {default} END)" if case else str(default)
        self.notes.append(f"{n_points} place(s) have no area polygon; a radius from the policy config is used")
        return self.new_rel(f"""
            SELECT id, name, subtype, source,
                   CASE WHEN ST_GeometryType(gs) IN ('POINT', 'MULTIPOINT')
                        THEN from_m(ST_Buffer(to_m(gs, utm(gs)), {r_expr}, 16), utm(gs)) ELSE geometry END AS geometry,
                   CASE WHEN ST_GeometryType(gs) IN ('POINT', 'MULTIPOINT')
                        THEN from_m(ST_Buffer(to_m(gs, utm(gs)), {r_expr}, 16), utm(gs)) ELSE gs END AS gs
            FROM {rel}
        """)

    def _features_photon(self, category: str, within: Any) -> str:
        leaf = category_leaves()[category]
        if not leaf.get("photon_tag"):
            raise ExecutionError(f"category {category} has no Photon tag")
        osm_tag = leaf["photon_tag"]
        q_text = leaf["description"].split(" ")[0].lower()
        rw = self.area_of(self.eval(within))
        row = self.run(f"SELECT ST_AsWKB({self.union_geom(rw, 'gs')})").fetchone()
        if row is None or row[0] is None:
            return self.empty_rel()
        geom = shapely.from_wkb(bytes(row[0]))
        if geom.is_empty:
            self.notes.append("features: the region is empty, so the result is empty")
            return self.empty_rel()
        tiles = _tiles(geom.bounds, int(self.ex.cfg["geocoder"]["max_tiles"]))
        gc = self.ex.geocoder_or_default()
        limit = int(self.ex.cfg["geocoder"]["limit"])
        seen: dict[str, Any] = {}
        shapely.prepare(geom)
        for t in tiles:
            if not geom.intersects(shapely.box(*t)):
                continue
            for f in gc.search(q_text, limit=limit, bbox=t, osm_tag=osm_tag):
                if f.id not in seen and geom.contains(shapely.Point(f.lon, f.lat)):
                    seen[f.id] = f
        if len(tiles) > 1:
            self.notes.append(f"features: {len(tiles)} geocoder tiles, max {limit} results each")
        if not seen:
            return self.empty_rel()
        rows = [[f.id, f.name, category, f.lon, f.lat] for f in seen.values()]
        self.n += 1
        tmp = f"pts{self.n}"
        self.run(f"CREATE TEMP TABLE {tmp} (id VARCHAR, name VARCHAR, subtype VARCHAR, lon DOUBLE, lat DOUBLE)")
        self.con.executemany(f"INSERT INTO {tmp} VALUES (?, ?, ?, ?, ?)", rows)
        return self.new_rel(f"SELECT id, name, subtype, 'photon' AS source, crs84(ST_Point(lon, lat)) AS geometry, "
                            f"crs84(ST_Point(lon, lat)) AS gs FROM {tmp}")


def _tiles(bounds: tuple[float, float, float, float], max_tiles: int) -> list[tuple[float, float, float, float]]:
    """Split a bbox into at most max_tiles tiles of about 0.05 degrees or more."""
    x0, y0, x1, y1 = bounds
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    n = max(1, min(int(math.sqrt(max_tiles)), math.ceil(max(w, h) / 0.05)))
    return [(x0 + i * w / n, y0 + j * h / n, x0 + (i + 1) * w / n, y0 + (j + 1) * h / n)
            for i in range(n) for j in range(n)]
