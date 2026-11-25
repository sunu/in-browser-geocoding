// Bundle exported by scripts/export_web.py. The Python package is the source of truth.
import { cachedFetch } from "./cache.ts";

export interface SlotDef { type: string; options_ref?: string | null; default?: any; optional?: boolean }
export interface Template { id: string; family: string; description: string; examples: string[]; slots: Record<string, SlotDef>; dag: any }
export interface Bundle {
  config: any;
  families: Record<string, { id: string; description: string }>;
  templates: Record<string, Template>;
  options: Record<string, any>;
  categories: Record<string, { description: string; items: Record<string, { description: string; match: string[]; keywords: string[] }> }>;
  lexicon: Record<string, { aliases: string[]; members: { code: string; id: string | null }[]; notes: string }>;
  aliases: Record<string, string>;
  instructions: Record<string, string>;
  is_subquery_criteria: { true: string; false: string };
  none_option: string;
  source_options: Record<string, string>;
  predicate_dags: Record<string, any>;
  catalog: Record<string, { args: { name: string; types: string[]; required: boolean; choices_ref: string | null }[]; out: string }>;
  layers: string[];
  direction_modes: string[];
  sources: string[];
  leading_fillers: string[];
  structure_level: string[];
  rank_by: string[];
  rank_orders: string[];
  quantifiers: string[];
  /** geoparse.parse.pipeline.frame_words: words that are not place names (stop, request and template words). */
  frame_words: string[];
}

export async function loadBundle(url: string): Promise<Bundle> {
  if (typeof window === "undefined") {
    const name = "node:fs/promises";
    const fs = await import(/* @vite-ignore */ name);
    return JSON.parse(await fs.readFile(url, "utf8"));
  }
  return (await cachedFetch(url, "fallback")).json();
}

/** geoparse.config.country_policy: the defaults with the values of `policy.countries.<country>`. */
export function countryPolicy(policy: any, country: string | null | undefined): any {
  return { ...policy, ...(policy.countries ?? {})[country ?? ""] };
}
