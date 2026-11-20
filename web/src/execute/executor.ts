// Port of geoparse/execute/executor.py for DuckDB-WASM (engine 1.5). In the browser data, `geometry` is the
// simplified polygon (areas.parquet has only the simplified form), so geometry and gs are the same column.
import { LOCAL_SUBTYPES } from "./store.ts";
import { countryPolicy, type Bundle } from "../core/bundle.ts";
import { NATURAL_COUNTRY } from "./gazetteer.ts";
import { validate } from "../core/dsl.ts";
import { list, q, type Db } from "./db.ts";
import type { Photon } from "./photon.ts";

const M_PER_DEG = 111320;
const COLS = "id, name, subtype, source, geometry, gs";
let RUN = 0;

export interface Feature { id: string | null; name: string | null; subtype: string | null; source: string | null; geometry: any }
export interface Result { ok: boolean; kind: string; features: Feature[]; ids: string[]; error: string | null; sql: string[]; notes: string[]; timings: Record<string, number> }

class ExecError extends Error {}

export class Executor {
  macrosReady = false;
  constructor(public db: Db, public bundle: Bundle, public photon: Photon) {}

  /** view: map view (xmin, ymin, xmax, ymax). Photon anchors use its center as a location bias. */
  async execute(dag: any, withGeometry = true, view: number[] | null = null): Promise<Result> {
    const errors = validate(dag, this.bundle);
    if (errors.length) return { ok: false, kind: "set", features: [], ids: [], error: "invalid DAG: " + errors.join("; "), sql: [], notes: [], timings: {} };
    if (!this.macrosReady) {
      for (const m of [
        "CREATE OR REPLACE MACRO crs84(g) AS g",
        "CREATE OR REPLACE MACRO utm(g) AS 'EPSG:' || (32600 + floor((ST_X(ST_Centroid(g)) + 180) / 6) + 1)::INT",
        "CREATE OR REPLACE MACRO to_m(g, crs) AS ST_Transform(g, 'EPSG:4326', crs)",
        "CREATE OR REPLACE MACRO from_m(g, crs) AS ST_Transform(g, crs, 'EPSG:4326')",
      ]) await this.db.query(m);
      this.macrosReady = true;
    }
    if (JSON.stringify(dag).includes('"op":"Layer"')) await this.db.store?.ensureLayers();
    const run = new Run(this, ++RUN, view);
    const t0 = performance.now();
    try {
      const rel = await run.eval(dag);
      const res = await run.collect(rel, withGeometry);
      res.kind = this.bundle.catalog[dag.op].out === "Geometry" ? "geometry" : "set";
      res.timings.total_s = (performance.now() - t0) / 1000;
      return res;
    } catch (e) {
      return { ok: false, kind: "set", features: [], ids: [], error: (e as Error).message, sql: run.sql, notes: run.notes, timings: {} };
    } finally {
      await run.close();
    }
  }
}

class Run {
  n = 0;
  sql: string[] = [];
  notes: string[] = [];
  tables: string[] = [];
  policy: any;
  constructor(public ex: Executor, public id: number, public view: number[] | null = null) { this.policy = ex.bundle.config.policy; }

  async run(sql: string) {
    this.sql.push(sql.trim());
    try { return await this.ex.db.query(sql); } catch (e) { throw new ExecError(`SQL error: ${(e as Error).message}\n${sql}`); }
  }

  async close() {
    for (const t of this.tables) { try { await this.ex.db.query(`DROP TABLE IF EXISTS ${t}`); } catch { /* ignore */ } }
  }

  async newRel(select: string): Promise<string> {
    const name = `r${this.id}_${++this.n}`;
    this.tables.push(name);
    await this.run(`CREATE TEMP TABLE ${name} AS SELECT ${COLS} FROM (${select})`);
    return name;
  }

  emptyRel() {
    return this.newRel("SELECT NULL::VARCHAR AS id, NULL::VARCHAR AS name, NULL::VARCHAR AS subtype, NULL::VARCHAR AS source, " +
      "ST_GeomFromText('POINT EMPTY') AS geometry, ST_GeomFromText('POINT EMPTY') AS gs WHERE false");
  }

  unionGeom(rel: string, col = "geometry") { return `(SELECT ST_Union_Agg(${col}) FROM ${rel})`; }

  async latOf(rel: string): Promise<number> {
    const r = await this.run(`SELECT avg(ST_Y(ST_Centroid(gs))) AS y FROM ${rel}`);
    return r[0]?.y ?? 20;
  }

  deg(m: number, lat: number) { return m / (M_PER_DEG * Math.max(Math.cos(((Math.abs(lat) + 1) * Math.PI) / 180), 0.2)); }

  async idsOf(rel: string): Promise<string[]> { return (await this.run(`SELECT id FROM ${rel} WHERE id IS NOT NULL`)).map((r) => r.id); }

  /** Country of most divisions in a relation; the configured country if it has none. */
  async countryOf(rel: string): Promise<string> {
    const r = await this.run(`SELECT d.country FROM ${rel} r JOIN divisions d ON d.id = r.id WHERE d.country IS NOT NULL
      GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1`);
    return r[0]?.country ?? this.ex.bundle.config.data.country;
  }

  levelFilter(level: string, country: string, a = "d"): string {
    const p = countryPolicy(this.policy, country);
    const cond = [`${a}.subtype IN (${p.admin_levels[level].map(q).join(", ")})`];
    if (level === "city") cond.push(`${a}.class IN (${p.city_classes.map(q).join(", ")})`);
    if (level === "village") cond.push(`${a}.class IN (${p.village_classes.map(q).join(", ")})`);
    if (level === "union_territory") cond.push(`${a}.region IN (${p.union_territories.map(q).join(", ") || "NULL"})`);
    if (level === "state") {
      if (p.require_region_code) cond.push(`${a}.region IS NOT NULL`);
      if (!p.union_territories_are_states && p.union_territories.length) cond.push(`${a}.region NOT IN (${p.union_territories.map(q).join(", ")})`);
    }
    if (level !== "country") cond.push(`${a}.country = ${q(country)}`);
    else cond.push(`(${a}.subtype <> 'country' OR ${a}.country NOT LIKE 'X%' OR ${a}.country IN (${(p.disputed_kept ?? []).map(q).join(", ") || "NULL"}))`);
    return cond.join(" AND ");
  }

  /** Country layout: polygons of all countries for an operation at country level. Other levels are limited to the
   * default country (levelFilter), which is loaded at start-up. */
  async levelData(level: string) {
    if (level === "country") await this.ex.db.store?.ensureAdminAreas();
  }

  divisionsRel(where: string) {
    return this.newRel(`SELECT d.id, coalesce(d.name_en, d.name) AS name, d.subtype, 'overture' AS source,
      coalesce(a.geometry, d.geometry) AS geometry, coalesce(a.gs, d.geometry) AS gs
      FROM divisions d LEFT JOIN areas a ON a.id = d.id WHERE ${where}`);
  }

  async eval(node: any): Promise<string> {
    const fn = (this as any)[`op_${node.op}`];
    if (!fn) throw new ExecError(`operator ${node.op} is not implemented`);
    return fn.call(this, node.args ?? {});
  }

  async collect(rel: string, withGeometry: boolean) {
    const simp = Number(this.policy.output_simplify_deg ?? 0);
    const g = simp > 0 ? `ST_SimplifyPreserveTopology(geometry, ${simp})` : "geometry";
    const rows = await this.run(`SELECT id, name, subtype, source, ${withGeometry ? `ST_AsGeoJSON(${g})` : "NULL"} AS gj
      FROM ${rel} WHERE geometry IS NOT NULL AND NOT ST_IsEmpty(geometry) ORDER BY name`);
    const features = rows.map((r) => ({ id: r.id, name: r.name, subtype: r.subtype, source: r.source,
      geometry: typeof r.gj === "string" ? JSON.parse(r.gj) : r.gj ?? null }));
    const ids = [...new Set(features.map((f) => f.id).filter(Boolean))].sort() as string[];
    return { ok: true, kind: "set", features, ids, error: null, sql: this.sql, notes: this.notes, timings: {} } as Result;
  }

  // ------------------------------------------------------------ sources

  async op_Resolve(a: any) {
    if (a.source === "photon") {
      const v = this.view;
      const feats = await this.ex.photon.search(a.name, v?.length
        ? { limit: 5, location: [(v[0] + v[2]) / 2, (v[1] + v[3]) / 2] } : { limit: 5, bbox: this.ex.bundle.config.data.bbox });
      const f = (a.id && feats.find((x) => x.id === a.id)) || feats[0];
      if (!f) throw new ExecError(`the geocoder found no result for '${a.name}'`);
      return this.newRel(`SELECT ${q(f.id)} AS id, ${q(f.name)} AS name, ${q(`${f.osm_key}:${f.osm_value}`)} AS subtype,
        'photon' AS source, ST_Point(${f.lon}, ${f.lat}) AS geometry, ST_Point(${f.lon}, ${f.lat}) AS gs`);
    }
    if (!a.id) throw new ExecError(`'${a.name}' has no resolved id`);
    await this.ex.db.store?.ensureId(a.id, a.name);
    return this.divisionsRel(`d.id = ${q(a.id)}`);
  }

  /** Port of population: Overture's population, else Wikidata's (data exported before plan-031 has no wd_population). */
  async population(): Promise<string> {
    const has = (await this.run(`SELECT count(*) AS n FROM information_schema.columns
      WHERE table_name = 'divisions' AND column_name = 'wd_population'`))[0].n > 0;
    return has ? "coalesce(d.population, d.wd_population)" : "d.population";
  }

  async op_LexiconSet(a: any) {
    const entry = this.ex.bundle.lexicon[a.key];
    const ids = entry.members.filter((m) => m.id).map((m) => m.id!) as string[];
    const missing = entry.members.filter((m) => !m.id).map((m) => m.code);
    if (missing.length) this.notes.push(`lexicon ${a.key}: members not in the extract: ${missing.join(", ")}`);
    // The members are countries (the global admin areas) and states (the regions file of their country): no country
    // data to load.
    const states = entry.members.filter((m) => m.id && m.code.includes("-")).map((m) => m.code.split("-")[0]);
    const countries = entry.members.some((m) => m.id && !m.code.includes("-"));
    await Promise.all([countries ? this.ex.db.store?.ensureAdminAreas() : null, this.ex.db.store?.ensureRegions(states)]);
    return this.divisionsRel(`d.id IN (SELECT unnest(${list(ids)}))`);
  }

  layerGeom(name: string) { return `(SELECT geometry FROM layers WHERE name = ${q(name)})`; }

  op_Layer(a: any) {
    return this.newRel(`SELECT NULL AS id, ${q(a.name)} AS name, 'layer' AS subtype, 'layer' AS source,
      ${this.layerGeom(a.name)} AS geometry, ${this.layerGeom(a.name)} AS gs`);
  }

  // ------------------------------------------------------------ hierarchy

  /** Port of level_countries: the countries of the divisions of a relation; for a natural feature, the countries
   * whose simplified shape is near it (country_shapes). Loads their data, except with load = false. */
  async levelCountries(rel: string, load = true): Promise<string[]> {
    let codes = (await this.run(`SELECT DISTINCT d.country FROM ${rel} r JOIN divisions d ON d.id = r.id
      WHERE d.country IS NOT NULL AND d.country <> '${NATURAL_COUNTRY}' ORDER BY 1`)).map((r) => r.country as string);
    if (!codes.length) {
      if (!(await this.run(`SELECT count(*) AS n FROM ${rel} WHERE subtype = 'natural'`))[0].n) return [await this.countryOf(rel)];
      await this.ex.db.store?.ensureCountryShapes();
      codes = (await this.run(`SELECT country FROM country_shapes WHERE ST_DWithin(geometry, ${this.unionGeom(rel, "gs")},
        ${Number(this.policy.around_tolerance_deg)}) ORDER BY 1`)).map((r) => r.country);
      if (!codes.length) return [await this.countryOf(rel)];
    }
    if (load) await this.ex.db.store?.ensureCountries(codes);
    return codes;
  }

  /** A level with local subtypes (city, village, locality) in one of the countries: the local part of their data. */
  needsLocal(level: string, codes: string[]): boolean {
    return codes.some((c) => (countryPolicy(this.policy, c).admin_levels[level] ?? []).some((s: string) => LOCAL_SUBTYPES.includes(s)));
  }

  /** Port of levels_filter: the level filter of each country, joined with OR. */
  levelsFilter(level: string, codes: string[]): string {
    return codes.length === 1 ? this.levelFilter(level, codes[0]) : `(${codes.map((c) => `(${this.levelFilter(level, c)})`).join(" OR ")})`;
  }

  async op_Children(a: any) {
    const parent = await this.eval(a.of);
    // Port: a set of divisions of the asked level ("countries of the Balkans") is the set (no country data to load).
    if (a.level && a.level !== "none") {
      const subtypes = (await this.run(`SELECT DISTINCT subtype FROM ${parent}`)).map((r) => r.subtype as string);
      const own = this.policy.admin_levels[a.level] ?? [];
      if (subtypes.length && subtypes.every((s) => own.includes(s))) return parent;
    }
    // Several parent countries ("districts along the Danube"), or a natural feature: the level filter of each country.
    const codes = await this.levelCountries(parent);
    let country = await this.countryOf(parent);
    if (!codes.includes(country)) country = codes[0];
    // No level: the highest subtype inside the parent. The admin part has the regions and counties; only if there are
    // none (the parent is a district or a city) the local part is needed.
    const level = a.level && a.level !== "none" ? a.level
      : await this.childLevel(parent, country).catch(async () => { await this.ex.db.store?.ensureLocal(codes); return this.childLevel(parent, country); });
    if (this.needsLocal(level, codes)) await this.ex.db.store?.ensureLocal(codes);
    await this.levelData(level);
    const lf = this.levelsFilter(level, codes);
    // A direction part has the id of its source but only a part of its geometry, and a natural feature is not an
    // ancestor of divisions: use the geometry.
    const natural = (await this.run(`SELECT count(*) AS n FROM ${parent} WHERE subtype = 'natural'`))[0].n > 0;
    if ((await this.idsOf(parent)).length && a.of?.op !== "Direction" && !natural)
      return this.divisionsRel(`${lf} AND EXISTS (SELECT 1 FROM ${parent} p
        WHERE p.id IS NOT NULL AND p.id <> d.id AND list_contains(d.ancestors, p.id))`);
    // A natural feature: the divisions that overlap it (a long, narrow range). A direction part: the point inside it.
    if (natural) return this.divisionsRel(`${lf} AND a.id IS NOT NULL AND ST_Intersects(a.gs, ${this.unionGeom(parent, "gs")})`);
    return this.divisionsRel(`${lf} AND ST_Intersects(d.geometry, ${this.unionGeom(parent, "gs")})`);
  }

  /** Port of child_level: the level of the highest subtype (region, county, locality) of the divisions inside the parent. */
  async childLevel(parent: string, country: string): Promise<string> {
    const levels = countryPolicy(this.policy, country).admin_levels;
    const found = new Set((await this.run(`SELECT DISTINCT d.subtype FROM divisions d, ${parent} p WHERE p.id IS NOT NULL
      AND p.id <> d.id AND d.subtype IN ('region', 'county', 'locality') AND list_contains(d.ancestors, p.id)`)).map((r) => r.subtype));
    for (const subtype of ["region", "county", "locality"])
      if (found.has(subtype)) return Object.entries(levels).find(([, v]: any) => v.length === 1 && v[0] === subtype)![0];
    throw new ExecError("cannot find a level for the divisions of the parent");
  }

  async op_Parent(a: any) {
    const child = await this.eval(a.of);
    await this.levelData(a.level);
    const ids = await this.idsOf(child);
    const lf = this.levelFilter(a.level, await this.countryOf(child));
    const nOv = (await this.run(`SELECT count(*) AS n FROM ${child} WHERE source = 'overture'`))[0].n;
    if (ids.length && nOv)
      return this.divisionsRel(`${lf} AND d.id IN (SELECT unnest(c.ancestors) FROM divisions c
        WHERE c.id IN (SELECT id FROM ${child}))`);
    return this.divisionsRel(`${lf} AND a.id IS NOT NULL AND ST_Contains(a.gs,
      (SELECT ST_PointOnSurface(ST_Union_Agg(gs)) FROM ${child}))`);
  }

  async op_Neighbors(a: any) {
    const src = await this.eval(a.of);
    const tol = this.deg(Number(this.policy.neighbor_tolerance_m), await this.latOf(src));
    let level = a.level;
    // The data of the countries is not needed at the country level (the admin rows and polygons of all countries are).
    const codes = await this.levelCountries(src, false);
    let country = await this.countryOf(src);
    if (!codes.includes(country)) country = codes[0];
    if (!level || level === "none") {
      const subtypes = (await this.run(`SELECT DISTINCT subtype FROM ${src}`)).map((r) => r.subtype);
      level = Object.entries(countryPolicy(this.policy, country).admin_levels).find(([, v]: any) => subtypes.every((s) => v.includes(s)))?.[0];
      if (!level) throw new ExecError(`cannot find a level for neighbors of subtypes ${subtypes}`);
    }
    if (level !== "country") await (this.needsLocal(level, codes) ? this.ex.db.store?.ensureLocal(codes) : this.ex.db.store?.ensureCountries(codes));
    await this.levelData(level);
    return this.divisionsRel(`${this.levelsFilter(level, codes)} AND a.id IS NOT NULL
      AND d.id NOT IN (SELECT id FROM ${src} WHERE id IS NOT NULL)
      AND ST_DWithin(a.gs, ${this.unionGeom(src, "gs")}, ${tol})`);
  }

  // ------------------------------------------------------------ filters

  async predSql(p: any, al = "s"): Promise<string> {
    const args = p.args ?? {};
    if (p.op === "Not") return `NOT (${await this.predSql(args.pred, al)})`;
    const t = args.target;
    if (p.op === "Touches") {
      if (t.op === "Layer") {
        const name = t.args.name;
        const tolM = name === "coastline" ? this.policy.coastal_tolerance_m : this.policy.neighbor_tolerance_m;
        const tol = this.deg(Number(tolM), 20);
        return `coalesce((SELECT ld.${name} FROM layer_dist ld WHERE ld.id = ${al}.id) <= ${tol}, ST_DWithin(${al}.gs, ${this.layerGeom(name)}, ${tol}))`;
      }
      const rel = await this.eval(t);
      const tol = this.deg(Number(this.policy.neighbor_tolerance_m), await this.latOf(rel));
      // Each member of the target (no union: the union of many features, for example all rivers, is slow).
      return `(EXISTS (SELECT 1 FROM ${rel} x WHERE ST_DWithin(${al}.gs, x.gs, ${tol}))
        AND NOT coalesce(${al}.id IN (SELECT id::VARCHAR FROM ${rel} WHERE id IS NOT NULL), false))`;
    }
    if (p.op === "Within") return `ST_Intersects(ST_PointOnSurface(${al}.gs), ${this.unionGeom(await this.eval(t), "gs")})`;
    if (p.op === "Intersects") return `EXISTS (SELECT 1 FROM ${await this.eval(t)} x WHERE ST_Intersects(${al}.gs, x.gs))`;
    if (p.op === "WithinDistance") {
      const g = t.op === "Layer" ? this.layerGeom(t.args.name) : this.unionGeom(await this.eval(t), "gs");
      return `ST_DWithin(to_m(${al}.gs, utm(${al}.gs)), to_m(${g}, utm(${al}.gs)), ${Number(args.distance_m)})`;
    }
    throw new ExecError(`unknown predicate ${p.op}`);
  }

  async op_Filter(a: any) {
    const src = await this.eval(a.set);
    return this.newRel(`SELECT s.* FROM ${src} s WHERE ${await this.predSql(a.pred, "s")}`);
  }

  async op_AttrFilter(a: any) {
    const src = await this.eval(a.set);
    const cmp = a.op === "gt" ? ">" : "<";
    let expr: string;
    if (a.attr === "population") {
      expr = `(SELECT ${await this.population()} FROM divisions d WHERE d.id = s.id)`;
      const n = (await this.run(`SELECT count(*) AS n FROM ${src} s WHERE ${expr} IS NULL`))[0].n;
      if (n) this.notes.push(`population: ${n} entities have no population in the extract and are excluded`);
    } else if (a.attr === "area") expr = "(ST_Area(to_m(s.gs, utm(s.gs))) / 1e6)";
    else throw new ExecError(`unknown attribute ${a.attr}`);
    return this.newRel(`SELECT s.* FROM ${src} s WHERE ${expr} ${cmp} ${Number(a.value)}`);
  }

  // ------------------------------------------------------------ geometry

  async op_Naturals(a: any) {
    await this.ex.db.store?.ensureCountries([NATURAL_COUNTRY]);
    const where = `d.subtype = 'natural' AND d.class = ${q(a.kind)}`;
    if (!a.within) return this.divisionsRel(where);
    return this.divisionsRel(`${where} AND a.id IS NOT NULL AND ST_Intersects(a.gs, ${this.unionGeom(await this.eval(a.within), "gs")})`);
  }

  async op_Top(a: any) {
    const src = await this.eval(a.set);
    const expr = a.by === "population" ? `(SELECT ${await this.population()} FROM divisions d WHERE d.id = s.id)` : "(ST_Area(to_m(s.gs, utm(s.gs))) / 1e6)";
    return this.newRel(`SELECT s.* FROM ${src} s WHERE ${expr} IS NOT NULL ORDER BY ${expr} ${a.order === "largest" ? "DESC" : "ASC"}, s.id LIMIT ${Math.trunc(Number(a.n))}`);
  }

  async op_Common(a: any) {
    const ra = await this.eval(a.a), rb = await this.eval(a.b);
    return this.newRel(`SELECT * FROM ${ra} WHERE id IS NOT NULL AND id IN (SELECT id FROM ${rb} WHERE id IS NOT NULL)`);
  }

  async op_SharedBorder(a: any) {
    const ra = await this.eval(a.a), rb = await this.eval(a.b);
    const tol = this.deg(Number(this.policy.neighbor_tolerance_m), await this.latOf(ra));
    const rel = await this.newRel(`WITH u AS (SELECT ST_Intersection(ST_Boundary(${this.unionGeom(ra, "gs")}),
        ST_Buffer(${this.unionGeom(rb, "gs")}, ${tol})) AS g)
      SELECT NULL AS id, 'shared border' AS name, 'geometry' AS subtype, 'computed' AS source, u.g AS geometry, u.g AS gs
      FROM u WHERE NOT ST_IsEmpty(u.g)`);
    if (!(await this.run(`SELECT count(*) AS n FROM ${rel}`))[0].n) throw new ExecError("the two places do not share a border");
    return rel;
  }

  async op_Buffer(a: any) {
    const g = this.unionGeom(await this.eval(a.of), "gs");
    const d = Number(a.distance_m);
    const b = `from_m(ST_Buffer(to_m(u.g, utm(u.g)), ${d}, 16), utm(u.g))`;
    return this.newRel(`WITH u AS (SELECT ${g} AS g) SELECT NULL AS id, 'buffer' AS name, 'geometry' AS subtype,
      'computed' AS source, ${b} AS geometry, ${b} AS gs FROM u`);
  }

  async op_Centroid(a: any) {
    const g = this.unionGeom(await this.eval(a.of));
    const c = "from_m(ST_Centroid(to_m(u.g, utm(u.g))), utm(u.g))";
    return this.newRel(`WITH u AS (SELECT ${g} AS g) SELECT NULL AS id, 'centroid' AS name, 'geometry' AS subtype,
      'computed' AS source, ${c} AS geometry, ${c} AS gs FROM u`);
  }

  async op_Direction(a: any) {
    const src = await this.eval(a.of);
    const r = (await this.run(`SELECT ST_XMin(g) AS x0, ST_YMin(g) AS y0, ST_XMax(g) AS x1, ST_YMax(g) AS y1 FROM (SELECT ${this.unionGeom(src, "gs")} AS g)`))[0];
    if (!r || r.x0 === null) throw new ExecError("direction: empty input");
    const { x0, y0, x1, y1 } = r;
    const w = x1 - x0, h = y1 - y0;
    const parts = ({ north: "n", south: "s", east: "e", west: "w", northeast: "ne", northwest: "nw", southeast: "se", southwest: "sw", central: "c" } as any)[a.dir];
    if (a.mode === "part") {
      const f = Number(this.policy.direction_part_fraction);
      let [bx0, by0, bx1, by1] = [x0, y0, x1, y1];
      if (parts === "c") { const m = (1 - f) / 2; [bx0, bx1, by0, by1] = [x0 + m * w, x1 - m * w, y0 + m * h, y1 - m * h]; }
      if (parts.includes("n")) by0 = y1 - f * h;
      if (parts.includes("s")) by1 = y0 + f * h;
      if (parts.includes("e")) bx0 = x1 - f * w;
      if (parts.includes("w")) bx1 = x0 + f * w;
      const box = `ST_MakeEnvelope(${bx0}, ${by0}, ${bx1}, ${by1})`;
      return this.newRel(`SELECT id, name, subtype, source, ST_Intersection(geometry, ${box}) AS geometry,
        ST_Intersection(gs, ${box}) AS gs FROM ${src} WHERE ST_Intersects(gs, ${box})`);
    }
    if (parts === "c") throw new ExecError("direction 'central' has no outside area");
    const s = Number(this.policy.direction_outside_scale);
    let [bx0, bx1, by0, by1] = [x0, x1, y0, y1];
    if (parts.includes("n")) [by0, by1] = [y1, y1 + s * h];
    if (parts.includes("s")) [by0, by1] = [y0 - s * h, y0];
    if (parts.includes("e")) [bx0, bx1] = [x1, x1 + s * w];
    if (parts.includes("w")) [bx0, bx1] = [x0 - s * w, x0];
    const box = `ST_MakeEnvelope(${bx0}, ${by0}, ${bx1}, ${by1})`;
    const g = this.unionGeom(src, "gs");
    return this.newRel(`SELECT NULL AS id, ${q(a.dir + " of")} AS name, 'geometry' AS subtype, 'computed' AS source,
      ST_Difference(${box}, ${g}) AS geometry, ST_Difference(${box}, ${g}) AS gs`);
  }

  // ------------------------------------------------------------ set algebra

  async op_Union(a: any) {
    const ra = await this.eval(a.a), rb = await this.eval(a.b);
    return this.newRel(`SELECT * FROM ${ra} UNION ALL SELECT * FROM ${rb}
      WHERE id IS NULL OR id NOT IN (SELECT id FROM ${ra} WHERE id IS NOT NULL)`);
  }

  async op_Intersect(a: any) {
    const ra = await this.eval(a.a), rb = await this.eval(a.b);
    const g = this.unionGeom(rb), gs = this.unionGeom(rb, "gs");
    return this.newRel(`SELECT id, name, subtype, source, ST_Intersection(geometry, ${g}) AS geometry,
      ST_Intersection(gs, ${gs}) AS gs FROM ${ra} WHERE ST_Intersects(gs, ${gs})`);
  }

  async op_Difference(a: any) {
    const ra = await this.eval(a.a), rb = await this.eval(a.b);
    const g = this.unionGeom(rb), gs = this.unionGeom(rb, "gs");
    return this.newRel(`SELECT id, name, subtype, source,
      CASE WHEN ST_Intersects(gs, ${gs}) THEN ST_Difference(geometry, ${g}) ELSE geometry END AS geometry,
      CASE WHEN ST_Intersects(gs, ${gs}) THEN ST_Difference(gs, ${gs}) ELSE gs END AS gs
      FROM ${ra} WHERE id IS NULL OR id NOT IN (SELECT id FROM ${rb} WHERE id IS NOT NULL)`);
  }

  // ------------------------------------------------------------ relational

  async op_Between(a: any) {
    const ga = this.unionGeom(await this.eval(a.a), "gs"), gb = this.unionGeom(await this.eval(a.b), "gs");
    const e = "ST_Difference(ST_Difference(ST_ConvexHull(ST_Union(a, b)), a), b)";
    return this.newRel(`WITH u AS (SELECT ${ga} AS a, ${gb} AS b) SELECT NULL AS id, 'between' AS name,
      'geometry' AS subtype, 'computed' AS source, ${e} AS geometry, ${e} AS gs FROM u`);
  }

  async op_Along(a: any) {
    const d = Number(a.distance_m);
    const rw = a.within ? await this.eval(a.within) : null;
    let clip: string, wg: string | null = null;
    if (a.line.op === "Layer") {
      if (!rw) throw new ExecError("Along a layer needs a 'within' region");
      const lg = this.layerGeom(a.line.args.name);
      wg = this.unionGeom(rw, "gs");
      const pad = this.deg(d, await this.latOf(rw)) * 1.5;
      clip = `ST_Intersection(${lg}, ST_MakeEnvelope(ST_XMin(${wg}) - ${pad}, ST_YMin(${wg}) - ${pad}, ST_XMax(${wg}) + ${pad}, ST_YMax(${wg}) + ${pad}))`;
    } else {
      // A line (a river, a shared border) is the line itself; an area is its boundary.
      clip = `(SELECT CASE WHEN ST_Dimension(x) = 1 THEN x ELSE ST_Boundary(x) END FROM (SELECT ${this.unionGeom(await this.eval(a.line), "gs")} AS x))`;
    }
    const out = wg ? `ST_Intersection(b.g, ${wg})` : "b.g";
    return this.newRel(`WITH l AS (SELECT ${clip} AS g),
      b AS (SELECT from_m(ST_Buffer(to_m(l.g, utm(l.g)), ${d}, 8), utm(l.g)) AS g FROM l WHERE NOT ST_IsEmpty(l.g))
      SELECT NULL AS id, 'along' AS name, 'geometry' AS subtype, 'computed' AS source, ${out} AS geometry, ${out} AS gs FROM b`);
  }

  // ------------------------------------------------------------ features (local Overture places)

  async areaOf(rel: string): Promise<string> {
    const n = (await this.run(`SELECT count(*) AS n FROM ${rel} WHERE ST_GeometryType(gs) IN ('POINT', 'MULTIPOINT')`))[0].n;
    if (!n) return rel;
    const radii = this.policy.point_area_radius_m ?? {};
    const def = Number(radii.default ?? 1000);
    const cases = Object.entries(radii).filter(([k]) => k !== "default").map(([k, v]) => `WHEN ${q(k)} THEN ${Number(v)}`).join(" ");
    const r = cases ? `(CASE subtype ${cases} ELSE ${def} END)` : String(def);
    this.notes.push(`${n} place(s) have no area polygon; a radius from the policy config is used`);
    const b = `CASE WHEN ST_GeometryType(gs) IN ('POINT', 'MULTIPOINT') THEN from_m(ST_Buffer(to_m(gs, utm(gs)), ${r}, 16), utm(gs)) ELSE gs END`;
    return this.newRel(`SELECT id, name, subtype, source, ${b} AS geometry, ${b} AS gs FROM ${rel}`);
  }

  async op_Features(a: any) {
    const leaf: any = Object.values(this.ex.bundle.categories).map((g) => g.items[a.category]).find(Boolean);
    if (!leaf) throw new ExecError(`unknown category ${a.category}`);
    const rw = await this.areaOf(await this.eval(a.within));
    const g = this.unionGeom(rw, "gs");
    const r = (await this.run(`SELECT ST_XMin(g) AS x0, ST_YMin(g) AS y0, ST_XMax(g) AS x1, ST_YMax(g) AS y1, ST_IsEmpty(g) AS e FROM (SELECT ${g} AS g)`))[0];
    if (!r || r.x0 === null || r.e) { this.notes.push("features: the region is empty, so the result is empty"); return this.emptyRel(); }
    const local = (this.ex.bundle.config.geocoder.features_source ?? "places") === "places";
    const table = !local ? null : this.ex.db.store ? this.ex.db.store.featuresTable(a.category) : "places";
    if (!table) {
      if (local) this.notes.push(`features: no local data for ${a.category}; Photon is used`);
      return this.featuresPhoton(a.category, leaf, g, [r.x0, r.y0, r.x1, r.y1]);
    }
    const minConf = Number(this.policy.places_min_confidence ?? 0);
    const limit = Number(this.policy.max_features ?? 10000);
    const rel = await this.newRel(`WITH r AS (SELECT ${g} AS g)
      SELECT p.id, p.name, ${q(a.category)} AS subtype, 'overture_places' AS source,
             ST_Point(p.lon, p.lat) AS geometry, ST_Point(p.lon, p.lat) AS gs
      FROM ${table} p, r
      WHERE p.lon BETWEEN ${r.x0} AND ${r.x1} AND p.lat BETWEEN ${r.y0} AND ${r.y1}
        AND p.confidence >= ${minConf} AND list_has_any(p.cats, ${list(leaf.match)})
        AND ST_Intersects(r.g, ST_Point(p.lon, p.lat))
      LIMIT ${limit + 1}`);
    const n = (await this.run(`SELECT count(*) AS n FROM ${rel}`))[0].n;
    if (n > limit) this.notes.push(`features: more than ${limit} results; the result is cut at ${limit + 1}`);
    return rel;
  }

  /** Port of _features_photon: one Photon search for each tile of the bbox that touches the region. */
  async featuresPhoton(category: string, leaf: any, g: string, bounds: number[]) {
    if (!leaf.photon_tag) throw new ExecError(`category ${category} has no Photon tag`);
    const cfg = this.ex.bundle.config.geocoder;
    const limit = Number(cfg.limit);
    const tiles = tilesOf(bounds, Number(cfg.max_tiles));
    const hit = await this.run(`SELECT list(ST_Intersects(g, ST_MakeEnvelope(t[1], t[2], t[3], t[4]))) AS h
      FROM (SELECT ${g} AS g), (SELECT unnest(${JSON.stringify(tiles)}::DOUBLE[][]) AS t)`);
    const seen = new Map<string, any>();
    for (const [i, t] of tiles.entries()) {
      if (!hit[0].h[i]) continue;
      for (const f of await this.ex.photon.search(leaf.description.split(" ")[0].toLowerCase(), { limit, bbox: t, osmTag: leaf.photon_tag }))
        if (!seen.has(f.id)) seen.set(f.id, f);
    }
    if (tiles.length > 1) this.notes.push(`features: ${tiles.length} geocoder tiles, max ${limit} results each`);
    if (!seen.size) return this.emptyRel();
    const vals = [...seen.values()].map((f) => `(${q(f.id)}, ${q(f.name)}, ${f.lon}, ${f.lat})`).join(", ");
    return this.newRel(`WITH r AS (SELECT ${g} AS g)
      SELECT p.id, p.name, ${q(category)} AS subtype, 'photon' AS source, ST_Point(p.lon, p.lat) AS geometry, ST_Point(p.lon, p.lat) AS gs
      FROM (VALUES ${vals}) p(id, name, lon, lat), r WHERE ST_Intersects(r.g, ST_Point(p.lon, p.lat))`);
  }
}

/** Port of executor._tiles: split a bbox into at most maxTiles tiles of about 0.05 degrees or more. */
function tilesOf([x0, y0, x1, y1]: number[], maxTiles: number): number[][] {
  const w = Math.max(x1 - x0, 1e-6), h = Math.max(y1 - y0, 1e-6);
  const n = Math.max(1, Math.min(Math.floor(Math.sqrt(maxTiles)), Math.ceil(Math.max(w, h) / 0.05)));
  const out: number[][] = [];
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) out.push([x0 + i * w / n, y0 + j * h / n, x0 + (i + 1) * w / n, y0 + (j + 1) * h / n]);
  return out;
}
