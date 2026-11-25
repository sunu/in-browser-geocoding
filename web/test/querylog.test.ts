import { describe, expect, it } from "vitest";
import { logged, type Db, type QueryRecord } from "../src/execute/db.ts";

const fake: Db = {
  async query(sql: string) {
    if (sql.includes("fail")) throw new Error("Parser Error: fail");
    if (sql.startsWith("SELECT count(*)")) return [{ n: 30n }];
    if (sql.startsWith("SELECT COLUMNS")) return Array.from({ length: 20 }, (_, i) => ({ id: `d${i}`, name: `Place ${i}` }));
    if (sql.startsWith("SELECT name")) return [{ name: "Kerala", gj: "x".repeat(300), wkb: new Uint8Array([1]) }];
    return [];
  },
};

describe("query log", () => {
  it("keeps the rows of a statement, cut to a small size", async () => {
    const log: QueryRecord[] = [];
    const rs = await logged(fake, log).query("SELECT name FROM divisions");
    expect(rs[0].gj).toHaveLength(300);
    expect(log).toHaveLength(1);
    expect(log[0].count).toBe(1);
    expect(log[0].rows[0].gj).toHaveLength(201);
    expect(log[0].rows[0].wkb).toBe("<binary>");
  });

  it("keeps the rows of a temp table, and not its preview queries", async () => {
    const log: QueryRecord[] = [];
    await logged(fake, log).query("CREATE TEMP TABLE r1_1 AS SELECT id, name FROM divisions");
    expect(log).toHaveLength(1);
    expect(log[0].count).toBe(30);
    expect(log[0].rows).toHaveLength(20);
  });

  it("skips DROP TABLE and macros, and keeps errors", async () => {
    const log: QueryRecord[] = [];
    const db = logged(fake, log);
    await db.query("DROP TABLE IF EXISTS r1_1");
    await db.query("CREATE OR REPLACE MACRO crs84(g) AS g");
    await expect(db.query("SELECT fail")).rejects.toThrow("fail");
    expect(log.map((r) => r.error)).toEqual(["Parser Error: fail"]);
  });
});
