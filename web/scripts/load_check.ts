// Load the page in several browsers and report the status line. Needs the dev server on :5173.
// Run: npx tsx scripts/load_check.ts [chromium|webkit|firefox|chrome]...
import { chromium, firefox, webkit } from "playwright";

const which = process.argv.slice(2).length ? process.argv.slice(2) : ["chromium", "webkit", "firefox"];
for (const name of which) {
  const launcher = name === "webkit" ? webkit : name === "firefox" ? firefox : chromium;
  const browser = await launcher.launch(name === "chrome" ? { channel: "chrome" } : {});
  const page = await browser.newPage();
  const errs: string[] = [];
  const failed: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 200)); });
  page.on("requestfailed", (r) => failed.push(`${r.method()} ${r.url().slice(-40)} ${r.failure()?.errorText}`));
  const t0 = Date.now();
  await page.goto("http://localhost:5173/");
  try {
    await page.waitForFunction(() => /^Ready|failed/.test(document.getElementById("status")!.textContent!), null, { timeout: 300000 });
  } catch { /* timeout */ }
  console.log(`[${name}] ${((Date.now() - t0) / 1000).toFixed(1)}s:`, (await page.textContent("#status"))?.slice(0, 300));
  if (errs.length) console.log(`  console errors:`, errs.slice(0, 3));
  if (failed.length) console.log(`  failed requests:`, failed.slice(0, 5));
  await browser.close();
}
