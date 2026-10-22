// Screenshot of the page after one query (software WebGL). Needs the dev server on :5173.
// Run: npx tsx scripts/screenshot.ts "districts near the sea in Gujarat"
import { chromium } from "playwright";
const query = process.argv[2] ?? "districts near the sea in Gujarat";
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 760 } });
await page.goto("http://localhost:5173/");
await page.waitForFunction(() => document.getElementById("status")!.textContent!.startsWith("Ready"), null, { timeout: 600000 });
await page.fill("#q", query);
await page.click("#go");
await page.waitForFunction(() => !(document.getElementById("go") as HTMLButtonElement).disabled, null, { timeout: 300000 });
await page.waitForTimeout(4000);
await page.screenshot({ path: "test/screenshot.png" });
await browser.close();
