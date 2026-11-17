// Port of geoparse/parse/pipeline.py, T5 path only (plan-007 section 3.3):
// T5 frames -> pick_family -> pick_template -> (viable splits) -> pick_split -> slots -> DAG, with recursion.
import type { Bundle, SlotDef, Template } from "../core/bundle.ts";
import { substitute, validate } from "../core/dsl.ts";
import { distanceM, frameToMatch, frameToText, groupFrames, UNSUPPORTED, valueNum, type Match } from "../core/frames.ts";
import { lexiconMatch, norm, normalizeQuery } from "../core/text.ts";
import { Decider, type TraceRecord } from "../decisions/decider.ts";
import type { Candidate, Decision } from "../decisions/types.ts";
import type { Gazetteer } from "../execute/gazetteer.ts";
import type { Photon } from "../execute/photon.ts";
import type { T5Frames } from "../models/t5.ts";

const OPEN = new Set(["region", "anchor"]);
const CLOSED = new Set(["admin_level", "predicate", "direction", "category", "attr", "op"]);
const SIMPLE_FAMILIES = new Set(["lookup", "modifier"]);
const GEOCODER_FAMILIES = new Set(["lookup", "modifier", "features"]);
const LABELS: Record<string, string> = { region: "place or area", anchor: "place", admin_level: "level", predicate: "property",
  direction: "direction", category: "category", attr: "quantity", op: "comparison", distance: "distance", value: "number" };

export interface Unsupported { reason: string; decision?: string | null; depth: number; text: string }
export interface ParseResult {
  query: string; ok: boolean; dag: any | null; unsupported: Unsupported | null; family: string | null; template: string | null;
  slots: Record<string, any>; path: string | null; trace: TraceRecord[]; timings: Record<string, number>;
}

class Stop extends Error {
  constructor(public u: Unsupported) { super(u.reason); }
}

function stop(reason: string, depth = 0, text = "", decision: string | null = null): never {
  throw new Stop({ reason, decision, depth, text });
}

function fmt(x: number) { return x.toFixed(2); }

export class Parser {
  templates: Record<string, Template>;
  maxDepth: number;
  /** photon: geocoder for the boost of close candidates (plan-012 section 3.2). null: no boost. */
  constructor(public bundle: Bundle, public t5: T5Frames, public gaz: Gazetteer, public base: Decider, public photon: Photon | null = null) {
    this.templates = bundle.templates;
    this.maxDepth = Number(bundle.config.decisions.max_depth);
  }

  /** view: map view (xmin, ymin, xmax, ymax) for the ranking of candidates. null: data.bbox. */
  async parse(query: string, view: number[] | null = null): Promise<ParseResult> {
    const dec = this.base.fork();
    dec.view = view;
    const t0 = performance.now();
    const res: ParseResult = { query, ok: false, dag: null, unsupported: null, family: null, template: null, slots: {}, path: null, trace: [], timings: {} };
    try {
      const [dag, info] = await this.parseLevel(dec, normalizeQuery(query, this.bundle.leading_fillers), 0);
      const errors = validate(dag, this.bundle);
      if (errors.length) stop("invalid DAG: " + errors.join("; "));
      Object.assign(res, { ok: true, dag, family: info.family, template: info.template, slots: info.slots });
      res.path = SIMPLE_FAMILIES.has(info.family) && countResolves(dag) === 1 ? "simple" : "complex";
    } catch (e) {
      if (e instanceof Stop) res.unsupported = e.u;
      else res.unsupported = { reason: `error: ${(e as Error).message}`, depth: 0, text: "" };
    }
    res.trace = dec.trace;
    res.timings.parse_s = (performance.now() - t0) / 1000;
    return res;
  }

  templateOption(tid: string): string {
    const t = this.templates[tid];
    const ex = t.examples.slice(0, 2).map((e) => `'${e}'`).join("; ");
    return ex ? `${t.description}. Examples: ${ex}` : t.description;
  }

  labels(tpl: Template, m: Match): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [seg, fed] of Object.entries(m.feeds)) {
      const parts = fed.map((s) => LABELS[tpl.slots[s]?.type ?? ""] ?? s);
      out[seg] = [...new Set(parts)].join(" and ");
    }
    return out;
  }

  private async candidates(dec: Decider, text: string, depth: number) {
    const k = Number(this.bundle.config.t5.beams ?? 4);
    const { frames, latency } = await this.t5.frames(text, k);
    const groups = groupFrames(frames, text, this.templates, Number(this.bundle.config.t5.margin ?? 2));
    dec.record("generate_frames", depth, { text }, null,
      { value: groups.map(frameToText), impl: `t5:${this.t5.name}`, confidence: frames.length ? Math.exp(frames[0].score) : 0,
        trace: { beam: frames.map((f) => [frameToText(f), Math.round(f.score * 1e4) / 1e4]) } }, latency);
    const unsupported = frames.length > 0 && frames[0].template === UNSUPPORTED &&
      Math.exp(frames[0].score) >= Number(this.bundle.config.t5.unsupported_p ?? 0.5);
    const out: Record<string, Match[]> = {};
    for (const f of groups) (out[f.template] ??= []).push(frameToMatch(f, text));
    return { cands: out, unsupported };
  }

  private async parseLevel(dec: Decider, text: string, depth: number): Promise<[any, any]> {
    const lex = lexiconMatch(text, this.bundle);
    if (lex) return [{ op: "LexiconSet", args: { key: lex } }, { family: "lookup", template: "lookup_place", slots: { anchor: { lex, text } } }];
    const { cands, unsupported } = await this.candidates(dec, text, depth);
    if (unsupported) stop("the T5 model classifies the text as unsupported", depth, text, "generate_frames");
    const tids = Object.keys(cands);
    if (!tids.length) stop("the T5 model gives no usable frame", depth, text, "generate_frames");
    const tscore: Record<string, number> = {};
    for (const t of tids) tscore[t] = Math.max(...cands[t].map((m) => m.score));
    const famScore: Record<string, number> = {};
    for (const t of tids) {
      const f = this.templates[t].family;
      famScore[f] = Math.max(famScore[f] ?? -1e9, tscore[t]);
    }
    const fams: Record<string, string> = {};
    for (const f of Object.keys(famScore).sort((a, b) => famScore[b] - famScore[a])) fams[f] = this.bundle.families[f].description;
    const fd = await dec.pickFamily(text, fams, depth);
    if (dec.below("pick_family", fd)) stop(`low confidence for pick_family (${fmt(fd.confidence)})`, depth, text, "pick_family");
    const topts: Record<string, string> = {};
    for (const t of [...tids].sort((a, b) => tscore[b] - tscore[a])) if (this.templates[t].family === fd.value) topts[t] = this.templateOption(t);
    const td = await dec.pickTemplate(text, fd.value, topts, depth);
    if (dec.below("pick_template", td)) stop(`low confidence for pick_template (${fmt(td.confidence)})`, depth, text, "pick_template");
    const tpl = this.templates[td.value];
    if (tpl.family === "lookup") {
      const g = await dec.isSubquery(text, depth);
      if (g.value || dec.below("is_subquery", g)) stop("the text is not one place name, and no other template matches", depth, text, "is_subquery");
    }
    let matches = [...(cands[tpl.id] ?? [])].sort((a, b) => b.score - a.score);
    if (!matches.length) stop(`template ${tpl.id} has no valid split`, depth, text, "pick_split");
    const fills = new Map<string, Promise<Decision<string>>>();
    if (matches.length > 1) {
      matches = await this.viable(dec, tpl, matches, text, depth, fills);
      if (!matches.length) stop(`no split of the text gives valid values for the slots of ${tpl.id}`, depth, text, "fill_closed_slot");
    }
    const sd = await dec.pickSplit(text, tpl.description, matches.map((m) => m.segments), this.labels(tpl, matches[0]), depth);
    if (dec.below("pick_split", sd)) stop(`low confidence for pick_split (${fmt(sd.confidence)})`, depth, text, "pick_split");
    const match = matches[sd.index];
    const [values, slots] = await this.fill(dec, tpl, match, text, depth, fills);
    return [substitute(tpl.dag, values), { family: tpl.family, template: tpl.id, slots }];
  }

  private closedJobs(dec: Decider, tpl: Template, m: Match, text: string, depth: number, fills: Map<string, Promise<Decision<string>>>) {
    const jobs: Record<string, Promise<Decision<string>>> = {};
    for (const [name, sd] of Object.entries(tpl.slots)) {
      if (!CLOSED.has(sd.type) || !(name in m.segments)) continue;
      const seg = m.segments[name];
      const key = JSON.stringify([seg, sd.type, sd.options_ref]);
      if (!fills.has(key)) fills.set(key, dec.fillClosedSlot(seg, sd.type, sd.options_ref!, depth, text, true));
      jobs[name] = fills.get(key)!;
    }
    return jobs;
  }

  private async viable(dec: Decider, tpl: Template, matches: Match[], text: string, depth: number, fills: Map<string, Promise<Decision<string>>>) {
    const per = matches.map((m) => this.closedJobs(dec, tpl, m, text, depth, fills));
    const out: Match[] = [];
    for (let i = 0; i < matches.length; i++) {
      let ok = true;
      for (const [name, p] of Object.entries(per[i])) {
        const r = await p;
        if (dec.below("fill_closed_slot", r) || (r.value === "none" && !tpl.slots[name].optional)) { ok = false; break; }
      }
      if (ok) out.push(matches[i]);
    }
    return out;
  }

  private slotDefault(sd: SlotDef): any {
    const v = sd.default;
    if (typeof v === "string" && v.startsWith("policy.")) return Number(this.bundle.config.policy[v.slice(7)]);
    return v ?? null;
  }

  private async fill(dec: Decider, tpl: Template, m: Match, text: string, depth: number, fills: Map<string, Promise<Decision<string>>>): Promise<[Record<string, any>, Record<string, any>]> {
    const values: Record<string, any> = {};
    const slots: Record<string, any> = {};
    for (const [name, sd] of Object.entries(tpl.slots)) {
      const seg = m.segments[name];
      if (sd.type === "distance") {
        const v = seg !== undefined ? distanceM(seg) : null;
        slots[name] = v;
        values[name] = v ?? this.slotDefault(sd);
      } else if (sd.type === "value") {
        values[name] = slots[name] = seg !== undefined ? valueNum(seg) : this.slotDefault(sd);
      } else if (CLOSED.has(sd.type) && seg === undefined) {
        slots[name] = sd.default ?? null;
        values[name] = sd.type === "admin_level" && sd.default === "none" ? null : sd.default ?? null;
      }
    }
    const jobs: Record<string, Promise<any>> = { ...this.closedJobs(dec, tpl, m, text, depth, fills) };
    let levelHint: string | null = null;
    if ("level" in jobs) {
      const lv = await jobs.level;
      levelHint = lv.value !== "none" ? lv.value : null;
    }
    for (const [name, sd] of Object.entries(tpl.slots)) {
      if (!OPEN.has(sd.type)) continue;
      if (!(name in m.segments)) { values[name] = await this.defaultRegion(sd); slots[name] = null; continue; }
      const hint = tpl.id === "neighbors" ? levelHint : null;
      jobs[name] = this.region(dec, tpl, m.segments[name], text, depth, hint);
    }
    const names = Object.keys(jobs);
    const results = await Promise.all(names.map((n) => jobs[n]));
    names.forEach((name, i) => {
      const sd = tpl.slots[name];
      const r = results[i];
      if (OPEN.has(sd.type)) { [values[name], slots[name]] = r; return; }
      if (dec.below("fill_closed_slot", r)) stop(`low confidence for slot ${name} (${fmt(r.confidence)})`, depth, text, "fill_closed_slot");
      if (r.value === "none" && !sd.optional) stop(`the text '${m.segments[name]}' names no known ${sd.type}`, depth, text, "fill_closed_slot");
      if (r.value === "none") {
        values[name] = sd.type === "admin_level" ? null : sd.default ?? null;
        slots[name] = sd.default ?? null;
        return;
      }
      slots[name] = r.value;
      values[name] = sd.type === "predicate" ? this.bundle.predicate_dags[r.value] : r.value;
    });
    return [values, slots];
  }

  private async defaultRegion(sd: SlotDef) {
    if (sd.default !== "country") stop(`no default for open slot (${sd.default})`);
    const code = this.bundle.config.data.country;
    const rows = await this.gaz.db.query(`SELECT id, name FROM divisions WHERE subtype = 'country' AND country = '${code}'`);
    if (!rows.length) stop(`country ${code} is not in the extract`);
    return { op: "Resolve", args: { name: rows[0].name, source: "overture", id: rows[0].id } };
  }

  private async region(dec: Decider, tpl: Template, text: string, query: string, depth: number, typeHint: string | null): Promise<[any, any]> {
    text = text.trim().replace(/^(the|a|an|whole|entire|all of|all of the|whole of)\s+/i, "");
    const lex = lexiconMatch(text, this.bundle);
    if (lex) return [{ op: "LexiconSet", args: { key: lex } }, { lex, text }];
    const isRegion = Object.values(tpl.slots).some((s) => s.type === "region") && tpl.family !== "lookup";
    const exact = await this.gaz.search(text, { typeHint, fuzzy: false, limit: 3, view: dec.view });
    if (isRegion) {
      const d = await dec.isSubquery(text, depth);
      if (dec.below("is_subquery", d)) stop(`low confidence for is_subquery (${fmt(d.confidence)})`, depth, text, "is_subquery");
      if (d.value) {
        if (depth + 1 > this.maxDepth) stop("depth limit", depth, text);
        const [sub, info] = await this.parseLevel(dec, text, depth + 1);
        return [sub, { q: text, t: info.template, s: info.slots }];
      }
    }
    return [await this.anchor(dec, tpl, text, query, depth, typeHint, exact), text];
  }

  private async anchor(dec: Decider, tpl: Template, text: string, query: string, depth: number, typeHint: string | null, exact: Candidate[]) {
    const scope = this.bundle.config.geocoder?.anchor_scope ?? "simple_and_features";
    const allowGeocoder = scope === "all" || (depth === 0 && GEOCODER_FAMILIES.has(tpl.family));
    if (allowGeocoder) {
      const cands = exact.length ? exact : await this.gaz.search(text, { typeHint, limit: 3, view: dec.view });
      const top = cands[0];
      const sd = await dec.selectSource(text, { gazetteer_match: top?.description ?? null, gazetteer_top_score: top?.score ?? 0 }, depth);
      if (dec.below("select_source", sd)) stop(`low confidence for select_source (${fmt(sd.confidence)})`, depth, text, "select_source");
      if (sd.value === "photon") return { op: "Resolve", args: { name: text, source: "photon" } };
    }
    // No NER spans in the browser version: the whole slot text is the anchor (bind_anchor is not asked).
    let cands = await this.gaz.search(text, { typeHint, limit: 6, view: dec.view });
    if (!cands.length) stop(`cannot resolve '${text}' in the local extract`, depth, text);
    cands = await this.photonBoost(dec, text, mergeNested(cands), depth);
    let chosen = cands[0];
    if (cands.length > 1 && cands[0].score - cands[1].score < this.bundle.config.policy.ranking.close_margin) {
      const close = cands.filter((c) => cands[0].score - c.score < 0.3);
      const d = await dec.disambiguate(text, close, query, depth);
      if (dec.below("disambiguate", d)) stop(`low confidence for disambiguate (${fmt(d.confidence)})`, depth, text, "disambiguate");
      chosen = d.candidate;
    }
    const args: any = { name: text, source: "overture", id: chosen.id };
    if (typeHint) args.type_hint = typeHint;
    return { op: "Resolve", args };
  }

  /** If the two best candidates are close, add a score to the candidates that match Photon results. */
  private async photonBoost(dec: Decider, name: string, cands: Candidate[], depth: number): Promise<Candidate[]> {
    const rk = this.bundle.config.policy.ranking;
    if (!this.photon || cands.length < 2 || cands[0].score - cands[1].score >= rk.close_margin) return cands;
    const v = dec.view;
    let feats;
    try {
      feats = await this.photon.search(name, { limit: Number(rk.photon_limit), location: v?.length ? [(v[0] + v[2]) / 2, (v[1] + v[3]) / 2] : undefined });
    } catch (e) {
      dec.recordStep("photon_boost", depth, { name }, null, "rules", { error: String((e as Error).message).slice(0, 200) });
      return cands;
    }
    const ranks = await this.gaz.matchPoints(cands.map((c) => c.id), feats.map((f) => [f.lon, f.lat]));
    const boosts: Record<string, number> = {};
    for (const [id, r] of Object.entries(ranks)) if (r <= rk.photon_boost.length) boosts[id] = rk.photon_boost[r - 1];
    dec.recordStep("photon_boost", depth, { name }, boosts, "rules", { photon: feats.map((f) => f.label), ranks });
    if (!Object.keys(boosts).length) return cands;
    const out = cands.map((c) => ({ ...c, score: Math.round((c.score + (boosts[c.id] ?? 0)) * 1e4) / 1e4 }));
    out.sort((a, b) => b.score - a.score || (a.id < b.id ? -1 : 1));
    return out;
  }
}

export function mergeNested(cands: Candidate[]): Candidate[] {
  const out: Candidate[] = [];
  for (const c of cands) {
    const same = out.some((o) => norm(o.name) === norm(c.name) && (c.ancestors.includes(o.id) || o.ancestors.includes(c.id)));
    if (!same) out.push(c);
  }
  return out;
}

function countResolves(node: any): number {
  if (!node || typeof node !== "object" || !("op" in node)) return 0;
  return (node.op === "Resolve" ? 1 : 0) + Object.values(node.args ?? {}).reduce((s: number, v) => s + countResolves(v), 0);
}
