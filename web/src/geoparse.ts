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
  parse(q: string): Promise<ParseResult>;
  execute(dag: any): Promise<Result>;
  run(q: string): Promise<{ parse: ParseResult; result: Result | null }>;
}

export async function load(base = "", onProgress: (msg: string) => void = () => {}): Promise<Geoparse> {
  setModelBase(`${base}/models`);
  onProgress("bundle");
  const bundle = await loadBundle(`${base}/bundle.json`);
  onProgress("data, models");
  const [db, t5, xenc] = await Promise.all([
    openDb(`${base}/data`, (m) => onProgress(`data: ${m}`)),
    T5Frames.load(true).then((m) => (onProgress("T5 model loaded"), m)),
    CrossEncoder.load(true).then((m) => (onProgress("decision model loaded"), m)),
  ]);
  const parser = new Parser(bundle, t5, new Gazetteer(db, bundle), new Decider(bundle, xenc));
  const executor = new Executor(db, bundle, new Photon(bundle.config.geocoder.photon_url));
  return {
    bundle, parser, executor,
    parse: (q) => parser.parse(q),
    execute: (dag) => executor.execute(dag),
    async run(q) {
      const p = await parser.parse(q);
      return { parse: p, result: p.ok ? await executor.execute(p.dag) : null };
    },
  };
}
