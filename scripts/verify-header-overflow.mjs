/* Header overflow regression (needs a running server and playwright-core; not part of `npm run check`):
 *   BASE_URL=http://localhost:3000 node scripts/verify-header-overflow.mjs
 * For each phone width, in light and dark, on pages that carry the header: the document must not scroll sideways
 * and the header's controls must end inside the gutter. 360 is the width that regressed when Search joined the header. */
import { chromium } from "playwright-core";

const base = process.env.BASE_URL || "http://localhost:3000";
const executablePath = process.env.CHROMIUM_PATH || undefined;
const widths = [320, 360, 390];
const paths = ["/", "/brands", "/models", "/search?q=toyota"];
const browser = await chromium.launch(executablePath ? { executablePath } : {});
let failed = 0;
for (const theme of ["light", "dark"]) for (const width of widths) for (const path of paths) {
  const page = await (await browser.newContext({ viewport: { width, height: 800 }, colorScheme: theme })).newPage();
  await page.goto(base + path, { waitUntil: "load" });
  await page.waitForTimeout(300);
  const r = await page.evaluate(() => {
    const right = (sel) => { const e = document.querySelector(sel); return e && getComputedStyle(e).display !== "none" ? Math.round(e.getBoundingClientRect().right) : 0; };
    return {
      over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      header: Math.max(right(".tdr-logo"), right(".tdr-search-btn"), right(".tdr-signup"), right(".tdr-burger")),
    };
  });
  const ok = r.over <= 0 && r.header <= width - 16;
  if (!ok) failed++;
  console.log(`${ok ? "ok  " : "FAIL"} ${theme} ${width} ${path} overflow=${r.over} headerRight=${r.header} (limit ${width - 16})`);
  await page.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
