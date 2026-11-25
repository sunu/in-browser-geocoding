// Port of geoparse.execute.data.Store.search and describe.
import { LOCAL_SUBTYPES } from "./store.ts";
import { countryPolicy, type Bundle } from "../core/bundle.ts";
import { normName } from "../core/text.ts";
import type { Candidate } from "../decisions/types.ts";
import { list, q, type Db } from "./db.ts";

const PRIOR: Record<string, number> = {
  country: 0.40, region: 0.38, county: 0.30, "locality|city": 0.32, "locality|town": 0.20, "locality|": 0.12,
  macrohood: 0.16, neighborhood: 0.10, microhood: 0.06, "locality|village": 0.02, "locality|hamlet": 0.0, natural: 0.3,
};
// geoparse.execute.data.NATURAL_COUNTRY: natural features are in no country.
export const NATURAL_COUNTRY = "QN";

// geoparse.execute.data.KIND_SCORE and FUZZY_PREFIX
// Level words at the end of region names that have no short form. The search also tries "<name> <suffix>".
const REGION_SUFFIXES = ["prefecture", "province"];
const KIND_SCORE = "CASE WHEN kind = 'primary' THEN 1.0 WHEN kind = 'en' THEN 0.98 WHEN kind = 'translit' THEN 0.9 ELSE 0.95 END";
const FUZZY_PREFIX = 3;

const COUNTRY_SUBTYPES = ["country", "dependency"];

export class Gazetteer {
  aliases: Record<string, string>;
  demonyms: Record<string, string>;
  constructor(public db: Db, public bundle: Bundle) {
    this.aliases = {};
    for (const [k, v] of Object.entries(bundle.aliases)) this.aliases[normName(k)] = normName(v);
    this.demonyms = {};
    for (const [k, v] of Object.entries(bundle.demonyms ?? {})) this.demonyms[normName(k)] = normName(v);
  }

  async describe(ids: string[]) {
    if (!ids.length) return {} as Record<string, any>;
    const rs = await this.db.query(`
      SELECT d.id, d.name, d.subtype, d.class, d.region, d.country, d.population,
             [h.name FOR h IN list_filter(
                (SELECT list(struct_pack(id := x.id, name := x.name, subtype := x.subtype)
                              ORDER BY list_position(d.ancestors, x.id) DESC)
                 FROM divisions x WHERE list_contains(d.ancestors, x.id) AND x.id <> d.id),
                lambda h: h.subtype IN ('region', 'county', 'locality', 'macrohood'))] AS anc,
             (EXISTS (SELECT 1 FROM areas a WHERE a.id = d.id)${this.db.store ? " OR EXISTS (SELECT 1 FROM name_rows r WHERE r.n = d.n AND r.has_area)" : ""}) AS has_area,
             d.ancestors AS anc_ids, d.lon, d.lat
      FROM divisions d WHERE d.id IN (SELECT unnest(${list(ids)}))`);
    const out: Record<string, any> = {};
    for (const r of rs) out[r.id] = { ...r, ancestors: r.anc ?? [], ancestor_ids: (r.anc_ids ?? []).filter((a: string) => a !== r.id) };
    return out;
  }

  /** Admin level words of one country from the data (manifest level_words). The flat layout has none. */
  levelWords(country: string | null): Record<string, string[]> {
    return this.db.store?.manifest.level_words?.[country ?? ""] ?? {};
  }

  /** Extent of the division points of each country: the manifest bbox, or the divisions table (flat layout). */
  /** Port of Store.countries_around: the countries whose simplified shape is near a division or natural feature
   * (its area, else its point; policy.around_tolerance_deg), in code order. */
  async countriesAround(id: string): Promise<string[]> {
    await this.db.store?.ensureCountryShapes();
    const tol = Number(this.bundle.config.policy.around_tolerance_deg);
    return (await this.db.query(`SELECT country FROM country_shapes WHERE ST_DWithin(geometry,
      (SELECT coalesce(a.gs, d.geometry) FROM divisions d LEFT JOIN areas a ON a.id = d.id WHERE d.id = ${q(id)}), ${tol})
      ORDER BY 1`)).map((x) => x.country);
  }

  private countryExtents(): Promise<Record<string, number[]>> {
    const m = this.db.store?.manifest;
    if (m) return Promise.resolve(Object.fromEntries(Object.entries<any>(m.countries).map(([c, d]) => [c, d.bbox])));
    this.extents ??= this.db.query(`SELECT country, round(min(lon), 5) AS x0, round(min(lat), 5) AS y0,
        round(max(lon), 5) AS x1, round(max(lat), 5) AS y1 FROM divisions WHERE country IS NOT NULL GROUP BY 1`)
      .then((rs) => Object.fromEntries(rs.map((r) => [r.country, [r.x0, r.y0, r.x1, r.y1]])));
    return this.extents;
  }
  private extents: Promise<Record<string, number[]>> | null = null;

  /** Port of Store.view: the map view and the country of its center (the nearest admin point of the countries whose
   * extent contains the center, or of all countries). No view: data.bbox and data.country. */
  async view(view: number[] | null | undefined): Promise<[number[], string | null]> {
    const { data } = this.bundle.config;
    if (!view?.length) return [data.bbox, data.country];
    const cx = (view[0] + view[2]) / 2, cy = (view[1] + view[3]) / 2;
    const inside = Object.entries(await this.countryExtents())
      .filter(([, b]) => b && b[0] <= cx && cx <= b[2] && b[1] <= cy && cy <= b[3]).map(([c]) => c);
    const r = await this.db.query(`SELECT country FROM divisions
      WHERE subtype IN ('country', 'dependency', 'region') AND country IS NOT NULL
        ${inside.length ? `AND country IN (${inside.map((c) => `'${c}'`).join(", ")})` : ""}
      ORDER BY (lon - ${cx}) ** 2 + (lat - ${cy}) ** 2, id LIMIT 1`);
    return [view, r[0]?.country ?? null];
  }

  /** For each division id, the first point (1-based rank) inside its area, or near its point (less than the
   * point_area_radius_m of its subtype). */
  async matchPoints(ids: string[], points: number[][]): Promise<Record<string, number>> {
    if (!ids.length || !points.length) return {};
    const radii = this.bundle.config.policy.point_area_radius_m ?? {};
    const cases = Object.entries(radii).filter(([k]) => k !== "default").map(([k, v]) => `WHEN ${q(k)} THEN ${Number(v)}`).join(" ");
    const def = Number(radii.default ?? 1000);
    const radius = cases ? `(CASE d.subtype ${cases} ELSE ${def} END)` : String(def);
    const pts = points.map((p, i) => `(${i + 1}, ${Number(p[0])}, ${Number(p[1])})`).join(", ");
    const rs = await this.db.query(`
      WITH p(rk, lon, lat) AS (VALUES ${pts})
      SELECT d.id, min(p.rk) AS rk FROM divisions d CROSS JOIN p LEFT JOIN areas a ON a.id = d.id
      WHERE d.id IN (SELECT unnest(${list(ids)}))
        AND ((a.gs IS NOT NULL AND ST_Contains(a.gs, ST_Point(p.lon, p.lat)))
             OR ST_Distance_Sphere(ST_Point(d.lon, d.lat), ST_Point(p.lon, p.lat)) <= ${radius})
      GROUP BY d.id`);
    return Object.fromEntries(rs.map((r) => [r.id, Number(r.rk)]));
  }

  /** The normalized name, the names to search (level word, natural kind, aliases, demonym) and the type hint of the name. */
  private queryNames(name: string): { n: string; qList: string[]; hintFromName: string | null } | null {
    const n = normName(name.trim().replace(/^the\s+/i, ""));
    if (!n) return null;
    const levelWords = new Set(["district", "state", "city", "town", "taluk", "village"]);
    const words = n.split(" ");
    let hintFromName = words.length > 1 && levelWords.has(words[words.length - 1]) ? words[words.length - 1] : null;
    const qList = [n];
    if (hintFromName) qList.push(words.slice(0, -1).join(" "));
    else {
      // "Ganga river" -> name "ganga", hint "natural:river" (the keywords of the option list natural_kinds)
      for (const [kind, ws] of Object.entries<string[]>(Object.fromEntries(Object.entries<any>(this.bundle.options.natural_kinds).map(([k, v]) => [k, v.keywords])))) {
        const w = ws.find((w) => n.endsWith(" " + w));
        if (w) { hintFromName = `natural:${kind}`; qList.push(n.slice(0, -w.length - 1)); break; }
      }
    }
    for (const x of [...qList]) {
      const ws = x.split(" ");
      ws.forEach((w, i) => { if (w in this.aliases) qList.push([...ws.slice(0, i), this.aliases[w], ...ws.slice(i + 1)].join(" ")); });
      if (x in this.aliases) qList.push(this.aliases[x]);
    }
    // Port: a demonym only for the whole name text ("Indian", not "Indian Ocean").
    if (n in this.demonyms) qList.push(this.demonyms[n]);
    return { n, qList, hintFromName };
  }

  /** search(name, { fuzzy: false }).length > 0, without the ranking: a frequent name ("Washington") has thousands of
   * candidates. The answer does not depend on the map view. */
  async exists(name: string): Promise<boolean> {
    return (await this.exactSubtypes(name)).length > 0;
  }

  /** The subtypes of the candidates of search(name, { fuzzy: false }), without the ranking. */
  async exactSubtypes(name: string): Promise<string[]> {
    const qn = this.queryNames(name);
    if (!qn) return [];
    const base = this.bundle.config.policy;
    const store = this.db.store;
    const found = async (xs: string[]) => {
      const keys = xs.map((x) => x.replaceAll(" ", ""));
      let rows: any[];
      if (store) {
        await store.loadKeys(keys);
        rows = await this.db.query(`SELECT DISTINCT n, country, subtype FROM name_rows WHERE key IN (SELECT unnest(${list(keys)}))`);
        // As in search: a region needs its region code where the country policy says so (the code is in the divisions).
        const coded = rows.filter((r) => r.subtype === "region" && countryPolicy(base, r.country).require_region_code);
        if (coded.length) {
          await store.ensureCountries(coded.map((r) => r.country));
          const ok = new Set((await this.db.query(`SELECT n FROM divisions WHERE region IS NOT NULL
            AND n IN (SELECT unnest([${coded.map((r) => r.n).join(", ")}]::INTEGER[]))`)).map((r) => r.n));
          rows = rows.filter((r) => !coded.includes(r) || ok.has(r.n));
        }
      } else {
        rows = (await this.db.query(`SELECT DISTINCT d.country, d.subtype, d.region FROM names n JOIN divisions d ON d.id = n.id
          WHERE n.name_nospace IN (SELECT unnest(${list(keys)}))`))
          .filter((r) => !(r.subtype === "region" && countryPolicy(base, r.country).require_region_code && !r.region));
      }
      return rows.map((r) => r.subtype as string);
    };
    // As in search: the names, the names with a region suffix, then (if none) the names with "district" or "city".
    const out = [...(await found(qn.qList)), ...(await found(qn.qList.flatMap((x) => REGION_SUFFIXES.map((w) => `${x} ${w}`))))];
    return [...new Set(out.length ? out : await found(qn.qList.flatMap((x) => [`${x} district`, `${x} city`])))];
  }

  /** Port of Store.search. fuzzy "only": the fuzzy matches also if there is an exact match. countries: only candidates in
   * these countries (only their data is loaded). */
  async search(name: string, opts: { typeHint?: string | null; context?: string | null; limit?: number; fuzzy?: boolean | "only"; view?: number[] | null; countries?: string[] | null; full?: boolean } = {}): Promise<Candidate[]> {
    const { typeHint = null, context = null, limit = 8, fuzzy = true, view = null, countries = null, full = false } = opts;
    // The name rows have the country: the country files to load come only from these countries.
    const inCountries = countries?.length ? ` AND country IN (SELECT unnest(${list(countries)}))` : "";
    const qn = this.queryNames(name);
    if (!qn) return [];
    const { n, qList, hintFromName } = qn;
    const { policy: base } = this.bundle.config;
    const ranking = base.ranking;
    const [vb, viewCountry] = await this.view(view);
    const [x0, y0, x1, y1] = vb;
    const hint = typeHint ?? hintFromName;
    const h = hint ? ({ district: "district", state: "state", city: "city", town: "city", country: "country", union_territory: "union_territory" } as any)[hint] ?? hint : null;
    const ctx = context ? normName(context) : "";
    // Score without the context match and the map-view penalty; null: not a candidate.
    const partial = (d: any, s: number): number | null => {
      const policy = countryPolicy(base, d.country);
      if (d.subtype === "region" && policy.require_region_code && !d.region) return null;
      let score = s + (PRIOR[`${d.subtype}|${d.class ?? ""}`] ?? PRIOR[d.subtype] ?? 0);
      if (d.has_area) score += 0.1;
      if (d.population) score += Math.min(0.1, Math.log10(Math.max(d.population, 1)) / 100);
      if (h && (policy.admin_levels[h] ?? []).includes(d.subtype)) score += 0.5;
      if (h?.startsWith("natural:") && d.subtype === "natural" && d.class === h.slice(8)) score += 0.5;
      if (d.country !== viewCountry && d.country !== NATURAL_COUNTRY) score -= ranking.view_other_country;
      return score;
    };

    // Name rows with the division id: one relation for the flat layout and the country layout.
    const store = this.db.store;
    const names = store
      ? "SELECT d.id, d.n, r.kind, r.key, d.subtype, d.class, d.population FROM name_rows r JOIN divisions d ON d.n = r.n"
      : "SELECT n.id, n.kind, n.name_nospace AS key, d.subtype, d.class, d.population FROM names n JOIN divisions d ON d.id = n.id";
    // Country layout: load only the countries of the candidates that can be in the best `limit`. The name rows
    // give the score except the context match (at most +0.3) and the view penalty (known if the extent of the
    // country is inside or outside the view). Returns the divisions (n) to keep, if `cap` cut the list.
    const prepare = async (where: string, sim: string, f: number, cap: number | null): Promise<number[] | null> => {
      if (!store) return null;
      const loadRows = (rs: any[]) => Promise.all([store.ensureCountries(rs.map((r) => r.country)),
        store.ensureLocal(rs.filter((r) => LOCAL_SUBTYPES.includes(r.subtype)).map((r) => r.country))]);
      const rows = (await this.db.query(`SELECT r.n, r.country, max(${sim} * ${KIND_SCORE})::DOUBLE AS s,
          any_value(r.subtype) AS subtype, any_value(r.class) AS class, any_value(r.population) AS population,
          bool_or(r.has_area) AS has_area, any_value(a.region) AS region, any_value(r.lon100) AS lon100, any_value(r.lat100) AS lat100
        FROM (SELECT * FROM name_rows WHERE ${where}) r LEFT JOIN (SELECT n, region FROM divisions) a ON a.n = r.n
        GROUP BY r.n, r.country`)).map((r) => ({ ...r, s: Number(r.s) * f }));
      let cand = rows, keep: number[] | null = null;
      if (cap && rows.length > cap) {
        // As Store.search: similarity, then population (the known places of a frequent name stay in the cut).
        const pop = (r: any) => Number(r.population ?? 0);
        rows.sort((a, b) => b.s - a.s || pop(b) - pop(a));
        const at = rows[cap - 1];
        // A tie at the cut: the order by id decides, so load all countries at the cut.
        if (rows[cap].s === at.s && pop(rows[cap]) === pop(at)) {
          await loadRows(rows.filter((r) => r.s > at.s || (r.s === at.s && pop(r) >= pop(at))));
          return null;
        }
        cand = rows.slice(0, cap);
        keep = cand.map((r) => r.n);
      }
      const bounds = cand.flatMap((r) => {
        const p = partial(r, r.s);
        if (p === null) return [];
        // The point of the name row (0.01 degrees): the map-view penalty is known, except for a point within 0.006 degrees of
        // the view edge. Without the point (older data), the extent of the country bounds the penalty.
        let inside: boolean, outside: boolean;
        if (r.lon100 != null) {
          const lon = Number(r.lon100) / 100, lat = Number(r.lat100) / 100, m = 0.006;
          inside = lon >= x0 + m && lon <= x1 - m && lat >= y0 + m && lat <= y1 - m;
          outside = lon < x0 - m || lon > x1 + m || lat < y0 - m || lat > y1 + m;
        } else {
          const b = store.bbox(r.country);
          inside = !!b && b[0] >= x0 && b[2] <= x1 && b[1] >= y0 && b[3] <= y1;
          outside = !!b && (b[2] < x0 || b[0] > x1 || b[3] < y0 || b[1] > y1);
        }
        return [{ country: r.country, lo: p - (inside ? 0 : ranking.view_outside), hi: p + (ctx ? 0.3 : 0) - (outside ? ranking.view_outside : 0),
          own: COUNTRY_SUBTYPES.includes(r.subtype), local: LOCAL_SUBTYPES.includes(r.subtype) }];
      });
      // A country or dependency candidate is described by its admin row (loaded at start-up): its country files
      // are not needed for the ranking ("China" does not load China). A locality or neighbourhood needs the local part.
      const load = (bs: typeof bounds) => Promise.all([store.ensureCountries(bs.filter((b) => !b.own).map((b) => b.country)),
        store.ensureLocal(bs.filter((b) => b.local).map((b) => b.country))]);
      // The best candidate is sure to lead all others by close_margin: the parser uses only it (no Photon boost, no
      // disambiguate). Load only its country.
      if (!full && bounds.length > 1) {
        const top = bounds.reduce((a, b) => (b.lo > a.lo ? b : a));
        const rest = Math.max(...bounds.filter((b) => b !== top).map((b) => b.hi));
        if (top.lo - rest >= Number(ranking.close_margin)) {
          await load([top]);
          return keep;
        }
      }
      const los = bounds.map((b) => b.lo).sort((a, b) => b - a);
      // Only candidates that can be in the best `limit`, and that can come within candidate_window of the best after the
      // Photon boost (the others are not used): their countries are loaded.
      const win = Number(ranking.candidate_window) + Math.max(0, ...(ranking.photon_boost ?? [0]).map(Number));
      const L = Math.max(los.length >= limit ? los[limit - 1] : -Infinity, los.length ? los[0] - win : -Infinity);
      await load(bounds.filter((b) => b.hi >= L - 1e-9));
      return keep;
    };
    const exact = async (xs: string[], f: number) => {
      const keys = xs.map((x) => x.replaceAll(" ", ""));
      const where = `key IN (SELECT unnest(${list(keys)}))`;
      if (store) { await store.loadKeys(keys); await prepare(where + inCountries, "1", f, null); }
      const rs = await this.db.query(`SELECT id, max(${KIND_SCORE})::DOUBLE AS s FROM (${names})
        WHERE ${where} GROUP BY id`);
      return Object.fromEntries(rs.map((r) => [r.id, Number(r.s) * f])) as Record<string, number>;
    };
    let scores: Record<string, number> = {};
    if (fuzzy !== "only") {
      scores = await exact(qList, 1);
      // Overture names of some regions end with a level word and have no short form ("Kyoto Prefecture").
      for (const [id, s] of Object.entries(await exact(qList.flatMap((x) => REGION_SUFFIXES.map((w) => `${x} ${w}`)), 0.98)))
        scores[id] = Math.max(scores[id] ?? 0, s);
      if (!Object.keys(scores).length) scores = await exact(qList.flatMap((x) => [`${x} district`, `${x} city`]), 0.98);
    }
    if (fuzzy && !Object.keys(scores).length && n.length >= 4) {
      const k = n.replaceAll(" ", ""), nk = q(k);
      const where = `subtype IN ('country', 'region', 'county', 'locality', 'macrohood', 'neighborhood')
          AND coalesce(class, '') NOT IN ('hamlet')
          AND left(key, ${FUZZY_PREFIX}) = left(${nk}, ${FUZZY_PREFIX})
          AND jaro_winkler_similarity(key, ${nk}) >= 0.85
          AND damerau_levenshtein(key, ${nk}) <= CASE WHEN length(${nk}) >= 10 THEN 2 ELSE 1 END`;
      let keep: number[] | null = null;
      if (store) {
        await store.loadPrefix([...k].slice(0, FUZZY_PREFIX).join(""));
        keep = await prepare(where + inCountries, `jaro_winkler_similarity(key, ${nk})`, 0.9, 50);
      }
      const only = keep ? ` AND n IN (SELECT unnest([${keep.join(", ")}]::INTEGER[]))` : "";
      const rs = await this.db.query(`SELECT id, max(jaro_winkler_similarity(key, ${nk}) * ${KIND_SCORE})::DOUBLE AS s
        FROM (${names}) WHERE ${where}${only} GROUP BY id ORDER BY s DESC, max(coalesce(population, 0)) DESC, id LIMIT 50`);
      scores = Object.fromEntries(rs.map((r) => [r.id, Number(r.s) * 0.9]));
    }
    if (!Object.keys(scores).length) return [];
    const info = await this.describe(Object.keys(scores));
    const cands: Candidate[] = [];
    for (const [id, s] of Object.entries(scores)) {
      const d = info[id];
      if (!d || (countries?.length && !countries.includes(d.country))) continue;
      // Same terms as partial(), in the order of the Python version (same rounding).
      const policy = countryPolicy(base, d.country);
      if (d.subtype === "region" && policy.require_region_code && !d.region) continue;
      let score = s + (PRIOR[`${d.subtype}|${d.class ?? ""}`] ?? PRIOR[d.subtype] ?? 0);
      if (d.has_area) score += 0.1;
      if (d.population) score += Math.min(0.1, Math.log10(Math.max(d.population, 1)) / 100);
      if (h && (policy.admin_levels[h] ?? []).includes(d.subtype)) score += 0.5;
      if (h?.startsWith("natural:") && d.subtype === "natural" && d.class === h.slice(8)) score += 0.5;
      if (ctx && d.ancestors.some((a: string) => normName(a).includes(ctx) || ctx.includes(normName(a)))) score += 0.3;
      if (d.lon == null || !(d.lon >= x0 && d.lon <= x1 && d.lat >= y0 && d.lat <= y1)) score -= ranking.view_outside;
      if (d.country !== viewCountry && d.country !== NATURAL_COUNTRY) score -= ranking.view_other_country;
      const where = d.ancestors.length ? d.ancestors.slice(-2).reverse().join(", ") : "";
      const kind = d.class ? `${d.subtype} (${d.class})` : d.subtype;
      const desc = `${d.name}: ${kind}` + (where ? ` in ${where}` : "") + (d.country === viewCountry ? "" : `, country ${d.country}`);
      cands.push({ id, name: d.name, source: "overture", subtype: d.subtype, description: desc, score: Math.round(score * 1e4) / 1e4, ancestors: d.ancestor_ids });
    }
    cands.sort((a, b) => b.score - a.score || (a.id < b.id ? -1 : 1));
    return cands.slice(0, limit);
  }
}
