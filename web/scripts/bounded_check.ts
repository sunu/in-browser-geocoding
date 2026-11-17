// The country layout loads only the countries of the candidates that can be in the best results (plan-019).
// Check: the same candidates as with all countries of the matching name rows loaded. Also the countries loaded.
// Run: DATA=<layout> VIEW=<0..3> npx tsx scripts/bounded_check.ts bounded|reference > x.json; ... compare a.json b.json
// One view for each process: the Node runtime of DuckDB-WASM shares its file table between instances.
import { loadBundle } from "../src/core/bundle.ts";
import { normName } from "../src/core/text.ts";
import { openDb } from "../src/execute/db.ts";
import { Gazetteer } from "../src/execute/gazetteer.ts";
import { prefixEnd } from "../src/execute/store.ts";

const pub = new URL("../public", import.meta.url).pathname;
const bundle = await loadBundle(pub + "/bundle.json");
const data = process.env.DATA ?? pub + "/countries/2026-10-21.0";
const NAMES = ["San Jose", "Victoria", "Springfield", "Paris", "London", "Lyon", "Osaka", "Hokkaido", "Recife", "Cordoba",
  "Santiago", "Alexandria", "Georgia", "Kingston", "Hamilton", "Richmond", "Aurangabad", "Vishakhapatnam", "Sprngfield", "Barcelna"];
const VIEWS: (number[] | null)[] = [null, [-125, 24, -66, 50], [-5, 41, 10, 51.5], [68, 6.5, 97.5, 37.2]];
const fmt = (cs: any[]) => cs.map((c) => `${c.id}:${c.score}`).join(" ");
const mode = process.argv[2];
if (mode === "compare") {
  const fs = await import("node:fs");
  const read = (fs_: string) => fs_.split(",").flatMap((f) => JSON.parse(fs.readFileSync(f, "utf8")));
  const [a, b] = process.argv.slice(3).map(read);
  let same = 0;
  a.forEach((x: any, i: number) => {
    const y = b[i];
    if (x.cands === y.cands) same++;
    else console.log("DIFF", x.name, JSON.stringify(x.view), "\n  got", x.cands.slice(0, 200), "\n  exp", y.cands.slice(0, 200));
    console.log(`${JSON.stringify(x.view)} ${x.name}: loaded ${x.loaded} countries (reference ${y.loaded})`);
  });
  console.log(`same candidates ${same}/${a.length}`);
  process.exit(0);
}
const out: any[] = [];
for (const view of process.env.VIEW ? [VIEWS[Number(process.env.VIEW)]] : VIEWS) {
  const g = new Gazetteer(await openDb(data, undefined, "IN"), bundle);
  const st = g.db.store!;
  for (const name of NAMES) {
    const before = st.countries.size;
    if (mode === "reference") {
      // As before plan-019: the countries of all exact matches; if none, of all rows that pass the fuzzy filter.
      const key = normName(name).replaceAll(" ", ""), k = `'${key}'`;
      const keys = [key, `${key}district`, `${key}city`];
      await st.ensureKeys(keys);
      const ex = await g.db.query(`SELECT count(*) AS n FROM name_rows WHERE key IN ('${keys.join("', '")}')`);
      if (!ex[0].n) {
        const p = [...key].slice(0, 3).join("");
        await st.loadPrefix(p);
        const rs = await g.db.query(`SELECT DISTINCT country FROM name_rows WHERE key >= '${p}' AND key < '${prefixEnd(p)}'
          AND subtype IN ('country', 'region', 'county', 'locality', 'macrohood', 'neighborhood') AND coalesce(class, '') <> 'hamlet'
          AND jaro_winkler_similarity(key, ${k}) >= 0.85
          AND damerau_levenshtein(key, ${k}) <= CASE WHEN length(${k}) >= 10 THEN 2 ELSE 1 END`);
        await st.ensureCountries(rs.map((r) => r.country));
      }
    }
    const cands = fmt(await g.search(name, { limit: 6, view }));
    out.push({ view, name, cands, loaded: st.countries.size - before });
  }
}
console.log(JSON.stringify(out));
