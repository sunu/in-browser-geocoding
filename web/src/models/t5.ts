// T5 frame generator: beam search over encoder.onnx and decoder.onnx (no key-value cache).
// Same algorithm as scripts/onnx_parity.py (checked against transformers generate()).
import { frameFromText, frameToText, type Frame } from "../core/frames.ts";
import { int64, ort, readJson, session, tokenizer } from "./runtime.ts";

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

export class T5Frames {
  enc: any; dec: any; tok: any; gen: any; name = "t5";
  static async load(int8 = true): Promise<T5Frames> {
    const m = new T5Frames();
    const s = int8 ? "_int8" : "";
    [m.enc, m.dec, m.tok, m.gen] = await Promise.all([
      session("t5", `encoder${s}.onnx`), session("t5", `decoder${s}.onnx`), tokenizer("t5"), readJson("t5", "generation.json"),
    ]);
    return m;
  }

  async frames(query: string, k = 4): Promise<{ frames: Frame[]; latency: number }> {
    const t0 = performance.now();
    const o = await ort();
    const x = await this.tok(this.gen.prefix + query, { truncation: true, max_length: 64 });
    const ids = int64(x.input_ids), mask = int64(x.attention_mask);
    const S = ids.dims[1];
    const h = (await this.enc.run({
      input_ids: new o.Tensor("int64", ids.data, [1, S]), attention_mask: new o.Tensor("int64", mask.data, [1, S]),
    })).last_hidden_state;
    const H = h.dims[2];
    const eos = this.gen.eos_token_id;
    let alive: [number[], number][] = [[[this.gen.decoder_start_token_id], 0]];
    const done: [number[], number][] = [];
    for (let step = 0; step < this.gen.max_new_tokens; step++) {
      const n = alive.length, T = alive[0][0].length;
      const decIds = new BigInt64Array(n * T);
      alive.forEach(([seq], i) => seq.forEach((t, j) => (decIds[i * T + j] = BigInt(t))));
      const hRep = new Float32Array(n * S * H), mRep = new BigInt64Array(n * S);
      for (let i = 0; i < n; i++) { hRep.set(h.data as Float32Array, i * S * H); mRep.set(mask.data, i * S); }
      const logits = (await this.dec.run({
        decoder_input_ids: new o.Tensor("int64", decIds, [n, T]),
        encoder_hidden_states: new o.Tensor("float32", hRep, [n, S, H]),
        encoder_attention_mask: new o.Tensor("int64", mRep, [n, S]),
      })).logits;
      const V = logits.dims[2];
      const data = logits.data as Float32Array;
      const cands: [number[], number][] = [];
      alive.forEach(([seq, sc], i) => {
        const lp = logSoftmaxRow(data, (i * T + (T - 1)) * V, V);
        for (const t of topK(lp, 2 * k)) cands.push([[...seq, t], sc + lp[t]]);
      });
      cands.sort((a, b) => b[1] - a[1]);
      alive = [];
      for (const [seq, sc] of cands) {
        if (seq[seq.length - 1] === eos) done.push([seq, sc / (seq.length - 1)]);
        else alive.push([seq, sc]);
        if (alive.length === k) break;
      }
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
