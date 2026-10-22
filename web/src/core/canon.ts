// Port of gold.run_gold.canon: a DAG form for comparison (Resolve by id; photon by normalized name).
import { ntext } from "./text.ts";

export function canon(dag: any): any {
  if (dag && typeof dag === "object" && "op" in dag) {
    const a = dag.args ?? {};
    if (dag.op === "Resolve") return a.source === "photon" ? ["Resolve", "photon", ntext(a.name)] : ["Resolve", a.id ?? ntext(a.name)];
    const out: Record<string, any> = {};
    for (const k of Object.keys(a).sort()) if (k !== "type_hint" && k !== "context") out[k] = canon(a[k]);
    return [dag.op, out];
  }
  return dag;
}
