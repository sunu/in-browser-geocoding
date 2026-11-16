// Range-read latency of remote Parquet files in real browsers (plan-008). Needs the dev server.
// Usage: npx tsx scripts/latency_check.ts <base URL> [chromium firefox webkit]   (PAGE: page URL, default :5173)
import { chromium, firefox, webkit } from "playwright";

const NAMES = ["springfield", "london", "paris", "mumbai", "san jose", "victoria", "santa maria", "saint martin",
  "berlin", "lagos", "kyoto", "toronto", "nairobi", "lima", "kerala", "bavaria", "texas", "gujarat", "oslo", "quito"];
const PREFIXES = ["lon", "san", "ber", "mum", "kyo"];

const [base, ...rest] = process.argv.slice(2);
if (!base) throw new Error("usage: latency_check.ts <base URL> [browsers]");
const host = new URL(base).host;
const pct = (xs: number[], p: number) => [...xs].sort((a, b) => a - b)[Math.min(xs.length - 1, Math.floor(xs.length * p))];

for (const name of rest.length ? rest : ["chromium", "firefox", "webkit"]) {
  const browser = await ({ chromium, firefox, webkit } as any)[name].launch();
  for (const metadataCache of [false, true]) {
    const page = await browser.newPage();
    let reqs = 0, bytes = 0;
    page.on("requestfinished", async (req) => {
      if (new URL(req.url()).host !== host) return;
      const s = await req.sizes().catch(() => null);
      reqs++;
      bytes += s?.responseBodySize ?? 0;
    });
    await page.goto(process.env.PAGE ?? "http://localhost:5173/latency.html");
    await page.waitForFunction(() => document.getElementById("out")!.textContent === "ready", null, { timeout: 120000 });
    const rs: any[] = await page.evaluate((a) => (window as any).lookups(a), { base, names: NAMES, prefixes: PREFIXES, metadataCache });
    await page.waitForTimeout(500);
    const exact = rs.filter((r) => r.kind === "exact").map((r) => r.ms);
    const prefix = rs.filter((r) => r.kind === "prefix").map((r) => r.ms);
    console.log(`${name} metadata_cache=${metadataCache}: first ${exact[0]} ms, exact median ${pct(exact.slice(1), 0.5)} p95 ${pct(exact.slice(1), 0.95)} ms,`,
      `prefix median ${pct(prefix, 0.5)} max ${Math.max(...prefix)} ms, ${reqs} requests, ${(bytes / 1e6).toFixed(1)} MB,`,
      `${rs.filter((r) => r.kind === "exact" && r.rows === 0).length} names not found`);
    if (!metadataCache) {
      const cs: any[] = await page.evaluate((a) => (window as any).countries(a), { base, codes: ["LU", "IN", "CN"] });
      console.log(`${name} country download:`, cs.map((c) => `${c.country} ${c.mb} MB ${c.ms} ms`).join(", "));
    }
    await page.close();
  }
  await browser.close();
}
