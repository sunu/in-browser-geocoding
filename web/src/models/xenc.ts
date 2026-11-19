// Local cross-encoder ("local Jev", plan-006). Port of LocalClassifierProvider.probs.
import { int64, ort, readJson, session, tokenizer } from "./runtime.ts";

const OPAQUE = /^[sc]\d+$/;
const RANKED = ["pick_family", "pick_template", "pick_split"];

export function stateText(state: any): string {
  if (typeof state === "string") return `text: ${state}`;
  return Object.keys(state).sort().map((k) => {
    const v = typeof state[k] === "string" ? state[k] : pyJson(state[k]);
    return `${k}: ${v}`;
  }).join(" | ");
}

/** json.dumps(ensure_ascii=False) with Python's default separators. */
function pyJson(v: any): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "[" + v.map(pyJson).join(", ") + "]";
  if (typeof v === "object") return "{" + Object.entries(v).map(([k, x]) => JSON.stringify(k) + ": " + pyJson(x)).join(", ") + "}";
  return JSON.stringify(v);
}

export function optionText(key: string, desc: string): string {
  if (OPAQUE.test(key)) return desc;
  if (key === "true" || key === "false") return `${key}: ${desc}`;
  return `${key.replaceAll("_", " ")}: ${desc}`;
}

export function pair(decision: string, instructions: string, state: any, key: string, desc: string, position: number): [string, string] {
  let b = optionText(key, desc);
  if (RANKED.includes(decision.split(".")[0])) b = `[rank ${position + 1}] ${b}`;
  return [`${decision} | ${instructions} | ${stateText(state)}`, b];
}

export class CrossEncoder {
  sess: any; tok: any; temps: Record<string, number> = {}; inputs: string[] = []; maxLength = 128; name = "local:xenc";
  static async load(int8 = true): Promise<CrossEncoder> {
    const m = new CrossEncoder();
    let cfg: any;
    [m.sess, m.tok, m.temps, cfg] = await Promise.all([
      session("xenc", int8 ? "model_int8.onnx" : "model.onnx"), tokenizer("xenc"), readJson("xenc", "calibration.json"),
      readJson("xenc", "inputs.json"),
    ]);
    m.inputs = cfg.input_names;
    m.maxLength = cfg.max_length;
    return m;
  }

  temperature(decision: string): number {
    const parts = decision.split(".");
    for (let i = parts.length; i > 0; i--) {
      const k = parts.slice(0, i).join(".");
      if (k in this.temps) return this.temps[k];
    }
    return this.temps.default ?? 1;
  }

  async probs(decision: string, instructions: string, state: any, options: Record<string, string>): Promise<Record<string, number>> {
    const o = await ort();
    const keys = Object.keys(options);
    const pairs = keys.map((k, i) => pair(decision, instructions, state, k, options[k], i));
    const enc = await this.tok(pairs.map((p) => p[0]), { text_pair: pairs.map((p) => p[1]), padding: true, truncation: true, max_length: this.maxLength });
    const feeds: Record<string, any> = {};
    for (const n of this.inputs) {
      const t = int64(enc[n]);
      feeds[n] = new o.Tensor("int64", t.data, t.dims);
    }
    const logits = (await this.sess.run(feeds)).logits.data as Float32Array;
    const T = this.temperature(decision);
    const z = Array.from(logits).map((v) => v / T);
    const m = Math.max(...z);
    const e = z.map((v) => Math.exp(v - m));
    const s = e.reduce((a, b) => a + b, 0);
    const out: Record<string, number> = {};
    keys.forEach((k, i) => (out[k] = e[i] / s));
    return out;
  }
}
