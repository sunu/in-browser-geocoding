// ONNX Runtime and tokenizers for Node.js (tests) and the browser (app). Same API in both.
import { AutoTokenizer, env } from "@huggingface/transformers";
import { readBody } from "../core/progress.ts";

export const isNode = typeof window === "undefined";

/** Import a Node.js-only module. The variable name keeps the browser bundler from following it. */
export function nodeImport(name: string): Promise<any> {
  return import(/* @vite-ignore */ name);
}

let ortMod: any = null;
export async function ort(): Promise<any> {
  if (!ortMod) {
    ortMod = isNode ? await nodeImport("onnxruntime-node") : await import("onnxruntime-web/wasm");
    if (!isNode) {
      ortMod.env.wasm.numThreads = Math.min(4, (navigator as any).hardwareConcurrency || 1);
    }
  }
  return ortMod;
}

/** Base URL (browser) or directory (Node.js) of the model files. */
let modelBase = "/models";
export function setModelBase(base: string) {
  modelBase = base.replace(/\/$/, "");
}
export function modelPath(...parts: string[]): string {
  return [modelBase, ...parts].join("/");
}

/** ONNX Runtime Web cannot run one session twice at the same time. Queue the runs of each session. */
function serialize(sess: any): any {
  let tail: Promise<any> = Promise.resolve();
  const run = sess.run.bind(sess);
  sess.run = (feeds: any) => {
    const p = tail.then(() => run(feeds));
    tail = p.catch(() => undefined);
    return p;
  };
  return sess;
}

/** Decoded sizes of the model files (sizes.json of a deployed model folder; the files are sent with brotli, so the
 * response length is not the size). Empty for local files. */
let sizes: Promise<Record<string, number>> | null = null;
function modelSizes(): Promise<Record<string, number>> {
  sizes ??= fetch(modelPath("sizes.json")).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  return sizes;
}

export async function session(...parts: string[]): Promise<any> {
  return serialize(await createSession(...parts));
}

async function createSession(...parts: string[]): Promise<any> {
  const o = await ort();
  const opts: any = { executionProviders: isNode ? ["cpu"] : ["wasm"], graphOptimizationLevel: "all" };
  // Node.js: ORT_THREADS limits the threads of each session (parity checks in several processes).
  if (isNode && process.env.ORT_THREADS) opts.intraOpNumThreads = Number(process.env.ORT_THREADS);
  if (isNode) return o.InferenceSession.create(modelPath(...parts), opts);
  const buf = await readBody(await fetch(modelPath(...parts)), parts.join("/"), (await modelSizes())[parts.join("/")] ?? 0);
  return o.InferenceSession.create(buf, opts);
}

export async function tokenizer(name: string): Promise<any> {
  // transformers.js reads a URL with a host only as a remote model location (remoteHost), not as localModelPath.
  const remote = /^https?:\/\//.test(modelBase);
  env.allowRemoteModels = remote;
  env.allowLocalModels = !remote;
  if (remote) {
    env.remoteHost = modelBase + "/";
    env.remotePathTemplate = "{model}/";
  } else env.localModelPath = modelBase + "/";
  return AutoTokenizer.from_pretrained(name);
}

export async function readJson(...parts: string[]): Promise<any> {
  if (isNode) {
    const fs = await nodeImport("node:fs/promises");
    return JSON.parse(await fs.readFile(modelPath(...parts), "utf8"));
  }
  return (await fetch(modelPath(...parts))).json();
}

/** Tokenizer output (Tensor of int64) to a BigInt64Array and its dims. */
export function int64(t: any): { data: BigInt64Array; dims: number[] } {
  const d = t.data instanceof BigInt64Array ? t.data : BigInt64Array.from(Array.from(t.data as any, (x: any) => BigInt(x)));
  return { data: d, dims: t.dims };
}
