// Plain-language text for the result panel: what the query was read as, and the decisions that made the parse.
import type { Bundle } from "../core/bundle.ts";
import type { TraceRecord } from "../decisions/decider.ts";
import type { Result } from "../execute/executor.ts";
import type { ParseResult } from "../parse/pipeline.ts";

export const esc = (s: any) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

/** Label of each slot name of the templates. */
export const SLOT_LABELS: Record<string, string> = {
  anchor: "Place", region: "Place", parent: "Inside", child: "Place", of: "Next to", other: "Near or touching",
  target: "Place", a: "Place 1", b: "Place 2", c: "Place 3", level: "Kind of division", kind: "Kind of feature",
  category: "Kind of place", pred: "Property", dir: "Direction", distance: "Distance", attr: "Quantity", by: "Ranked by",
  op: "Comparison", value: "Value", n: "How many", order: "Order", per: "In each", quant: "Any or all", places: "Places",
};

/** Question of each decision type (the part of the name before the first dot). */
export const QUESTIONS: Record<string, (t: TraceRecord) => string> = {
  generate_frames: (t) => `Which forms can “${t.inputs?.text}” have?`,
  pick_family: () => "What kind of question is this?",
  pick_template: () => "Which form of question is it?",
  pick_split: () => "Which words go to which part of the form?",
  is_subquery: (t) => `Is “${t.inputs?.text}” the name of one place, or a description of places?`,
  fill_closed_slot: (t) => `What does “${t.inputs?.text}” mean?`,
  select_source: (t) => `Where must the app look for “${t.inputs?.text}”?`,
  disambiguate: (t) => `Many places have the name “${t.inputs?.name}”. Which one is it?`,
  qualified_name: (t) => `Which place is “${t.inputs?.text}”?`,
  natural_name: (t) => `Is “${t.inputs?.text}” a natural feature?`,
  frame_override: (t) => `Does a rule change the form of “${t.inputs?.text}”?`,
  photon_boost: (t) => `Does the street search know “${t.inputs?.name}”?`,
  sibling_view: (t) => `Which “${t.inputs?.text}” is near the other places of the query?`,
  list: (t) => `Is “${t.inputs?.text}” a list of places?`,
  extend_span: (t) => `Is “${t.inputs?.from}” part of a longer place name?`,
  frame_coverage: (t) => `Which forms of “${t.inputs?.text}” use all the place names?`,
  quantifier: (t) => (t.trace.from === "default" ? "Near any of the places, or near all of them?" : `Does “${t.inputs?.text}” mean any or all of the places?`),
};

const ANSWER_RULES: Record<string, (t: TraceRecord) => string> = {
  qualified_name: (t) => `The place “${t.trace.name}” inside “${[t.trace.context].flat().join(", ")}”.`,
  natural_name: () => "Yes. The text is the exact name of a natural feature.",
  frame_override: (t) => `Yes: “${t.value}” in place of “${t.trace.from}”.`,
  photon_boost: (t) => (t.trace.error ? "The street search did not answer." : "Its answers change the order of the candidate places."),
  sibling_view: () => "A different candidate: the places of the query are nearer each other with it.",
  list: (t) => `Yes: ${[t.value].flat().join(", ")}.`,
  extend_span: (t) => `Yes: “${t.value}”.`,
  frame_coverage: (t) => `${[t.value].flat().length} of them. The others leave out ${[...new Set(Object.values<string[]>(t.trace.dropped ?? {}).flat())].map((n) => `“${n}”`).join(", ")}.`,
  quantifier: (t) => (t.value === "all" ? "All of them." : t.trace.ambiguous ? "Any of them (“and” can mean both readings; say “both” for all of them)." : "Any of them."),
};

function who(impl: string): string {
  if (impl.startsWith("t5")) return "language model";
  if (impl.includes("xenc")) return "decision model";
  if (impl === "keyword") return "keyword";
  if (impl === "deterministic") return "only one choice";
  return "rule";
}

const pct = (x: number) => `${Math.round(100 * x)}%`;

/** The top line of the panel. */
export function headline(p: ParseResult, r: Result | null): string {
  if (!p.ok) return `<span class="err">Not understood</span>`;
  if (!r) return "";
  if (!r.ok) return `<span class="err">The query was understood, but the answer failed</span>`;
  const n = r.features.length;
  if (r.kind === "geometry") return `<span class="ok">Found an area</span>`;
  if (n === 1) return `<span class="ok">Found 1 place: ${esc(r.features[0].name)}</span>`;
  return `<span class="ok">Found ${n} places</span>`;
}

function unsupportedText(p: ParseResult): string {
  const u = p.unsupported;
  if (!u) return "";
  const where = u.text && u.text !== p.query ? ` (in the part “${esc(u.text)}”)` : "";
  return `<p>The app cannot answer this query${where}. Reason: ${esc(u.reason)}.</p>`;
}

const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/** Choices with a bar for each (the first is the chosen one). */
function bars(rows: [string, number][], mono: boolean): string {
  return `<div class="rows${mono ? "" : " text"}">${rows.map(([t, p]) => `<div class="row"><div class="t"><span>${t}</span><span>${pct(p)}</span></div>
    <div class="b" aria-hidden="true"><i style="width:${pct(p)}"></i></div></div>`).join("")}</div>`;
}

function slotValue(v: any): string {
  if (v == null) return "";
  if (typeof v === "string" || typeof v === "number") return esc(v);
  if (v.q) return `“${esc(v.q)}” <span class="muted">(a description, read as its own question)</span>`;
  if (Array.isArray(v.list)) return `${v.list.map(slotValue).join(v.conj === "or" ? " or " : ", ")} <span class="muted">(a list)</span>`;
  if (v.text) return esc(v.text);
  return esc(JSON.stringify(v));
}

function distance(m: number): string {
  return m >= 1000 ? `${+(m / 1000).toFixed(2)} km` : `${m} m`;
}

/** "How the app read the query": the form and its parts. */
export function reading(p: ParseResult, bundle: Bundle): string {
  if (!p.ok || !p.template) return unsupportedText(p);
  const tpl = bundle.templates[p.template];
  const chips = Object.entries(p.slots).filter(([, v]) => v != null && v !== "none").map(([k, v]) => {
    const val = tpl?.slots[k]?.type === "distance" && typeof v === "number" ? distance(v) : slotValue(v);
    return `<span class="chip"><b>${esc(SLOT_LABELS[k] ?? k)}</b><span>${val}</span></span>`;
  });
  return `<p class="form-line">Form: <strong>${esc(p.template)}</strong> · ${esc(lower(tpl?.description ?? ""))}.</p><div class="chips">${chips.join("")}</div>`;
}

function optionText(t: TraceRecord, key: string, bundle: Bundle): string {
  if (t.decision === "is_subquery") return key === "true" ? "A description of places" : "The name of one place";
  if (t.options && !Array.isArray(t.options) && typeof t.options === "object") {
    const d = t.options[key];
    return d ? `${d}` : key;
  }
  return key;
}

function choices(t: TraceRecord, bundle: Bundle): [string, number][] {
  if (t.decision === "is_subquery" && typeof t.trace?.p_yes === "number") return [["true", t.trace.p_yes], ["false", 1 - t.trace.p_yes]];
  const p = t.trace?.probabilities as Record<string, number> | undefined;
  return p ? Object.entries(p).sort((a, b) => b[1] - a[1]) : [];
}

function answer(t: TraceRecord, bundle: Bundle): string {
  const base = t.decision.split(".")[0];
  if (base in ANSWER_RULES && !t.options) return esc(ANSWER_RULES[base](t));
  if (base === "generate_frames") {
    const beam: [string, number][] = t.trace?.beam ?? [];
    return beam.length ? bars(beam.slice(0, 4).map(([f, s]) => [esc(f), Math.exp(s)]), true) : "none";
  }
  if (t.decision === "is_subquery") return esc(optionText(t, String(t.value), bundle));
  const key = typeof t.value === "string" ? t.value : JSON.stringify(t.value);
  return esc(optionText(t, key, bundle));
}

/** The decisions of the parse as questions and answers. */
export function decisions(trace: TraceRecord[], bundle: Bundle): string {
  return trace.map((t) => {
    const base = t.decision.split(".")[0];
    const q = (QUESTIONS[base] ?? (() => t.decision))(t);
    const unsure = t.threshold > 0 && t.confidence < t.threshold;
    const cs = choices(t, bundle);
    const others = cs.length > 1 ? `<details><summary>Other choices</summary>${bars(cs.map(([k, v]) => [esc(optionText(t, k, bundle)), v]), false)}</details>` : "";
    const model = who(t.impl) === "decision model" || who(t.impl) === "language model";
    const conf = model
      ? `<span class="conf ${unsure ? "err" : ""}" title="How sure the model is"><i style="width:${pct(t.confidence)}"></i></span>
         <span class="${unsure ? "err" : "muted"}">${unsure ? "not sure" : `sure: ${pct(t.confidence)}`}</span>` : "";
    return `<div class="dec${model ? " model" : ""}" style="margin-left:${Math.min(t.depth, 4) * 14}px">
      <div class="q">${esc(q)}</div>
      <div class="a">${answer(t, bundle)}</div>
      <div class="meta"><span class="tag">${who(t.impl)}</span>${conf}</div>${others}</div>`;
  }).join("");
}

export const HOW_IT_WORKS = `<details class="how" open><summary>How this works</summary><ol>
  <li>A small language model (T5) reads your query and writes possible <b>forms</b>, for example
  “divisions of a level inside a place”, with the words of the query in the <b>parts</b> of the form.</li>
  <li>A small decision model chooses between the possible forms and finds the meaning of words such as
  “districts” or “coastal”. Some decisions are rules. Each decision shows below with how sure the model was.</li>
  <li>The form becomes a <b>plan</b> (the JSON below): steps such as “find the place”, “get its divisions”,
  “keep the coastal ones”.</li>
  <li>A database in this browser tab (DuckDB) runs the plan on map data (Overture Maps, Natural Earth). Only
  street and building names go to an outside search service (Photon).</li></ol></details>`;
