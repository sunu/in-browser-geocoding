// Port of geoparse.execute.data.Store.search and describe.
import type { Bundle } from "../core/bundle.ts";
import { normName } from "../core/text.ts";
import type { Candidate } from "../decisions/types.ts";
import { list, q, type Db } from "./db.ts";

const PRIOR: Record<string, number> = {
  country: 0.40, region: 0.38, county: 0.30, "locality|city": 0.32, "locality|town": 0.20, "locality|": 0.12,
  macrohood: 0.16, neighborhood: 0.10, microhood: 0.06, "locality|village": 0.02, "locality|hamlet": 0.0,
};

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
                (SELECT list(struct_pack(id := x.id, name := x.name, subtype := x.subtype))
                 FROM divisions x WHERE list_contains(d.ancestors, x.id) AND x.id <> d.id),
                lambda h: h.subtype IN ('region', 'county', 'locality', 'macrohood'))] AS anc,
             EXISTS (SELECT 1 FROM areas a WHERE a.id = d.id) AS has_area, d.ancestors AS anc_ids
      FROM divisions d WHERE d.id IN (SELECT unnest(${list(ids)}))`);
    const out: Record<string, any> = {};
    for (const r of rs) out[r.id] = { ...r, ancestors: r.anc ?? [], ancestor_ids: (r.anc_ids ?? []).filter((a: string) => a !== r.id) };
    return out;
  }

  async search(name: string, opts: { typeHint?: string | null; context?: string | null; limit?: number; fuzzy?: boolean } = {}): Promise<Candidate[]> {
    const { typeHint = null, context = null, limit = 8, fuzzy = true } = opts;
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
    const kindScore = "max(CASE WHEN kind = 'primary' THEN 1.0 WHEN kind = 'en' THEN 0.98 WHEN kind = 'translit' THEN 0.9 ELSE 0.95 END)::DOUBLE";
    let rs = await this.db.query(`SELECT id, ${kindScore} AS s FROM names
      WHERE name_norm IN (SELECT unnest(${list(qList)})) OR name_nospace IN (SELECT replace(unnest(${list(qList)}), ' ', '')) GROUP BY id`);
    let scores: Record<string, number> = Object.fromEntries(rs.map((r) => [r.id, Number(r.s)]));
    if (!Object.keys(scores).length) {
      const q2 = qList.flatMap((x) => [`${x} district`, `${x} city`]);
      rs = await this.db.query(`SELECT id, ${kindScore} AS s FROM names WHERE name_norm IN (SELECT unnest(${list(q2)})) GROUP BY id`);
      scores = Object.fromEntries(rs.map((r) => [r.id, Number(r.s) * 0.98]));
    }
    if (fuzzy && !Object.keys(scores).length && n.length >= 4) {
      rs = await this.db.query(`SELECT n.id, max(jaro_winkler_similarity(n.name_norm, ${q(n)})) AS s
        FROM names n JOIN divisions d ON d.id = n.id
        WHERE d.subtype IN ('country', 'region', 'county', 'locality', 'macrohood', 'neighborhood')
          AND coalesce(d.class, '') NOT IN ('hamlet') AND n.name_norm[1] = ${q(n[0])}
          AND jaro_winkler_similarity(n.name_norm, ${q(n)}) >= 0.85
          AND damerau_levenshtein(n.name_norm, ${q(n)}) <= ${n.length >= 10 ? 2 : 1}
        GROUP BY n.id ORDER BY s DESC LIMIT 50`);
      scores = Object.fromEntries(rs.map((r) => [r.id, Number(r.s) * 0.9]));
    }
    if (!Object.keys(scores).length) return [];
    const info = await this.describe(Object.keys(scores));
    const policy = this.bundle.config.policy;
    const hint = typeHint ?? hintFromName;
    let hintSubtypes = new Set<string>();
    if (hint) {
      const h = ({ district: "district", state: "state", city: "city", town: "city", country: "country", union_territory: "union_territory" } as any)[hint] ?? hint;
      hintSubtypes = new Set(policy.admin_levels[h] ?? []);
    }
    const ctx = context ? normName(context) : "";
    const cands: Candidate[] = [];
    for (const [id, s] of Object.entries(scores)) {
      const d = info[id];
      if (!d) continue;
      if (d.subtype === "region" && policy.require_region_code && !d.region) continue;
      const prior = PRIOR[`${d.subtype}|${d.class ?? ""}`] ?? PRIOR[d.subtype] ?? 0;
      let score = s + prior;
      if (d.has_area) score += 0.1;
      if (d.population) score += Math.min(0.1, Math.log10(Math.max(d.population, 1)) / 100);
      if (hintSubtypes.size && hintSubtypes.has(d.subtype)) score += 0.5;
      if (ctx && d.ancestors.some((a: string) => normName(a).includes(ctx) || ctx.includes(normName(a)))) score += 0.3;
      if (d.country !== this.bundle.config.data.country) score -= 0.2;
      const where = d.ancestors.length ? d.ancestors.slice(-2).reverse().join(", ") : "";
      const kind = d.class ? `${d.subtype} (${d.class})` : d.subtype;
      const desc = `${d.name}: ${kind}` + (where ? ` in ${where}` : "") + (d.country === "IN" ? "" : `, country ${d.country}`);
      cands.push({ id, name: d.name, source: "overture", subtype: d.subtype, description: desc, score: Math.round(score * 1e4) / 1e4, ancestors: d.ancestor_ids });
    }
    cands.sort((a, b) => b.score - a.score || (a.id < b.id ? -1 : 1));
    return cands.slice(0, limit);
  }
}
