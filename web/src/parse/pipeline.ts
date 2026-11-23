// Port of geoparse/parse/pipeline.py, T5 path only (plan-007 section 3.3):
// T5 frames -> pick_family -> pick_template -> (viable splits) -> pick_split -> slots -> DAG, with recursion.
import type { Bundle, SlotDef, Template } from "../core/bundle.ts";
import { substitute, validate } from "../core/dsl.ts";
import { distanceM, findSpan, frameToMatch, frameToText, groupFrames, mergeUnionSlots, UNSUPPORTED, valueNum, type Frame, type Match } from "../core/frames.ts";
import { keywordHits } from "../core/keywords.ts";
import { lexiconMatch, norm, normalizeQuery } from "../core/text.ts";
import { Decider, type TraceRecord } from "../decisions/decider.ts";
import type { Candidate, Decision } from "../decisions/types.ts";
import type { Gazetteer } from "../execute/gazetteer.ts";
import type { Photon } from "../execute/photon.ts";
import type { T5Frames } from "../models/t5.ts";

const OPEN = new Set(["region", "anchor"]);
const CLOSED = new Set(["admin_level", "predicate", "direction", "category", "attr", "op", "natural_kind", "rank_order", "quantifier"]);
const SIMPLE_FAMILIES = new Set(["lookup", "modifier"]);
const GEOCODER_FAMILIES = new Set(["lookup", "modifier", "features"]);
const LABELS: Record<string, string> = { region: "place or area", anchor: "place", admin_level: "level", predicate: "property",
  direction: "direction", category: "category", attr: "quantity", op: "comparison", distance: "distance", value: "number",
  quantifier: "any or all" };

export interface Unsupported { reason: string; decision?: string | null; depth: number; text: string }
export interface ParseResult {
  query: string; ok: boolean; dag: any | null; unsupported: Unsupported | null; family: string | null; template: string | null;
  slots: Record<string, any>; path: string | null; trace: TraceRecord[]; timings: Record<string, number>; notes: string[];
}

class Stop extends Error {
  constructor(public u: Unsupported) { super(u.reason); }
}

function stop(reason: string, depth = 0, text = "", decision: string | null = null): never {
  throw new Stop({ reason, decision, depth, text });
}

function fmt(x: number) { return x.toFixed(2); }

// geoparse.parse.pipeline.AROUND_DEFAULT: the optional parent (first) without text is the countries around the
// other slot (second).
// geoparse.parse.pipeline.HAS_DISTANCE: a number with a distance unit in a text.
const HAS_DISTANCE = /\b\d+(?:\.\d+)?\s*(?:km|kms|kilometres?|kilometers?|m|metres?|meters?|mi|miles?)\b/i;
const AROUND_DEFAULT: Record<string, [string, string]> = { children_touching: ["parent", "other"], children_near: ["parent", "other"] };
// geoparse.parse.pipeline.LIST_SEP and LIST_MARKER: lists of places in a slot; separators are whole words with spaces.
const LIST_SEP = /\s*,\s*(?:(?:and|or|&|plus)\s+)?|\s+(?:and|or|&|n|plus|as well as|along with|together with)\s+|\s*\+\s*/gi;
const LIST_MARKER = /^(both|either|all of the|all of|each of|any one of|any of)\s+(.+)$/i;
const LIST_MARKER_QUANT: Record<string, string> = { both: "all", "all of the": "all", "all of": "all", "each of": "all", either: "any",
  "any one of": "any", "any of": "any" };
const SPACE_LIST_TEMPLATES = new Set(["shared_border"]);
// geoparse.parse.pipeline.SUB_LIST_TEMPLATES: list parts can be sub-queries ("Kerala and coastal districts of Karnataka").
const SUB_LIST_TEMPLATES = new Set(["union"]);
const WORD = /\p{L}[\p{L}\p{N}_'.-]*/gu;

/** The cuts of n separators into k groups (indexes in order), fewest first. */
function* combinations(n: number, k: number, start = 0): Generator<number[]> {
  if (k === 0) { yield []; return; }
  for (let i = start; i <= n - k; i++) for (const rest of combinations(n, k - 1, i + 1)) yield [i, ...rest];
}

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
    dec.viewCountry = (await this.gaz.view(view))[1];
    dec.dataLevelWords = this.gaz.levelWords(dec.viewCountry);
    // The query normalization removes a leading "the"; the lookup rule for natural features uses it.
    dec.article = /^\s*the\s/i.test(query);
    const t0 = performance.now();
    const res: ParseResult = { query, ok: false, dag: null, unsupported: null, family: null, template: null, slots: {}, path: null, trace: [], timings: {}, notes: [] };
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
    res.notes = [...new Set(dec.notes)];
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
    const { frames: raw, latency } = await this.t5.frames(text, k);
    // Port: a union frame needs a list separator ("madhya pradesh sans bhopal" is not a union).
    const merged = raw.map((f) => mergeUnionSlots(f, text)).filter((f) => !SUB_LIST_TEMPLATES.has(f.template)
      || new RegExp(LIST_SEP.source, "i").test(f.slots.places ?? "") || LIST_MARKER.test(f.slots.places ?? ""));
    const frames = await this.extendSlots(dec, merged, text, depth);
    const groups = await this.covering(dec, groupFrames(frames, text, this.templates, Number(this.bundle.config.t5.margin ?? 2)), text, depth);
    dec.record("generate_frames", depth, { text }, null,
      { value: groups.map(frameToText), impl: `t5:${this.t5.name}`, confidence: frames.length ? Math.exp(frames[0].score) : 0,
        trace: { beam: frames.map((f) => [frameToText(f), Math.round(f.score * 1e4) / 1e4]) } }, latency);
    const unsupported = frames.length > 0 && frames[0].template === UNSUPPORTED &&
      Math.exp(frames[0].score) >= Number(this.bundle.config.t5.unsupported_p ?? 0.5);
    const out: Record<string, Match[]> = {};
    for (const f of groups) (out[f.template] ??= []).push(frameToMatch(f, text));
    return { cands: out, unsupported };
  }

  private exactCache = new Map<string, any>();
  private _frameWords: Set<string> | null = null;
  private _nameStop: Set<string> | null = null;

  private frameWords(): Set<string> { return this._frameWords ??= new Set(this.bundle.frame_words); }

  /** Port of _name_stop: frame words and the words of the closed options. */
  private nameStop(): Set<string> {
    return this._nameStop ??= new Set([...this.frameWords(), ...this.setWords().flatMap((k) => norm(k).split(/\s+/))]);
  }

  /** Port of _exact: the top exact candidate of a name ("lexicon" for a lexicon key), or null. */
  private async exact(dec: Decider, name: string): Promise<any> {
    const key = `${name.toLowerCase()}|${(dec.view ?? []).join(",")}`;
    if (!this.exactCache.has(key)) {
      const c = await this.gaz.search(name, { fuzzy: false, limit: 1, view: dec.view });
      this.exactCache.set(key, lexiconMatch(name, this.bundle) ? "lexicon" : (c[0] ?? null));
    }
    return this.exactCache.get(key);
  }

  /** Port of _extend_slots: a region slot text plus the next 1 or 2 words, if that is an exact name ("Aravalli range"). */
  private async extendSlots(dec: Decider, frames: Frame[], text: string, depth: number): Promise<Frame[]> {
    const out: Frame[] = [];
    for (const f of frames) {
      const t = this.templates[f.template];
      if (f.template === UNSUPPORTED || !t) { out.push(f); continue; }
      const slots = { ...f.slots };
      const spans = Object.fromEntries(Object.entries(f.slots).map(([k, v]) => [k, findSpan(text, v)]));
      for (const [k, v] of Object.entries(f.slots)) {
        const r = spans[k];
        if (!r || !t.slots[k] || !["region", "anchor"].includes(t.slots[k].type)) continue;
        const m = /^\s+(\p{L}[\p{L}\p{N}_'-]*)(\s+(\p{L}[\p{L}\p{N}_'-]*))?/u.exec(text.slice(r[1]));
        if (!m) continue;
        const ends: [number, string][] = [[r[1] + m[0].length - (m[2]?.length ?? 0), m[1]]];
        if (m[2]) ends.push([r[1] + m[0].length, m[3]]);
        for (const [end, word] of ends.reverse()) {
          const longer = text.slice(r[0], end);
          if (this.frameWords().has(word.toLowerCase()) || Object.entries(spans).some(([j, o]) => j !== k && o && o[0] < end && o[1] > r[1])) continue;
          if (await this.exact(dec, longer)) {
            dec.recordStep("extend_span", depth, { text, slot: k, from: v }, longer, "rules", {});
            slots[k] = longer;
            break;
          }
        }
      }
      out.push(JSON.stringify(slots) !== JSON.stringify(f.slots) ? { ...f, slots } : f);
    }
    return out;
  }

  /** Port of _dropped_names: the exact place names of the query in no slot of the frame (1 to 4 words, 4 or more letters). */
  private async droppedNames(dec: Decider, f: Frame, text: string): Promise<string[]> {
    const covered = Object.values(f.slots).map((v) => findSpan(text, v));
    const words = [...text.matchAll(WORD)].filter((m) => !covered.some((r) => r && r[0] <= m.index! && m.index! < r[1]));
    const out: string[] = [];
    const used = new Set<number>();
    for (const n of [4, 3, 2, 1]) {
      for (let i = 0; i + n <= words.length; i++) {
        const ws = words.slice(i, i + n);
        if (ws.some((_, j) => used.has(i + j))) continue;
        // Port: only words next to each other in the query (no slot text between them).
        if (ws.slice(1).some((b, j) => /[\p{L}\p{N}_]/u.test(text.slice(ws[j].index! + ws[j][0].length, b.index!)))) continue;
        if (this.nameStop().has(ws[0][0].toLowerCase()) || this.nameStop().has(ws[n - 1][0].toLowerCase())) continue;
        const name = text.slice(ws[0].index!, ws[n - 1].index! + ws[n - 1][0].length);
        if ([...name].filter((ch) => /\p{L}/u.test(ch)).length < 4 || !(await this.exact(dec, name))) continue;
        out.push(name);
        for (let j = 0; j < n; j++) used.add(i + j);
      }
    }
    return out;
  }

  /** Port of _covering: drop the frames that leave out more exact place names than the best frame; a note if all do. */
  private async covering(dec: Decider, frames: Frame[], text: string, depth: number): Promise<Frame[]> {
    if (!frames.length) return frames;
    const dropped: string[][] = [];
    for (const f of frames) dropped.push(await this.droppedNames(dec, f, text));
    const least = Math.min(...dropped.map((d) => d.length));
    const keep = frames.filter((_, i) => dropped[i].length === least);
    if (keep.length < frames.length)
      dec.recordStep("frame_coverage", depth, { text }, keep.map(frameToText), "rules",
        { dropped: Object.fromEntries(frames.map((f, i) => [frameToText(f), dropped[i]]).filter(([, d]) => d.length)) });
    if (least) {
      const kept = dropped.filter((_, i) => dropped[i].length === least);
      const common = kept[0].filter((n) => kept.every((d) => d.includes(n))).sort();
      for (const name of common) {
        const c = await this.exact(dec, name);
        if (c && c !== "lexicon" && ["country", "dependency", "region", "county"].includes(c.subtype)) dec.notes.push(`'${name}' is not used in the result`);
      }
    }
    return keep;
  }

  private async parseLevel(dec: Decider, text: string, depth: number): Promise<[any, any]> {
    const lex = lexiconMatch(text, this.bundle);
    if (lex) return [{ op: "LexiconSet", args: { key: lex } }, { family: "lookup", template: "lookup_place", slots: { anchor: { lex, text } } }];
    const qual = await this.qualified(dec, text, depth);
    if (qual) return [qual, { family: "lookup", template: "lookup_place", slots: { anchor: qual.args.name } }];
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
    let tpl = this.templates[td.value];
    const alt = await this.frameOverride(dec, text, tpl.id, cands, tscore, depth);
    if (alt) tpl = this.templates[alt];
    const inside = tpl.id === "natural_in" ? text.trim().match(/^(.+?)\s+(?:inside|in|within)\s+(.+)$/i) : null;
    if (inside) {
      // Port: "Amazon basin inside Ecuador" is the overlap of a named natural feature and a place (intersection).
      const top = await this.gaz.search(inside[1], { fuzzy: false, limit: 1, view: dec.view });
      if (top.length && top[0].subtype === "natural") {
        dec.recordStep("frame_override", depth, { text }, "intersection", "rules", { from: tpl.id, feature: inside[1] });
        tpl = this.templates["intersection"];
        cands["intersection"] = [{ segments: { a: inside[1], b: inside[2] }, feeds: { a: ["a"], b: ["b"] }, score: 0, template: "intersection", t5Score: 0 }];
      }
    }
    if (tpl.family !== "lookup" && text.trim().split(/\s+/).length <= 4) {
      // Port: "Ganga river", "Sahara desert", "Malabar Coast" is the exact name of one natural feature.
      const top = await this.gaz.search(text, { fuzzy: false, limit: 1, view: dec.view });
      if (top.length && top[0].subtype === "natural") {
        dec.recordStep("natural_name", depth, { text }, top[0].id, "rules", { from: tpl.id });
        return [{ op: "Resolve", args: { name: text, source: "overture", id: top[0].id } },
          { family: "lookup", template: "lookup_place", slots: { anchor: text } }];
      }
    }
    if (tpl.family === "lookup" && depth === 0 && dec.article && !lexiconMatch(text, this.bundle)) {
      // Port: "the equator": with "the", an exact natural feature is the place.
      const name = text.trim();
      const nat = (await this.gaz.search(name, { fuzzy: false, limit: 5, view: dec.view })).filter((c) => c.subtype === "natural");
      if (nat.length) {
        dec.recordStep("natural_name", depth, { text }, nat[0].id, "rules", { article: true });
        return [{ op: "Resolve", args: { name, source: "overture", id: nat[0].id } }, { family: "lookup", template: "lookup_place", slots: { anchor: name } }];
      }
    }
    if (tpl.family === "lookup" && alt !== "lookup_place" && !(await this.listParts(dec, text, false))) {
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
        if (dec.below("fill_closed_slot", r) || (r.value === "none" && !this.levelFree(tpl, name))) { ok = false; break; }
      }
      if (ok) out.push(matches[i]);
    }
    return out;
  }

  /** Port of _level_free: a slot that can be empty. In the structure_level templates the executor finds the level. */
  private levelFree(tpl: Template, name: string): boolean {
    const sd = tpl.slots[name];
    return !!sd.optional || (sd.type === "admin_level" && this.bundle.structure_level.includes(tpl.id));
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
    let around: string | null = null;
    for (const [name, sd] of Object.entries(tpl.slots)) {
      if (!OPEN.has(sd.type)) continue;
      if (!(name in m.segments) && AROUND_DEFAULT[tpl.id]?.[0] === name) { around = name; continue; }
      if (!(name in m.segments)) { values[name] = await this.defaultRegion(sd, dec); slots[name] = null; continue; }
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
      if (r.value === "none" && !this.levelFree(tpl, name)) stop(`the text '${m.segments[name]}' names no known ${sd.type}`, depth, text, "fill_closed_slot");
      if (r.value === "none") {
        values[name] = sd.type === "admin_level" ? null : sd.default ?? null;
        slots[name] = sd.default ?? null;
        return;
      }
      slots[name] = r.value;
      values[name] = sd.type === "predicate" ? this.bundle.predicate_dags[r.value] : r.value;
    });
    this.quantifier(dec, tpl, m, values, slots, depth);
    await this.siblingView(dec, tpl, values, depth);
    if (around) { values[around] = await this.around(dec, tpl.slots[around], values[AROUND_DEFAULT[tpl.id][1]]); slots[around] = null; }
    if (this.bundle.structure_level.includes(tpl.id) && values.level == null && "level" in m.segments) {
      // Port: the level from the data only below a country that the text names.
      const pid = "parent" in m.segments ? values.parent?.args?.id : null;
      const subtype = pid ? (await this.gaz.describe([pid]))[pid]?.subtype : null;
      if (subtype !== "country" && subtype !== "dependency")
        stop(`the text '${m.segments.level}' names no known admin_level`, depth, text, "fill_closed_slot");
    }
    return [values, slots];
  }

  /** Port of _around: the countries whose extent overlaps the extent of the other place, else the view country. */
  private async around(dec: Decider, sd: SlotDef, other: any) {
    const oid = other?.op === "Resolve" ? other.args?.id : null;
    const codes = oid ? await this.gaz.countriesAround(oid) : [];
    if (!codes.length) return this.defaultRegion(sd, dec);
    const rows = await this.gaz.db.query(`SELECT country, id, name FROM divisions WHERE subtype = 'country'
      AND country IN (${codes.map((c) => `'${c}'`).join(", ")}) ORDER BY country`);
    let node: any = null;
    for (const r of rows) {
      const res = { op: "Resolve", args: { name: r.name, source: "overture", id: r.id } };
      node = node ? { op: "Union", args: { a: node, b: res } } : res;
    }
    return node ?? this.defaultRegion(sd, dec);
  }

  /** Port of _default_region: the country of the map view. */
  private async defaultRegion(sd: SlotDef, dec: Decider) {
    if (sd.default !== "country") stop(`no default for open slot (${sd.default})`);
    const code = dec.viewCountry ?? this.bundle.config.data.country;
    const rows = await this.gaz.db.query(`SELECT id, name FROM divisions WHERE subtype = 'country' AND country = '${code}'`);
    if (!rows.length) stop(`country ${code} is not in the extract`);
    return { op: "Resolve", args: { name: rows[0].name, source: "overture", id: rows[0].id } };
  }

  /** Port of _frame_override: union for "A and B" that is not one exact name; a frame that covers the level words. */
  private async frameOverride(dec: Decider, text: string, tid: string, cands: Record<string, Match[]>, tscore: Record<string, number>, depth: number): Promise<string | null> {
    const exactName = async (x: string) => (await this.gaz.search(x, { fuzzy: false, limit: 1, view: dec.view })).length > 0;
    const m = text.trim().match(/^(.+?)\s+(?:and|&)\s+(.+)$/i);
    if (tid === "lookup_place" && m && "union" in cands && !(await exactName(text)) && (await exactName(m[1])) && (await exactName(m[2]))) {
      dec.recordStep("frame_override", depth, { text }, "union", "rules", { from: tid });
      return "union";
    }
    // A direction word and an exact name ("Northern India"), if the whole text is not an exact name ("North Carolina").
    const rest = tid === "lookup_place" && "direction_part" in cands ? this.directionRest(text) : null;
    if (rest && !(await exactName(text)) && (await exactName(rest))) {
      dec.recordStep("frame_override", depth, { text }, "direction_part", "rules", { from: tid, direction_rest: rest });
      return "direction_part";
    }
    // The other way: one side of a place is a lookup if the whole text is an exact name ("Western Ghats").
    const name = text.trim().replace(/^the\s+/i, "");
    if (tid === "direction_part" && "lookup_place" in cands && this.directionRest(name) && (await exactName(name))) {
      dec.recordStep("frame_override", depth, { text }, "lookup_place", "rules", { from: tid, exact_name: name });
      return "lookup_place";
    }
    const levelWords = Object.values<any>(this.bundle.options.admin_levels).flatMap((v) => v.keywords ?? [])
      .filter((w: string) => new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(text));
    const covers = (t: string) => {
      const ms = cands[t] ?? [];
      if (!ms.length) return false;
      const best = ms.reduce((a, b) => (b.score > a.score ? b : a));
      const segs = Object.values(best.segments).map(String).join(" ").toLowerCase();
      return levelWords.every((w: string) => segs.includes(w.toLowerCase()));
    };
    // Not for a lookup: a level word after a place name is usually noise ("Konark Sun Temple state").
    if (tid !== "lookup_place" && levelWords.length && cands[tid]?.length && !covers(tid)) {
      const alts = Object.keys(cands).filter((t) => t !== tid && covers(t)).sort((a, b) => (tscore[b] ?? -1e9) - (tscore[a] ?? -1e9));
      if (alts.length) {
        dec.recordStep("frame_override", depth, { text }, alts[0], "rules", { from: tid, level_words: levelWords });
        return alts[0];
      }
    }
    return null;
  }

  private async region(dec: Decider, tpl: Template, text: string, query: string, depth: number, typeHint: string | null,
                       part = false): Promise<[any, any]> {
    const article = /^the\s/i.test(text.trim());
    text = text.trim().replace(/^(the|a|an|whole|entire|all of|all of the|whole of)\s+/i, "");
    // A named set first ("the Balkans" is the countries, not Natural Earth's Balkan Peninsula).
    const lex = lexiconMatch(text, this.bundle);
    if (lex) return [{ op: "LexiconSet", args: { key: lex } }, { lex, text }];
    if (article) {
      // Port: "the Godavari": an exact natural feature is the place (rivers, ranges and seas take "the").
      const nat = (await this.gaz.search(text, { fuzzy: false, limit: 5, view: dec.view })).filter((c) => c.subtype === "natural");
      if (nat.length) {
        dec.recordStep("natural_name", depth, { text }, nat[0].id, "rules", { article: true });
        return [{ op: "Resolve", args: { name: text, source: "overture", id: nat[0].id } }, text];
      }
    }
    const qual = await this.qualified(dec, text, depth);
    if (qual) return [qual, text];
    const isRegion = Object.values(tpl.slots).some((s) => s.type === "region") && tpl.family !== "lookup";
    const exact = await this.gaz.search(text, { typeHint, fuzzy: false, limit: 3, view: dec.view });
    const lst = exact.length || part ? null : await this.listParts(dec, text, SPACE_LIST_TEMPLATES.has(tpl.id), SUB_LIST_TEMPLATES.has(tpl.id));
    if (lst) return this.listRegion(dec, tpl, lst, query, depth, typeHint);
    if (SUB_LIST_TEMPLATES.has(tpl.id) && !part) stop("a union needs two or more places", depth, text, "pick_split");
    const inside = isRegion && !exact.length ? /^(.+?)\s+in\s+(.+)$/i.exec(text) : null;
    if (inside && ![inside[1], inside[2]].some((x) => keywordHits(x, this.setWords(), false))) {
      const found: boolean[] = [];
      for (const x of [inside[1], inside[2]]) found.push((await this.gaz.search(x, { fuzzy: false, limit: 1, view: dec.view })).length > 0);
      if (found.every(Boolean)) {
        // Port: "Bangladesh in Tripura": two exact names, the first not inside the second. Never a union: "in" limits
        // the area to the second name.
        dec.recordStep("not_inside", depth, { text }, inside[2], "rules", { inner: inside[1] });
        dec.notes.push(`'${inside[1]}' is not inside '${inside[2]}': the result uses '${inside[2]}'`);
        return this.region(dec, tpl, inside[2], query, depth, typeHint, true);
      }
    }
    const rest = isRegion && !exact.length ? this.directionRest(text) : null;
    if (rest && (await this.gaz.search(rest, { fuzzy: false, limit: 1, view: dec.view })).length) {
      // "northern France": a direction word and a place name. A subquery, without the model.
      dec.recordStep("is_subquery", depth, { text }, true, "rules", { direction_rest: rest });
      if (depth + 1 > this.maxDepth) stop("depth limit", depth, text);
      const [sub, info] = await this.parseLevel(dec, text, depth + 1);
      return [sub, { q: text, t: info.template, s: info.slots }];
    }
    const levelWords = Object.values<any>(this.bundle.options.admin_levels).flatMap((v) => v.keywords ?? []);
    if (isRegion && !exact.length && (keywordHits(text, levelWords, false) || HAS_DISTANCE.test(text))) {
      // Port: a set by a level or a distance ("coastal districts of Odisha"), not a place name. A sub-query.
      dec.recordStep("is_subquery", depth, { text }, true, "rules", { level_or_distance: true });
      if (depth + 1 > this.maxDepth) stop("depth limit", depth, text);
      const [sub, info] = await this.parseLevel(dec, text, depth + 1);
      return [sub, { q: text, t: info.template, s: info.slots }];
    }
    if (isRegion && exact.length && !keywordHits(text, levelWords, false)) {
      // Port: the whole text is an exact place name ("Western Ghats", "Northern Ireland"): a place, also with a direction word.
      dec.recordStep("is_subquery", depth, { text }, false, "rules", { exact_name: true });
      return [await this.anchor(dec, tpl, text, query, depth, typeHint, exact), text];
    }
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

  /** Port of _list_parts: [names, conjunction, quantifier of a leading word] of a list of named sets or exact names; the
   * cut with the fewest names wins ("Bosnia and Herzegovina and Croatia" is two names). null if not such a list. */
  async listParts(dec: Decider, text: string, allowSpace: boolean, allowSub = false): Promise<[string[], string, string | null] | null> {
    let t = text.trim();
    let marker: string | null = null;
    const m = LIST_MARKER.exec(t);
    if (m) { marker = LIST_MARKER_QUANT[m[1].toLowerCase()]; t = m[2]; }
    let seps = [...t.matchAll(LIST_SEP)];
    if (!seps.length && allowSpace) seps = [...t.matchAll(/\s+/g)];
    // Port: commas alone are not a list ("Salt Lake, Kolkata" is a qualified name).
    // Port: in a union, _qualified was tried first, so commas alone are a list there.
    if (seps.length && seps.every((s) => s[0].trim() === ",") && !allowSpace && !allowSub) return null;
    if (!seps.length || seps.length > 6) return null;
    const known = new Map<string, boolean>();
    const levelWords = Object.values<any>(this.bundle.options.admin_levels).flatMap((v) => v.keywords ?? []);
    const probe = dec.fork();  // Port: the qualified-name check, without steps in the trace
    probe.view = dec.view;
    const isSub = (p: string) => !!keywordHits(p, levelWords, false) || HAS_DISTANCE.test(p);
    const isName = async (p: string) => {
      if (!known.has(p)) {
        const q = allowSub ? p.replace(/^(the|all of the|all of|whole of)\s+/i, "") : p;
        // Port: a part with a comma is not a name if a piece is a set ("Sundarbans, 10 km around Kolkata").
        known.set(p, !!q && !q.split(",").slice(1).some(isSub) && (!!lexiconMatch(q, this.bundle)
          || (await this.gaz.search(q, { fuzzy: false, limit: 1, view: dec.view })).length > 0
          || (q.includes(",") && (await this.qualified(probe, q, 0)) !== null)));
      }
      return known.get(p)!;
    };
    const conjOf = (cut: number[]) => cut.some((i) => /\bor\b/i.test(seps[i][0])) ? "or" : "and";
    const partsOf = (cut: number[]) => {
      const parts: string[] = [];
      let start = 0;
      for (const i of cut) { parts.push(t.slice(start, seps[i].index!).trim()); start = seps[i].index! + seps[i][0].length; }
      return [...parts, t.slice(start).trim()];
    };
    // Port: exact names first; then (a union) exact names or sub-queries.
    const tests: ((p: string) => Promise<boolean>)[] = [isName];
    if (allowSub) tests.push(async (p) => (await isName(p)) || (isSub(p) && !p.includes(",")));
    for (const ok of tests) {
      for (let k = 1; k <= seps.length; k++) {
        for (const cut of combinations(seps.length, k)) {
          const parts = partsOf(cut);
          let good = true;
          for (const p of parts) if (!(await ok(p))) { good = false; break; }
          if (good) return [parts, conjOf(cut), marker];
        }
      }
    }
    if (!allowSub) return null;
    // Port: a union: the cut at all separators; a part that is not a name stays one part (typos, Photon). Spaces are not
    // separators ("Taj Mahal").
    const all = [...Array(seps.length).keys()];
    const parts = partsOf(all);
    return parts.every(Boolean) ? [parts, conjOf(all), marker] : null;
  }

  /** Port of _list_region: the Union of the places of a list. */
  private async listRegion(dec: Decider, tpl: Template, lst: [string[], string, string | null], query: string, depth: number,
                           typeHint: string | null): Promise<[any, any]> {
    const [names, conj, marker] = lst;
    dec.recordStep("list", depth, { text: names.join(" | ") }, names, "rules", { conjunction: conj, quantifier: marker });
    let node: any = null;
    const infos: any[] = [];
    for (const p of names) {
      const [dag, info] = await this.region(dec, tpl, p, query, depth, typeHint, true);
      node = node === null ? dag : { op: "Union", args: { a: node, b: dag } };
      infos.push(info);
    }
    return [node, { list: infos, conj, quant: marker }];
  }

  /** Port of _quantifier: a quantifier slot with no text gets the leading word of the list, else `any` (a note for a
   * list joined by "and"). `any` is the operator default: the DAG has the argument only for `all`. */
  private quantifier(dec: Decider, tpl: Template, m: Match, values: Record<string, any>, slots: Record<string, any>, depth: number) {
    const q = Object.keys(tpl.slots).find((n) => tpl.slots[n].type === "quantifier");
    if (!q) return;
    const lst = Object.entries(slots).find(([n, s]) => OPEN.has(tpl.slots[n]?.type) && s && typeof s === "object" && "list" in s)?.[1];
    if (!(q in m.segments) && lst?.quant) {
      values[q] = slots[q] = lst.quant;
      dec.recordStep("quantifier", depth, { text: lst.conj }, lst.quant, "rules", { from: "leading word" });
    } else if (!(q in m.segments) && lst && lst.conj === "and" && values[q] === "any") {
      dec.recordStep("quantifier", depth, { text: "and" }, "any", "rules", { from: "default", ambiguous: true });
      dec.notes.push("'and' between the places is read as 'or' (any of them); say 'both' or 'all of' for all of them");
    }
    if (values[q] === "any") values[q] = null;
  }

  /** Port of _qualified: "Paris, Texas" is the Paris inside an exact match of each later name, or null. */
  private async qualified(dec: Decider, text: string, depth: number): Promise<any | null> {
    let parts = text.split(",").map((p) => p.trim());
    let exactOnly = false;
    if (parts.length === 1) {
      // "Springfield in Illinois": exact names only, and not a set ("districts in Kerala", "hospitals in Pune").
      const m = text.trim().match(/^(.+?)\s+in\s+(.+)$/i);
      if (!m || keywordHits(m[1], this.setWords(), false)) return null;
      parts = [m[1], m[2]];
      exactOnly = true;
    }
    if (parts.length < 2 || parts.length > 3 || parts.some((p) => !p || /\band\b|&/i.test(p))) return null;
    const outer: Set<string>[] = [];
    for (const p of parts.slice(1)) {
      const ids = new Set((await this.gaz.search(p, { fuzzy: false, limit: 5, view: dec.view, full: true })).map((c) => c.id));
      if (!ids.size) return null;
      outer.push(ids);
    }
    // Port: search only in the countries of the outer places (the browser then loads only these countries).
    const outerIds = [...new Set(outer.flatMap((s) => [...s]))].sort();
    const countries = [...new Set(Object.values(await this.gaz.describe(outerIds)).map((d: any) => d.country).filter(Boolean))].sort() as string[];
    const context = parts.slice(1).join(", ");
    for (const fuzzy of exactOnly ? [false] as const : [true, "only"] as const) {
      for (const c of await this.gaz.search(parts[0], { context, limit: 20, fuzzy, view: dec.view, countries, full: true })) {
        if (outer.every((ids) => c.ancestors.some((a) => ids.has(a)))) {
          dec.recordStep("qualified_name", depth, { text }, c.id, "rules", { name: parts[0], context, fuzzy });
          return { op: "Resolve", args: { name: parts[0], source: "overture", id: c.id, context } };
        }
      }
    }
    return null;
  }

  /** Port of _set_words: admin levels, categories, predicates, directions and natural kinds. */
  private setWords(): string[] {
    const o = this.bundle.options;
    const opt = (ref: string) => Object.values<any>(o[ref]).flatMap((v) => v.keywords ?? []);
    const cats = Object.values(this.bundle.categories).flatMap((g) => Object.values(g.items).flatMap((i) => i.keywords));
    return [...opt("admin_levels"), ...cats, ...opt("predicates"), ...opt("directions"), ...opt("natural_kinds")];
  }

  /** Port of _direction_rest: the text after a leading direction word of 4 or more letters. */
  /** Port of _sibling_view: the close candidates of the places of one template are chosen together, as the combination
   * with the smallest sum of distances between the places. */
  private async siblingView(dec: Decider, tpl: Template, values: Record<string, any>, depth: number) {
    // Port: the members of a list (a Union of places) count as places of the template.
    const leaves = (v: any): any[] => (v?.op === "Union" ? [...leaves(v.args.a), ...leaves(v.args.b)] : [v]);
    const res = Object.entries(values).filter(([n]) => OPEN.has(tpl.slots[n]?.type))
      .flatMap(([n, v]) => leaves(v).map((x, i) => [`${n}.${i}`, x] as [string, any]))
      .filter(([, v]) => v?.op === "Resolve" && v.args?.source === "overture" && v.args?.id);
    if (res.length < 2 || !res.some(([, v]) => dec.closeAnchors.has(v.args.id))) return;
    const options = res.map(([, v]) => dec.closeAnchors.get(v.args.id)?.cands ?? [v.args.id]);
    const info = await this.gaz.describe([...new Set(options.flat())].sort());
    const pt = (i: string) => (info[i]?.lon != null ? [Number(info[i].lon), Number(info[i].lat)] : null);
    const dist = (a: number[], b: number[]) => Math.hypot((a[0] - b[0]) * Math.cos(((a[1] + b[1]) / 2) * Math.PI / 180), a[1] - b[1]);
    // Only places that are far apart are a wrong choice; places near each other stay (Punjab is not the Thar Desert).
    const chosen = res.map(([, v]) => pt(v.args.id));
    if (chosen.some((p) => !p)) return;
    let far = 0;
    for (let i = 0; i < chosen.length; i++) for (let j = i + 1; j < chosen.length; j++) far = Math.max(far, dist(chosen[i]!, chosen[j]!));
    if (far <= Number(this.bundle.config.policy.ranking.sibling_far_deg)) return;
    let best: string[] | null = null, bestCost = Infinity;
    const walk = (k: number, combo: string[]) => {
      if (k === options.length) {
        const ps = combo.map(pt);
        if (ps.some((p) => !p)) return;
        let cost = 0;
        for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) cost += dist(ps[i]!, ps[j]!);
        if (cost < bestCost - 1e-9) { best = [...combo]; bestCost = cost; }
        return;
      }
      for (const id of options[k]) walk(k + 1, [...combo, id]);
    };
    walk(0, []);
    (best as string[] | null)?.forEach((id, k) => {
      const v = res[k][1];
      if (id !== v.args.id) {
        dec.recordStep("sibling_view", depth, { text: v.args.name }, id, "rules", { from: v.args.id });
        v.args.id = id;
      }
    });
  }

  private directionRest(text: string): string | null {
    const kws = Object.values<any>(this.bundle.options.directions).flatMap((d) => d.keywords as string[])
      .filter((k) => k.length >= 4).sort((a, b) => b.length - a.length);
    for (const k of kws) {
      const m = text.trim().match(new RegExp(`^${k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s+(.+)$`, "i"));
      if (m) return m[1];
    }
    return null;
  }

  private async anchor(dec: Decider, tpl: Template, text: string, query: string, depth: number, typeHint: string | null, exact: Candidate[]) {
    const scope = this.bundle.config.geocoder?.anchor_scope ?? "simple_and_features";
    const allowGeocoder = scope === "all" || (depth === 0 && GEOCODER_FAMILIES.has(tpl.family));
    if (allowGeocoder) {
      const cands = exact.length ? exact : await this.gaz.search(text, { typeHint, limit: 3, view: dec.view });
      const top = cands[0];
      const sd = await dec.selectSource(text, { gazetteer_match: top?.description ?? null, gazetteer_top_score: top?.score ?? 0, gazetteer_top_subtype: top?.subtype ?? null }, depth);
      if (dec.below("select_source", sd)) stop(`low confidence for select_source (${fmt(sd.confidence)})`, depth, text, "select_source");
      if (sd.value === "photon") return { op: "Resolve", args: { name: text, source: "photon" } };
    }
    // No NER spans in the browser version: the whole slot text is the anchor (bind_anchor is not asked).
    let cands = await this.gaz.search(text, { typeHint, limit: 6, view: dec.view });
    if (!cands.length) stop(`cannot resolve '${text}' in the local extract`, depth, text);
    cands = await this.photonBoost(dec, text, mergeNested(cands), depth);
    let chosen = cands[0];
    if (cands.length > 1 && cands[0].score - cands[1].score < this.bundle.config.policy.ranking.close_margin) {
      const close = cands.filter((c) => cands[0].score - c.score < Number(this.bundle.config.policy.ranking.candidate_window));
      const d = await dec.disambiguate(text, close, query, depth);
      if (dec.below("disambiguate", d)) stop(`low confidence for disambiguate (${fmt(d.confidence)})`, depth, text, "disambiguate");
      chosen = d.candidate;
      dec.closeAnchors.set(chosen.id, { name: text, cands: close.map((c) => c.id) });
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
