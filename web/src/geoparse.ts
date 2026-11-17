// Public API of the browser version: load(), parse(query), execute(dag), run(query).
import { loadBundle, type Bundle } from "./core/bundle.ts";
import { Decider } from "./decisions/decider.ts";
import { openDb } from "./execute/db.ts";
import { Executor, type Result } from "./execute/executor.ts";
import { Gazetteer } from "./execute/gazetteer.ts";
import { Photon } from "./execute/photon.ts";
import { setModelBase } from "./models/runtime.ts";
import { T5Frames } from "./models/t5.ts";
import { CrossEncoder } from "./models/xenc.ts";
import { Parser, type ParseResult } from "./parse/pipeline.ts";

export interface Geoparse {
  bundle: Bundle; parser: Parser; executor: Executor;
  /** view: map view (xmin, ymin, xmax, ymax) for the ranking of places. */
  parse(q: string, view?: number[] | null): Promise<ParseResult>;
  execute(dag: any, view?: number[] | null): Promise<Result>;
  run(q: string, view?: number[] | null): Promise<{ parse: ParseResult; result: Result | null }>;
}

/** data: URL of the data files (flat layout or country layout); default `${base}/data`.
 * opts.models: URL of the model files; default `${base}/models`. opts.dataVersion: see openDb. */
export async function load(base = "", onProgress: (msg: string) => void = () => {}, data = `${base}/data`,
                           opts: { models?: string; dataVersion?: string } = {}): Promise<Geoparse> {
  setModelBase(opts.models ?? `${base}/models`);
  onProgress("bundle");
  const bundle = await loadBundle(`${base}/bundle.json`);
  onProgress("data, models");
  const [db, t5, xenc] = await Promise.all([
    openDb(data, (m) => onProgress(`data: ${m}`), bundle.config.data.country, opts.dataVersion),
    T5Frames.load(true).then((m) => (onProgress("T5 model loaded"), m)),
    CrossEncoder.load(true).then((m) => (onProgress("decision model loaded"), m)),
  ]);
  const photon = new Photon(bundle.config.geocoder.photon_url);
  const parser = new Parser(bundle, t5, new Gazetteer(db, bundle), new Decider(bundle, xenc), photon);
  const executor = new Executor(db, bundle, photon);
  return {
    bundle, parser, executor,
    parse: (q, view = null) => parser.parse(q, view),
    execute: (dag, view = null) => executor.execute(dag, true, view),
    async run(q, view = null) {
      const p = await parser.parse(q, view);
      return { parse: p, result: p.ok ? await executor.execute(p.dag, true, view) : null };
    },
  };
}
