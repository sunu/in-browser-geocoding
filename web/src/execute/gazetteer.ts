// Port of geoparse.execute.data.Store.search and describe.
import { countryPolicy, type Bundle } from "../core/bundle.ts";
import { normName } from "../core/text.ts";
import type { Candidate } from "../decisions/types.ts";
import { list, q, type Db } from "./db.ts";

const PRIOR: Record<string, number> = {
  country: 0.40, region: 0.38, county: 0.30, "locality|city": 0.32, "locality|town": 0.20, "locality|": 0.12,
  macrohood: 0.16, neighborhood: 0.10, microhood: 0.06, "locality|village": 0.02, "locality|hamlet": 0.0,
};

// geoparse.execute.data.KIND_SCORE and FUZZY_PREFIX
const KIND_SCORE = "CASE WHEN kind = 'primary' THEN 1.0 WHEN kind = 'en' THEN 0.98 WHEN kind = 'translit' THEN 0.9 ELSE 0.95 END";
const FUZZY_PREFIX = 3;

export class Gazetteer {
  aliases: Record<string, string>;
  constructor(public db: Db, public bundle: Bundle) {
    this.aliases = {};
    for (const [k, v] of Object.entries(bundle.aliases)) this.aliases[normName(k)] = normName(v);
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
             EXISTS (SELECT 1 FROM areas a WHERE a.id = d.id) AS has_area, d.ancestors AS anc_ids, d.lon, d.lat
      FROM divisions d WHERE d.id IN (SELECT unnest(${list(ids)}))`);
    const out: Record<string, any> = {};
    for (const r of rs) out[r.id] = { ...r, ancestors: r.anc ?? [], ancestor_ids: (r.anc_ids ?? []).filter((a: string) => a !== r.id) };
    return out;
  }

  /** Map view and the country of its center (nearest admin point). No view: data.bbox and data.country. */
  async view(view: number[] | null | undefined): Promise<[number[], string | null]> {
    const { data } = this.bundle.config;
    if (!view?.length) return [data.bbox, data.country];
    const cx = (view[0] + view[2]) / 2, cy = (view[1] + view[3]) / 2;
    const r = await this.db.query(`SELECT country FROM divisions
      WHERE subtype IN ('country', 'dependency', 'region') AND country IS NOT NULL
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

  async search(name: string, opts: { typeHint?: string | null; context?: string | null; limit?: number; fuzzy?: boolean; view?: number[] | null } = {}): Promise<Candidate[]> {
    const { typeHint = null, context = null, limit = 8, fuzzy = true, view = null } = opts;
    const n = normName(name.trim().replace(/^the\s+/i, ""));
    if (!n) return [];
    const levelWords = new Set(["district", "state", "city", "town", "taluk", "village"]);
    const words = n.split(" ");
    const hintFromName = words.length > 1 && levelWords.has(words[words.length - 1]) ? words[words.length - 1] : null;
    const qList = [n];
    if (hintFromName) qList.push(words.slice(0, -1).join(" "));
    for (const x of [...qList]) {
      const ws = x.split(" ");
      ws.forEach((w, i) => { if (w in this.aliases) qList.push([...ws.slice(0, i), this.aliases[w], ...ws.slice(i + 1)].join(" ")); });
      if (x in this.aliases) qList.push(this.aliases[x]);
    }
    // Name rows with the division id: one relation for the flat layout and the country layout.
    const store = this.db.store;
    const names = store
      ? "SELECT d.id, r.kind, r.key, d.subtype, d.class FROM name_rows r JOIN divisions d ON d.n = r.n"
      : "SELECT n.id, n.kind, n.name_nospace AS key, d.subtype, d.class FROM names n JOIN divisions d ON d.id = n.id";
    const exact = async (xs: string[], f: number) => {
      const keys = xs.map((x) => x.replaceAll(" ", ""));
      await store?.ensureKeys(keys);
      const rs = await this.db.query(`SELECT id, max(${KIND_SCORE})::DOUBLE AS s FROM (${names})
        WHERE key IN (SELECT unnest(${list(keys)})) GROUP BY id`);
      return Object.fromEntries(rs.map((r) => [r.id, Number(r.s) * f])) as Record<string, number>;
    };
    let scores = await exact(qList, 1);
    if (!Object.keys(scores).length) scores = await exact(qList.flatMap((x) => [`${x} district`, `${x} city`]), 0.98);
    if (fuzzy && !Object.keys(scores).length && n.length >= 4) {
      const k = n.replaceAll(" ", ""), nk = q(k);
      const where = `subtype IN ('country', 'region', 'county', 'locality', 'macrohood', 'neighborhood')
          AND coalesce(class, '') NOT IN ('hamlet')
          AND left(key, ${FUZZY_PREFIX}) = left(${nk}, ${FUZZY_PREFIX})
          AND jaro_winkler_similarity(key, ${nk}) >= 0.85
          AND damerau_levenshtein(key, ${nk}) <= CASE WHEN length(${nk}) >= 10 THEN 2 ELSE 1 END`;
      await store?.ensurePrefix([...k].slice(0, FUZZY_PREFIX).join(""), where);
      const rs = await this.db.query(`SELECT id, max(jaro_winkler_similarity(key, ${nk}) * ${KIND_SCORE})::DOUBLE AS s
        FROM (${names}) WHERE ${where} GROUP BY id ORDER BY s DESC, id LIMIT 50`);
      scores = Object.fromEntries(rs.map((r) => [r.id, Number(r.s) * 0.9]));
    }
    if (!Object.keys(scores).length) return [];
    const info = await this.describe(Object.keys(scores));
    const { policy: base, data } = this.bundle.config;
    const ranking = base.ranking;
    const [[x0, y0, x1, y1], viewCountry] = await this.view(view);
    const hint = typeHint ?? hintFromName;
    const h = hint ? ({ district: "district", state: "state", city: "city", town: "city", country: "country", union_territory: "union_territory" } as any)[hint] ?? hint : null;
    const ctx = context ? normName(context) : "";
    const cands: Candidate[] = [];
    for (const [id, s] of Object.entries(scores)) {
      const d = info[id];
      if (!d) continue;
      const policy = countryPolicy(base, d.country);
      if (d.subtype === "region" && policy.require_region_code && !d.region) continue;
      const prior = PRIOR[`${d.subtype}|${d.class ?? ""}`] ?? PRIOR[d.subtype] ?? 0;
      let score = s + prior;
      if (d.has_area) score += 0.1;
      if (d.population) score += Math.min(0.1, Math.log10(Math.max(d.population, 1)) / 100);
      if (h && (policy.admin_levels[h] ?? []).includes(d.subtype)) score += 0.5;
      if (ctx && d.ancestors.some((a: string) => normName(a).includes(ctx) || ctx.includes(normName(a)))) score += 0.3;
      if (d.lon == null || !(d.lon >= x0 && d.lon <= x1 && d.lat >= y0 && d.lat <= y1)) score -= ranking.view_outside;
      if (d.country !== viewCountry) score -= ranking.view_other_country;
      const where = d.ancestors.length ? d.ancestors.slice(-2).reverse().join(", ") : "";
      const kind = d.class ? `${d.subtype} (${d.class})` : d.subtype;
      const desc = `${d.name}: ${kind}` + (where ? ` in ${where}` : "") + (d.country === data.country ? "" : `, country ${d.country}`);
      cands.push({ id, name: d.name, source: "overture", subtype: d.subtype, description: desc, score: Math.round(score * 1e4) / 1e4, ancestors: d.ancestor_ids });
    }
    cands.sort((a, b) => b.score - a.score || (a.id < b.id ? -1 : 1));
    return cands.slice(0, limit);
  }
}
