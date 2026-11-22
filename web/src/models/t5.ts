// T5 frame generator: beam search over encoder.onnx and decoder.onnx (one step with a key-value cache).
// Same algorithm as scripts/onnx_parity.py (checked against transformers generate()).
import { frameFromText, frameToText, type Frame } from "../core/frames.ts";
import { int64, isNode, modelFile, ort, readJson, session, tokenizer } from "./runtime.ts";

function logSoftmaxRow(x: Float32Array, off: number, n: number): Float64Array {
  let max = -Infinity;
  for (let i = 0; i < n; i++) if (x[off + i] > max) max = x[off + i];
  let s = 0;
  for (let i = 0; i < n; i++) s += Math.exp(x[off + i] - max);
  const ls = Math.log(s);
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = x[off + i] - max - ls;
  return out;
}

function topK(x: Float64Array, k: number): number[] {
  const idx: number[] = [];
  for (let i = 0; i < x.length; i++) {
    if (idx.length < k) { idx.push(i); idx.sort((a, b) => x[b] - x[a]); }
    else if (x[i] > x[idx[k - 1]]) { idx[k - 1] = i; idx.sort((a, b) => x[b] - x[a]); }
  }
  return idx;
}

/** The rows of present ([L, 2, n, heads, t, d]) of the parent beams, in their order: the past of the next step. */
function beamPast(o: any, present: any, parents: number[]): any {
  const [L, two, n, H, T, D] = present.dims;
  const src = present.data as Float32Array, block = H * T * D;
  const out = new Float32Array(L * two * parents.length * block);
  for (let lk = 0; lk < L * two; lk++)
    parents.forEach((p, j) => out.set(src.subarray((lk * n + p) * block, (lk * n + p + 1) * block), (lk * parents.length + j) * block));
  return new o.Tensor("float32", out, [L, two, parents.length, H, T, D]);
}

export class T5Frames {
  enc: any; dec: any; tok: any; gen: any; name = "t5";
  static async load(int8 = true): Promise<T5Frames> {
    const m = new T5Frames();
    const s = int8 ? "_int8" : "";
    // The int8 encoder and decoder share one embedding table (embed.bin): one download for both sessions.
    const ext: Record<string, Promise<Uint8Array>> = int8 && !isNode ? { "embed.bin": modelFile("t5", "embed.bin") } : {};
    [m.enc, m.dec, m.tok, m.gen] = await Promise.all([
      session("t5", `encoder${s}.onnx`, ext), session("t5", `decoder${s}.onnx`, ext), tokenizer("t5"), readJson("t5", "generation.json"),
    ]);
    return m;
  }

  async frames(query: string, k = 4): Promise<{ frames: Frame[]; latency: number }> {
    const t0 = performance.now();
    const o = await ort();
    const x = await this.tok(this.gen.prefix + query, { truncation: true, max_length: 64 });
    const ids = int64(x.input_ids), mask = int64(x.attention_mask);
    const S = ids.dims[1];
    const kv = (await this.enc.run({
      input_ids: new o.Tensor("int64", ids.data, [1, S]), attention_mask: new o.Tensor("int64", mask.data, [1, S]),
    })).cross_kv;
    const [L, , , H, , D] = kv.dims;
    const maskT = new o.Tensor("int64", mask.data, [1, S]);
    const eos = this.gen.eos_token_id;
    let alive: [number[], number][] = [[[this.gen.decoder_start_token_id], 0]];
    let past = new o.Tensor("float32", new Float32Array(0), [L, 2, 1, H, 0, D]);
    const done: [number[], number][] = [];
    for (let step = 0; step < this.gen.max_new_tokens; step++) {
      const n = alive.length;
      const decIds = BigInt64Array.from(alive, ([seq]) => BigInt(seq[seq.length - 1]));
      const r = await this.dec.run({
        input_ids: new o.Tensor("int64", decIds, [n, 1]), past, cross_kv: kv, encoder_attention_mask: maskT,
      });
      const V = r.logits.dims[1];
      const data = r.logits.data as Float32Array;
      const cands: [number[], number, number][] = [];
      alive.forEach(([seq, sc], i) => {
        const lp = logSoftmaxRow(data, i * V, V);
        for (const t of topK(lp, 2 * k)) cands.push([[...seq, t], sc + lp[t], i]);
      });
      cands.sort((a, b) => b[1] - a[1]);
      alive = [];
      const parents: number[] = [];
      for (const [seq, sc, i] of cands) {
        if (seq[seq.length - 1] === eos) done.push([seq, sc / (seq.length - 1)]);
        else { alive.push([seq, sc]); parents.push(i); }
        if (alive.length === k) break;
      }
      past = beamPast(o, r.present, parents);
      if (done.length >= k) {
        const bestAlive = Math.max(-1e9, ...alive.map(([s, sc]) => sc / (s.length - 1)));
        const kth = done.map((d) => d[1]).sort((a, b) => b - a)[k - 1];
        if (kth >= bestAlive) break;
      }
      if (!alive.length) break;
    }
    done.sort((a, b) => b[1] - a[1]);
    const out: Frame[] = [];
    for (const [seq, sc] of done.slice(0, k)) {
      const f = frameFromText(this.tok.decode(seq, { skip_special_tokens: true }), sc);
      if (f && out.every((g) => frameToText(g) !== frameToText(f))) out.push(f);
    }
    return { frames: out, latency: (performance.now() - t0) / 1000 };
  }
}
