// Port of geoparse/dsl/schema.py: substitute and validate.
import type { Bundle } from "./bundle.ts";

export function substitute(node: any, values: Record<string, any>): any {
  if (Array.isArray(node)) return node.map((v) => substitute(v, values));
  if (node && typeof node === "object") {
    if ("$slot" in node) return values[node["$slot"]];
    const out: any = {};
    for (const [k, v] of Object.entries(node)) {
      const sv = substitute(v, values);
      if ((sv === null || sv === undefined) && k !== "op") continue;
      out[k] = sv;
    }
    if ("args" in node && !("args" in out)) out.args = {};
    return out;
  }
  return node;
}

export function outputType(node: any, bundle: Bundle): string {
  if (node && typeof node === "object" && "op" in node) return bundle.catalog[node.op].out;
  return typeof node === "number" ? "num" : "str";
}

export function choices(bundle: Bundle): Record<string, string[]> {
  const o = bundle.options;
  const leaves = Object.values(bundle.categories).flatMap((g) => Object.keys(g.items));
  return {
    admin_levels: Object.keys(o.admin_levels).filter((k) => k !== "none"),
    directions: Object.keys(o.directions), predicates: Object.keys(o.predicates), attrs: Object.keys(o.attrs),
    ops: Object.keys(o.ops), categories: leaves, lexicon: Object.keys(bundle.lexicon), layers: bundle.layers,
    direction_modes: bundle.direction_modes, sources: bundle.sources,
    natural_kinds: Object.keys(o.natural_kinds), rank_by: bundle.rank_by, rank_orders: bundle.rank_orders,
  };
}

export function validate(node: any, bundle: Bundle, path = "$"): string[] {
  if (!node || typeof node !== "object" || !("op" in node)) return [`${path}: not an operator node`];
  const spec = bundle.catalog[node.op];
  if (!spec) return [`${path}: unknown operator ${node.op}`];
  const ch = choices(bundle);
  const args = node.args ?? {};
  const errors: string[] = [];
  const known = new Set(spec.args.map((a) => a.name));
  for (const k of Object.keys(args)) if (!known.has(k)) errors.push(`${path}.${node.op}: unknown argument ${k}`);
  for (const a of spec.args) {
    if (!(a.name in args)) { if (a.required) errors.push(`${path}.${node.op}: missing argument ${a.name}`); continue; }
    const v = args[a.name];
    const p = `${path}.${node.op}.${a.name}`;
    const t = outputType(v, bundle);
    if (!a.types.includes(t)) { errors.push(`${p}: type ${t} is not one of ${a.types}`); continue; }
    if (v && typeof v === "object") errors.push(...validate(v, bundle, p));
    else if (a.choices_ref && ch[a.choices_ref] && !ch[a.choices_ref].includes(v)) errors.push(`${p}: value ${v} is not in ${a.choices_ref}`);
  }
  return errors;
}
