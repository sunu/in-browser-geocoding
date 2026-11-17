import { describe, expect, it } from "vitest";
import { cmpKey, once, prefixEnd, shardOf } from "../src/execute/store.ts";

describe("name shards", () => {
  it("compares keys by code point, as DuckDB does", () => {
    // UTF-16 order puts U+FF21 before U+1F600 (surrogate pair); code point order does not.
    expect(cmpKey("\u{1F600}", "Ａ")).toBeGreaterThan(0);
    expect("\u{1F600}" < "Ａ").toBe(true);
    expect(cmpKey("ab", "abc")).toBeLessThan(0);
    expect(cmpKey("abc", "abc")).toBe(0);
  });
  it("finds the shard of a key and the shards of a prefix", () => {
    const shards = ["a", "delhi", "kochi", "pune", "zz"].map((first, i) => ({ file: `${i}`, first }));
    expect(shardOf(shards, "aaa")).toBe(0);
    expect(shardOf(shards, "delhi")).toBe(1);
    expect(shardOf(shards, "kerala")).toBe(1);
    expect(shardOf(shards, "pune")).toBe(3);
    expect(shardOf(shards, "")).toBe(0);
    expect(prefixEnd("vis")).toBe("vit");
    expect(prefixEnd("ab\u{1F600}")).toBe("ab\u{1F601}");
    expect([shardOf(shards, "kol"), shardOf(shards, prefixEnd("kol"))]).toEqual([2, 2]);
  });
});

describe("loads", () => {
  it("runs a failed load again on the next call", async () => {
    const m = new Map<string, Promise<void>>();
    let n = 0;
    const load = async () => { if (++n === 1) throw new TypeError("Load failed"); };
    await expect(once(m, "BR", load)).rejects.toThrow("Load failed");
    await once(m, "BR", load);
    await once(m, "BR", load);
    expect(n).toBe(2);
  });
});
