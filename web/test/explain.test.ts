import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { QUESTIONS, SLOT_LABELS, sqlLog } from "../src/app/explain.ts";

describe("explain", () => {
  it("has a question for every decision and rule step of the trace", () => {
    const src = ["src/decisions/decider.ts", "src/parse/pipeline.ts"].map((f) => readFileSync(f, "utf8")).join("\n");
    const names = new Set([...src.matchAll(/(?:record|recordStep|choose)\(["`]([a-z_]+)/g)].map((m) => m[1]));
    expect(names.size).toBeGreaterThan(8);
    for (const n of names) expect(QUESTIONS, n).toHaveProperty(n);
  });

  it("has a label for every slot of the templates", () => {
    const bundle = JSON.parse(readFileSync("public/bundle.json", "utf8"));
    for (const t of Object.values<any>(bundle.templates)) for (const s of Object.keys(t.slots)) expect(SLOT_LABELS, s).toHaveProperty(s);
  });

  it("shows the SQL statements with their rows, escaped", () => {
    const html = sqlLog([{ sql: "SELECT '<b>'", ms: 1.2, count: 25, rows: [{ name: "<i>Goa</i>", id: null }] }],
      [{ sql: "SELECT x", ms: 3, count: 0, rows: [], error: "Binder Error: <x>" }]);
    expect(html).toContain("SQL queries and data (2)");
    expect(html).toContain("SELECT '&lt;b&gt;'");
    expect(html).toContain("&lt;i&gt;Goa&lt;/i&gt;");
    expect(html).not.toContain("<i>Goa");
    expect(html).toContain("The first 1 of 25 rows.");
    expect(html).toContain("Binder Error: &lt;x&gt;");
    expect(sqlLog([], [])).toBe("");
  });
});
