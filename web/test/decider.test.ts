import { describe, expect, it } from "vitest";
import { loadBundle } from "../src/core/bundle.ts";
import { Decider } from "../src/decisions/decider.ts";

describe("admin level words", () => {
  it("gives the level of a keyword with no typo, with the words of the view country", async () => {
    const d = new Decider(await loadBundle("public/bundle.json"), null as any);
    const levels = { country: "", state: "", district: "", city: "", village: "", union_territory: "" };
    expect(d.levelWord("counties", levels)).toBe("district");
    expect(d.levelWord("prefectures", levels)).toBe("state");
    expect(d.levelWord("states and districts", levels)).toBeNull();
    expect(d.levelWord("municipalities", levels)).toBe("city");
    d.dataLevelWords = { state: ["county", "counties"], district: ["constituency", "constituencies"] };
    expect(d.levelWord("counties", levels)).toBe("state");
    d.dataLevelWords = { district: ["province", "provinces", "municipality", "municipalities"] };
    expect(d.levelWord("provinces", levels)).toBe("district");
    expect(d.levelWord("municipalities", levels)).toBe("district");
  });
});
