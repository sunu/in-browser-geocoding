// Quick check of the JS models against Python (run with: node --experimental-strip-types scripts/probe_models.ts)
import { setModelBase } from "../src/models/runtime.ts";
import { T5Frames } from "../src/models/t5.ts";
import { CrossEncoder } from "../src/models/xenc.ts";
import { frameToText } from "../src/core/frames.ts";

setModelBase(new URL("../public/models", import.meta.url).pathname);
const t5 = await T5Frames.load(true);
for (const q of ["districts near the sea in Gujarat", "half a km around Charminar", "MG Road, Bangalore", "what is the weather in Pune"]) {
  const { frames, latency } = await t5.frames(q, 4);
  console.log((latency * 1000).toFixed(0) + "ms", q, "->", frames.map((f) => `${frameToText(f)} (${f.score.toFixed(3)})`).slice(0, 2));
}
const x = await CrossEncoder.load(true);
const p = await x.probs("fill_closed_slot.predicate", "Which property of places does the text name?", { text: "near the sea" },
  { coastal: "On the sea coast (touches the sea or the ocean)", landlocked: "Not on the sea coast (landlocked, inland, no access to the sea)", none: "The text does not name any of the other options" });
console.log(p);
