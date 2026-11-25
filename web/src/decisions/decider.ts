// Port of geoparse/decisions/functions.py for the browser: providers "local" and "rules" (no Jev).
import { countryPolicy, type Bundle } from "../core/bundle.ts";
import { keywordHits } from "../core/keywords.ts";
import type { CrossEncoder } from "../models/xenc.ts";
import type { Candidate, Decision } from "./types.ts";

export interface TraceRecord {
  decision: string; depth: number; inputs: any; options: any; value: any; confidence: number; impl: string;
  latency_s: number; threshold: number; trace: Record<string, any>;
}

const STREET_WORDS = ["road", "rd", "street", "st", "marg", "lane", "highway", "station", "metro", "airport", "temple",
  "fort", "palace", "gate", "gateway", "bridge", "mall", "hospital", "college", "university", "park", "circle", "chowk",
  "junction", "stadium", "beach", "lake", "tower", "minar", "charminar", "majestic"];

function choiceConfidence(p: Record<string, number>): number {
  const n = Object.keys(p).length;
  if (n < 2) return 1;
  return (Math.max(...Object.values(p)) - 1 / n) / (1 - 1 / n);
}

function best(scores: Record<string, number>): [string, number] {
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const margin = ranked.length > 1 ? ranked[0][1] - ranked[1][1] : 1;
  return [ranked[0][0], Math.max(0, Math.min(1, 0.5 + margin / 2))];
}

export class Decider {
  trace: TraceRecord[] = [];
  /** Map view (xmin, ymin, xmax, ymax) of the parse and the country of its center. Parser.parse sets them on the
   * fork; the gazetteer uses the view, the admin level words use the country. dataLevelWords: the level words of
   * that country in the data (manifest level_words). */
  view: number[] | null = null;
  viewCountry: string | null = null;
  article = false;
  /** Names whose candidates were close (the chosen id: name, the close candidate ids); see Parser.siblingView. */
  closeAnchors = new Map<string, { name: string; cands: string[] }>();
  /** Notes for the user about the reading of the query ("read as 'France or Germany'"). */
  notes: string[] = [];
  dataLevelWords: Record<string, string[]> = {};
  constructor(public bundle: Bundle, public xenc: CrossEncoder) {}

  fork(): Decider { return new Decider(this.bundle, this.xenc); }

  /** Record a ranking step that is not a decision (for example the Photon boost) in the trace. */
  recordStep(step: string, depth: number, inputs: Record<string, any>, value: any, impl: string, trace: Record<string, any>) {
    this.trace.push({ decision: step, depth, inputs, options: null, value, confidence: 1, impl, latency_s: 0, threshold: 0, trace } as any);
  }

  providerName(decision: string): string {
    const providers = this.bundle.config.decisions.providers;
    const parts = decision.split(".");
    const keys = parts.map((_, i) => parts.slice(0, parts.length - i).join("."));
    if (parts[0] === "pick_template_flat") keys.push("pick_template");
    for (const k of keys) if (k in providers) return providers[k] === "jev" ? "local" : providers[k];
    throw new Error(`no provider for ${decision}`);
  }

  threshold(decision: string): number {
    let base = decision.split(".")[0];
    if (base === "pick_template_flat") base = "pick_template";
    return Number(this.bundle.config.decisions.thresholds[base] ?? 0);
  }

  below(decision: string, d: Decision<any>): boolean { return d.confidence < this.threshold(decision); }

  record(decision: string, depth: number, inputs: any, options: any, d: Decision<any>, dt: number) {
    this.trace.push({ decision, depth, inputs, options, value: d.value, confidence: Math.round(d.confidence * 1e4) / 1e4,
      impl: d.impl, latency_s: dt, threshold: this.threshold(decision), trace: d.trace });
  }

  private async choose(decision: string, depth: number, state: any, options: Record<string, string>, context: any, inputs: any): Promise<Decision<string>> {
    const t0 = performance.now();
    let d: Decision<string>;
    const keys = Object.keys(options);
    if (keys.length === 1) d = { value: keys[0], confidence: 1, impl: "deterministic", trace: {} };
    else if (this.providerName(decision) === "rules") d = this.rule(decision, state, options, context);
    else {
      const p = await this.xenc.probs(decision, this.bundle.instructions[decision], state, options);
      const v = Object.keys(p).reduce((a, b) => (p[a] >= p[b] ? a : b));
      d = { value: v, confidence: choiceConfidence(p), impl: this.xenc.name, trace: { state, probabilities: p } };
    }
    this.record(decision, depth, inputs, options, d, (performance.now() - t0) / 1000);
    return d;
  }

  private rule(decision: string, state: any, options: Record<string, string>, ctx: any): Decision<string> {
    const base = decision.split(".")[0];
    if (base === "select_source") {
      // A typo in a street word counts only if the gazetteer has no good match ("Minas Gerais" is not "minar").
      // An exact natural feature ("Lake Geneva"): "lake" is also a street word, but the gazetteer has the place.
      if (ctx.gazetteer_top_subtype === "natural" && (ctx.gazetteer_top_score ?? 0) >= 1.0) return { value: "overture", confidence: 0.8, impl: "rules-v1", trace: {} };
      if (keywordHits(ctx.text, STREET_WORDS, (ctx.gazetteer_top_score ?? 0) < 1.0)) return { value: "photon", confidence: 0.8, impl: "rules-v1", trace: {} };
      if ((ctx.gazetteer_top_score ?? 0) >= 1.0) return { value: "overture", confidence: 0.8, impl: "rules-v1", trace: {} };
      return { value: "photon", confidence: 0.6, impl: "rules-v1", trace: {} };
    }
    if (base === "disambiguate") {
      const s: Record<string, number> = {};
      for (const k of Object.keys(options)) s[k] = ctx.scores[k];
      const [v, c] = best(s);
      return { value: v, confidence: c, impl: "rules-v1", trace: { scores: ctx.scores } };
    }
    if (base === "bind_anchor") return { value: "whole", confidence: 0.8, impl: "rules-v1", trace: {} };
    throw new Error(`no browser rule for ${decision}; set it to "local" in the config`);
  }

  // ------------------------------------------------------------ decision functions

  pickFamily(query: string, families: Record<string, string>, depth: number) {
    return this.choose("pick_family", depth, { query }, families, {}, { query });
  }

  pickTemplate(query: string, family: string, templates: Record<string, string>, depth: number) {
    return this.choose("pick_template", depth, { query }, templates, {}, { query, family });
  }

  async pickSplit(query: string, templateDesc: string, parts: Record<string, string>[], labels: Record<string, string>, depth: number) {
    const opts: Record<string, string> = {};
    parts.forEach((p, i) => (opts[`s${i}`] = Object.entries(p).map(([k, v]) => `${labels[k] ?? k} = '${v}'`).join("; ")));
    const d = await this.choose("pick_split", depth, { query, template: templateDesc }, opts, {}, { query, template: templateDesc });
    return { ...d, index: d.value in opts ? Number(d.value.slice(1)) : 0 };
  }

  optionDescriptions(ref: string): Record<string, string> {
    if (ref === "categories") return Object.fromEntries(Object.entries(this.bundle.categories).map(([k, v]) => [k, v.description]));
    return Object.fromEntries(Object.entries(this.bundle.options[ref]).map(([k, v]: [string, any]) => [k, v.description]));
  }

  async fillClosedSlot(text: string, slotType: string, ref: string, depth: number, query: string, allowNone = true): Promise<Decision<string>> {
    const noneDesc = this.bundle.none_option;
    if (slotType === "category") {
      const groups = this.optionDescriptions("categories");
      if (allowNone) groups.none = noneDesc;
      const g = await this.choose("fill_closed_slot.category.group", depth, { text }, groups, {}, { text, slot_type: slotType, query });
      if (this.below("fill_closed_slot", g) || g.value === "none") return g;
      const items = Object.fromEntries(Object.entries(this.bundle.categories[g.value].items).map(([k, v]) => [k, v.description]));
      const leaf = await this.choose("fill_closed_slot.category", depth, { text }, items, {}, { text, slot_type: slotType, query, group: g.value });
      return { value: leaf.value, confidence: Math.min(g.confidence, leaf.confidence), impl: leaf.impl, trace: { group: g.value } };
    }
    const all = this.optionDescriptions(ref);
    const opts: Record<string, string> = {};
    for (const [k, v] of Object.entries(all)) if (k !== "none") opts[k] = v;
    if (ref === "admin_levels") {
      const level = this.levelWord(text, opts);
      if (level) {
        const d: Decision<string> = { value: level, confidence: 1, impl: "keyword", trace: { view_country: this.viewCountry } };
        this.record(`fill_closed_slot.${slotType}`, depth, { text, slot_type: slotType, query }, opts, d, 0);
        return d;
      }
    }
    if (ref === "quantifiers") {
      // Port: "both", "either": the quantifier whose keyword is in the text with no typo, if exactly one has one.
      const hits = Object.keys(opts).filter((k) => keywordHits(text, this.bundle.options.quantifiers?.[k]?.keywords ?? [], false));
      if (hits.length === 1) {
        const d: Decision<string> = { value: hits[0], confidence: 1, impl: "keyword", trace: {} };
        this.record(`fill_closed_slot.${slotType}`, depth, { text, slot_type: slotType, query }, opts, d, 0);
        return d;
      }
    }
    if (allowNone) opts.none = ref !== "admin_levels" ? noneDesc : all.none;
    let d = await this.choose(`fill_closed_slot.${slotType}`, depth, { text }, opts, {}, { text, slot_type: slotType, query });
    // Port: an option with no keyword in the text loses to the one option that has a keyword (one typo allowed).
    const kw = (k: string): string[] => this.bundle.options[ref]?.[k]?.keywords ?? [];
    if (ref !== "admin_levels" && d.value !== "none" && !keywordHits(text, kw(d.value))) {
      const hits = Object.keys(opts).filter((k) => k !== "none" && keywordHits(text, kw(k)));
      if (hits.length === 1) {
        d = { value: hits[0], confidence: 1, impl: "keyword_check", trace: { model: d.value, model_confidence: d.confidence } };
        this.record(`fill_closed_slot.${slotType}`, depth, { text, slot_type: slotType, query }, opts, d, 0);
      }
    }
    return d;
  }

  /** Port of Decider._level_word: the level whose keyword is in the text with no typo, if exactly one level has one.
   * The level words of the view country (policy.countries.<CC>.level_words and the data) belong only to their level. */
  levelWord(text: string, levels: Record<string, string>): string | null {
    const cfgWords: Record<string, string[]> = countryPolicy(this.bundle.config.policy, this.viewCountry).level_words ?? {};
    const cfgOwn = new Set(Object.values(cfgWords).flat());
    const words: Record<string, string[]> = Object.fromEntries(Object.keys(levels).map((k) =>
      [k, [...(cfgWords[k] ?? []), ...(this.dataLevelWords[k] ?? []).filter((w) => !cfgOwn.has(w))]]));
    const own = new Set(Object.values(words).flat());
    const hits = Object.keys(levels).filter((k) => keywordHits(text,
      [...(this.bundle.options.admin_levels[k]?.keywords ?? []).filter((w: string) => !own.has(w)), ...(words[k] ?? [])], false));
    return hits.length === 1 ? hits[0] : null;
  }

  async isSubquery(text: string, depth: number): Promise<Decision<boolean>> {
    const t0 = performance.now();
    const crit = this.bundle.is_subquery_criteria;
    const p = await this.xenc.probs("is_subquery", this.bundle.instructions.is_subquery, { text }, { true: crit.true, false: crit.false });
    const py = p.true;
    const d: Decision<boolean> = { value: py >= 0.5, confidence: Math.abs(2 * py - 1), impl: this.xenc.name, trace: { p_yes: py } };
    this.record("is_subquery", depth, { text }, ["true", "false"], d, (performance.now() - t0) / 1000);
    return d;
  }

  selectSource(text: string, ctx: { gazetteer_match: string | null; gazetteer_top_score: number; gazetteer_top_subtype?: string | null }, depth: number) {
    const state = { text, gazetteer_match: ctx.gazetteer_match ?? "none" };
    return this.choose("select_source", depth, state, this.bundle.source_options, { text, ...ctx }, { text, ...ctx });
  }

  async disambiguate(name: string, cands: Candidate[], query: string, depth: number) {
    const opts: Record<string, string> = {};
    const scores: Record<string, number> = {};
    cands.forEach((c, i) => { opts[`c${i}`] = c.description; scores[`c${i}`] = c.score; });
    const d = await this.choose("disambiguate", depth, { name, query }, opts, { scores }, { name, query });
    return { ...d, candidate: cands[d.value in opts ? Number(d.value.slice(1)) : 0] };
  }
}
