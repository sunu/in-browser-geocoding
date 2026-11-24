// Port of geoparse/t5/frames.py
import type { Template } from "./bundle.ts";
import { escapeRegExp, norm } from "./text.ts";

export const UNSUPPORTED = "unsupported";
// Port: plan-039 list parts ("parent = France | Spain") and the qualifier `<slot>.within`.
export const PART_SEP = " | ";
export const WITHIN = ".within";
const DISTANCE_UNITS: Record<string, number> = { m: 1, km: 1000, mi: 1609.344 };
const VALUE_SCALES: Record<string, number> = { "": 1, thousand: 1e3, lakh: 1e5, million: 1e6, crore: 1e7, billion: 1e9 };
const DIST = /^(\d+(?:\.\d+)?)\s*(m|km|mi)$/;
const VAL = /^(\d+(?:\.\d+)?)\s*(thousand|lakh|million|crore|billion)?$/;

export interface Frame { template: string; slots: Record<string, string>; score: number }

export function frameFromText(text: string, score = 0): Frame | null {
  const parts = text.trim().split(" ; ").map((p) => p.trim());
  if (!parts.length || !parts[0]) return null;
  if (parts[0] === UNSUPPORTED) return { template: UNSUPPORTED, slots: {}, score };
  const slots: Record<string, string> = {};
  for (const p of parts.slice(1)) {
    const i = p.indexOf(" = ");
    if (i < 0) return null;
    slots[p.slice(0, i).trim()] = p.slice(i + 3).trim();
  }
  return { template: parts[0], slots, score };
}

export function frameToText(f: Frame): string {
  if (f.template === UNSUPPORTED) return UNSUPPORTED;
  return [f.template, ...Object.entries(f.slots).map(([k, v]) => `${k} = ${v}`)].join(" ; ");
}

export function distanceM(text: string): number | null {
  const m = DIST.exec(text.trim());
  return m ? parseFloat(m[1]) * DISTANCE_UNITS[m[2]] : null;
}

export function valueNum(text: string): number | null {
  const m = VAL.exec(text.trim());
  return m ? parseFloat(m[1]) * VALUE_SCALES[m[2] ?? ""] : null;
}

export function slotParts(value: string): string[] { return value.split(PART_SEP).map((p) => p.trim()); }

/** Case-insensitive, whole-word span search. */
export function findSpan(query: string, span: string): [number, number] | null {
  const s = span.trim();
  if (!s) return null;
  const re = new RegExp("(?<![\\p{L}\\p{N}_])" + escapeRegExp(s) + "(?![\\p{L}\\p{N}_])", "iu");
  const m = re.exec(query);
  return m ? [m.index, m.index + m[0].length] : null;
}

export function checkFrame(f: Frame, query: string, templates: Record<string, Template>): string[] {
  if (f.template === UNSUPPORTED) return [];
  const t = templates[f.template];
  if (!t) return [`unknown template ${f.template}`];
  const problems: string[] = [];
  for (const [name, value] of Object.entries(f.slots)) {
    const sd = t.slots[name];
    if (name.endsWith(WITHIN)) {
      const base = name.slice(0, -WITHIN.length);
      if (!["region", "anchor"].includes(t.slots[base]?.type) || !(base in f.slots)) problems.push(`unknown slot ${name}`);
      else if (findSpan(query, value) === null) problems.push(`span ${value} is not in the query`);
    } else if (!sd) problems.push(`unknown slot ${name}`);
    else if (sd.type === "distance") { if (distanceM(value) === null) problems.push(`bad distance ${value}`); }
    else if (sd.type === "value") { if (valueNum(value) === null) problems.push(`bad value ${value}`); }
    else if (["region", "anchor"].includes(sd.type) && value.includes(PART_SEP)) {
      for (const p of slotParts(value)) if (findSpan(query, p) === null) problems.push(`span ${p} is not in the query`);
    } else if (findSpan(query, value) === null) problems.push(`span ${value} is not in the query`);
  }
  // Port: the same text in two region slots or list parts ("union ; a = England and Wales ; b = England and Wales").
  const texts = Object.entries(f.slots).filter(([k]) => ["region", "anchor"].includes(t.slots[k]?.type))
    .flatMap(([, v]) => slotParts(v).map((p) => p.toLowerCase()));
  if (texts.length !== new Set(texts).size) problems.push("the same text in two region slots");
  for (const [name, sd] of Object.entries(t.slots)) {
    if (!(name in f.slots) && sd.type !== "distance" && !sd.optional && (sd.default === null || sd.default === undefined))
      problems.push(`missing slot ${name}`);
  }
  return problems;
}

// Port: in a group, a frame within COVER_MARGIN of the best score that covers more of the query wins.
export const COVER_MARGIN = 0.5;

export function covered(f: Frame, query: string): number {
  const chars = new Set<number>();
  for (const v of Object.values(f.slots)) for (const p of slotParts(v)) {
    const r = findSpan(query, p);
    if (r) for (let i = r[0]; i < r[1]; i++) chars.add(i);
  }
  return chars.size;
}

export function groupFrames(frames: Frame[], query: string, templates: Record<string, Template>, margin: number): Frame[] {
  const groups = new Map<string, Frame[]>();
  for (const f of frames) {
    if (f.template === UNSUPPORTED || checkFrame(f, query, templates).length) continue;
    const t = templates[f.template];
    const open = Object.entries(f.slots)
      .filter(([k]) => k.endsWith(WITHIN) || (t.slots[k] && (t.slots[k].type === "region" || t.slots[k].type === "anchor")))
      .map(([k, v]) => [k, v.toLowerCase()] as [string, string])
      .sort((a, b) => (a[0] < b[0] ? -1 : 1));
    const key = JSON.stringify([f.template, open]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(f);
  }
  if (!groups.size) return [];
  const best = new Map<string, Frame>();
  for (const [key, fs] of groups) {
    const top = Math.max(...fs.map((f) => f.score));
    let pick: Frame | null = null;
    for (const f of fs) {
      if (f.score < top - COVER_MARGIN) continue;
      if (!pick || covered(f, query) > covered(pick, query) || (covered(f, query) === covered(pick, query) && f.score > pick.score)) pick = f;
    }
    best.set(key, pick!.score !== top ? { ...pick!, score: top } : pick!);
  }
  const top = Math.max(...[...best.values()].map((f) => f.score));
  return [...best.values()].filter((f) => f.score >= top - margin).sort((a, b) => b.score - a.score);
}

export interface Match { segments: Record<string, string>; feeds: Record<string, string[]>; within?: Record<string, string>; score: number; template: string; t5Score: number }

export function frameToMatch(f: Frame, query: string): Match {
  const segments: Record<string, string> = {};
  const feeds: Record<string, string[]> = {};
  const within: Record<string, string> = {};
  const inQuery = (v: string) => { const r = findSpan(query, v); return r ? query.slice(r[0], r[1]) : v; };
  for (const [name, value] of Object.entries(f.slots)) {
    if (name.endsWith(WITHIN)) { within[name.slice(0, -WITHIN.length)] = inQuery(value); continue; }
    if (name === "distance" || name === "value") segments[name] = value;
    else if (value.includes(PART_SEP)) segments[name] = slotParts(value).map(inQuery).join(PART_SEP);
    else {
      const r = findSpan(query, value);
      segments[name] = r ? query.slice(r[0], r[1]) : value;
    }
    feeds[name] = [name];
  }
  return { segments, feeds, within, score: 20 + f.score, template: f.template, t5Score: f.score };
}

export { norm };
