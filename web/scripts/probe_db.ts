import { openDb } from "../src/execute/db.ts";
import { Gazetteer } from "../src/execute/gazetteer.ts";
import { loadBundle } from "../src/core/bundle.ts";

const pub = new URL("../public", import.meta.url).pathname;
const t0 = performance.now();
const db = await openDb(pub + "/data");
console.log("load", ((performance.now() - t0) / 1000).toFixed(1), "s");
const g = new Gazetteer(db, await loadBundle(pub + "/bundle.json"));
for (const n of ["Koramangala", "bangalore", "Tamilnadu", "maharastra", "Mumbai Suburban", "UP", "Palakkad"]) {
  const t = performance.now();
  const c = await g.search(n);
  console.log(`${(performance.now() - t).toFixed(0)}ms`, n, c.slice(0, 2).map((x) => `${x.description} ${x.score}`));
}
