// Text helpers. Ports of geoparse.options.norm, geoparse.execute.data.norm_name, pipeline.normalize_query.
import type { Bundle } from "./bundle.ts";

/** geoparse.options.norm */
export function norm(text: string): string {
  return text.toLowerCase().replace(/[^\p{L}\p{N}_\s<>=&+-]/gu, " ").replace(/\s+/g, " ").trim();
}

/** geoparse.execute.data.norm_name */
export function normName(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();
}

export function ntext(s: string): string {
  return norm(s).replace(/^(the|a|an) /, "");
}

/** geoparse.parse.pipeline.normalize_query */
export function normalizeQuery(q: string, fillers: string[]): string {
  q = q.trim().replace(/[?.! ]+$/, "").trim().replace(/\s+/g, " ");
  let changed = true;
  while (changed) {
    changed = false;
    const low = q.toLowerCase();
    for (const f of fillers) {
      if (low.startsWith(f + " ") && low.length > f.length + 1) {
        q = q.slice(f.length + 1);
        changed = true;
        break;
      }
    }
  }
  return q;
}

/** geoparse.parse.pipeline.lexicon_match */
export function lexiconMatch(text: string, bundle: Bundle): string | null {
  const t = norm(text).replace(/^the /, "");
  for (const [key, entry] of Object.entries(bundle.lexicon)) {
    if (entry.aliases.some((a) => norm(a) === t)) return key;
  }
  return null;
}

export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
