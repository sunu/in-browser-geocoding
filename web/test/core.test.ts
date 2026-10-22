import { describe, expect, it } from "vitest";
import { checkFrame, distanceM, findSpan, frameFromText, frameToText, groupFrames, valueNum } from "../src/core/frames.ts";
import { keywordHits } from "../src/core/keywords.ts";
import { normalizeQuery, normName } from "../src/core/text.ts";
import { substitute } from "../src/core/dsl.ts";
import { pair, stateText } from "../src/models/xenc.ts";

const T: any = {
  buffer: { id: "buffer", family: "modifier", description: "", examples: [], slots: { distance: { type: "distance", default: "policy.default_near_m" }, target: { type: "region" } }, dag: null },
  lookup_place: { id: "lookup_place", family: "lookup", description: "", examples: [], slots: { anchor: { type: "anchor" } }, dag: null },
};

describe("frames (same as geoparse/t5/frames.py)", () => {
  it("round-trips and parses quantities", () => {
    const t = "children_with_predicate ; level = districts ; pred = near the sea ; parent = Gujarat";
    expect(frameToText(frameFromText(t)!)).toBe(t);
    expect(distanceM("0.5 km")).toBe(500);
    expect(distanceM("2 kilometres")).toBeNull();
    expect(valueNum("30 lakh")).toBe(3e6);
  });
  it("matches spans as whole words", () => {
    expect(findSpan("districts of Kerala", "district")).toBeNull();
    expect(findSpan("districts of Kerala", "kerala")).toEqual([13, 19]);
  });
  it("groups beam frames as the pipeline does", () => {
    const q = "half a km around Charminar";
    const fs = [frameFromText("buffer ; distance = 0.5 km ; target = Charminar", -0.01)!, frameFromText("buffer ; distance = 0.6 km ; target = Charminar", -0.4)!,
      frameFromText("lookup_place ; anchor = Charminar", -1.5)!];
    expect(groupFrames(fs, q, T, 2).map(frameToText)).toEqual(["buffer ; distance = 0.5 km ; target = Charminar", "lookup_place ; anchor = Charminar"]);
    expect(checkFrame(frameFromText("buffer ; target = Hyderabad")!, q, T)[0]).toContain("not in the query");
  });
});

describe("text and keywords", () => {
  it("normalizes like Python", () => {
    expect(normalizeQuery("show me the coastal states?", ["show me the", "show me"])).toBe("coastal states");
    expect(normName("Tamil-Nadu ")).toBe("tamil nadu");
    expect(keywordHits("coastl states", ["coastal"])).toBe(1);
  });
  it("substitutes slots and drops None", () => {
    expect(substitute({ op: "Neighbors", args: { of: { $slot: "of" }, level: { $slot: "level" } } }, { of: { op: "Resolve", args: { name: "Kerala" } }, level: null }))
      .toEqual({ op: "Neighbors", args: { of: { op: "Resolve", args: { name: "Kerala" } } } });
  });
});

describe("cross-encoder input (same as geoparse/decisions/xenc_format.py)", () => {
  it("formats state and options", () => {
    expect(stateText({ text: "near the sea" })).toBe("text: near the sea");
    expect(pair("pick_split", "Which?", { query: "q" }, "s1", "a = 'b'", 1)).toEqual(["pick_split | Which? | query: q", "[rank 2] a = 'b'"]);
    expect(pair("fill_closed_slot.admin_level", "Which?", { text: "dists" }, "union_territory", "UTs", 0)[1]).toBe("union territory: UTs");
  });
});
