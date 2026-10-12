/**
 * Page fetching for the price refresh. A real browser (Playwright) because several OEM sites render prices with
 * JavaScript. Polite by construction: robots.txt is honoured, one request at a time per host with a pause between,
 * a hard timeout, two retries. A refusal (robots, 401/403/429) is reported as BLOCKED and is never worked around.
 */
import { createHash } from "node:crypto";
import type { PageText } from "./extract.ts";

export type FetchOutcome =
  | { ok: true; page: PageText }
  | { ok: false; kind: "BLOCKED" | "FAILED"; error: string };

export type PageFetcher = (url: string) => Promise<FetchOutcome>;

export const USER_AGENT = "TDR-PriceBot/1.0 (+https://github.com/smgkikikiki-cloud/TDR)";

/** Minimal robots.txt reader: our own group if there is one, else `*`; longest matching Allow/Disallow prefix wins. */
export function robotsAllows(robotsTxt: string, path: string): boolean {
  type Group = { agents: string[]; rules: { allow: boolean; prefix: string }[] };
  const groups: Group[] = [];
  let current: Group | null = null;
  let lastWasAgent = false;
  for (const raw of robotsTxt.split(/\r?\n/)) {
    const m = /^([a-z-]+)\s*:\s*(.*)$/i.exec(raw.replace(/#.*/, "").trim());
    if (!m) continue;
    const key = m[1].toLowerCase();
    const value = m[2].trim();
    if (key === "user-agent") {
      if (!current || !lastWasAgent) { current = { agents: [], rules: [] }; groups.push(current); }
      current.agents.push(value.toLowerCase());
      lastWasAgent = true;
    } else {
      lastWasAgent = false;
      if (current && (key === "disallow" || key === "allow") && value) current.rules.push({ allow: key === "allow", prefix: value });
    }
  }
  const own = groups.filter((g) => g.agents.some((a) => a !== "*" && "tdr-pricebot".includes(a)));
  const chosen = own.length ? own : groups.filter((g) => g.agents.includes("*"));
  let best: { allow: boolean; len: number } | null = null;
  for (const rule of chosen.flatMap((g) => g.rules)) {
    const prefix = rule.prefix.replace(/\*.*$/, "").replace(/\$$/, "");
    if (prefix && path.startsWith(prefix) && (!best || prefix.length > best.len)) best = { allow: rule.allow, len: prefix.length };
  }
  return best ? best.allow : true;
}

export const sha256 = (text: string) => `sha256:${createHash("sha256").update(text).digest("hex")}`;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export type BrowserFetcher = { fetch: PageFetcher; close: () => Promise<void> };

export async function openBrowserFetcher(options: { pauseMs?: number; timeoutMs?: number } = {}): Promise<BrowserFetcher> {
  const pauseMs = options.pauseMs ?? 2_500;
  const timeoutMs = options.timeoutMs ?? 40_000;
  // Installed by the workflow (`npm install --no-save playwright`), not a project dependency; the name is a variable so tsc does not need it.
  const moduleName = "playwright";
  const { chromium } = (await import(moduleName)) as any;
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ userAgent: USER_AGENT, locale: "th-TH" });
  const lastHit = new Map<string, number>();
  const robots = new Map<string, string | null>();

  async function allowed(url: URL): Promise<boolean> {
    if (!robots.has(url.origin)) {
      try {
        const r = await context.request.get(`${url.origin}/robots.txt`, { timeout: 15_000 });
        robots.set(url.origin, r.ok() ? await r.text() : null);   // no robots.txt = no restriction
      } catch { robots.set(url.origin, null); }
    }
    const txt = robots.get(url.origin);
    return txt ? robotsAllows(txt, url.pathname + url.search) : true;
  }

  async function fetchOnce(url: string): Promise<FetchOutcome> {
    const u = new URL(url);
    if (!(await allowed(u))) return { ok: false, kind: "BLOCKED", error: "robots.txt disallows this path" };
    const wait = (lastHit.get(u.host) ?? 0) + pauseMs - Date.now();
    if (wait > 0) await sleep(wait);
    lastHit.set(u.host, Date.now());
    const page = await context.newPage();
    try {
      const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
      const status = response?.status() ?? 0;
      if ([401, 403, 429].includes(status)) return { ok: false, kind: "BLOCKED", error: `HTTP ${status}` };
      if (status >= 400) return { ok: false, kind: "FAILED", error: `HTTP ${status}` };
      await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
      await page.waitForTimeout(1_500);
      const text: string = await page.evaluate(() => (document.body?.innerText ?? ""));
      if (text.trim().length < 200) return { ok: false, kind: "FAILED", error: "page rendered almost no text" };
      return { ok: true, page: { url, text, content_hash: sha256(text), fetched_at: new Date().toISOString() } };
    } finally {
      await page.close().catch(() => {});
    }
  }

  return {
    fetch: async (url) => {
      let last: FetchOutcome = { ok: false, kind: "FAILED", error: "not attempted" };
      for (let attempt = 0; attempt < 3; attempt++) {
        try { last = await fetchOnce(url); } catch (e) { last = { ok: false, kind: "FAILED", error: String((e as Error).message).slice(0, 200) }; }
        if (last.ok || last.kind === "BLOCKED") return last;
        await sleep(2_000 * (attempt + 1));
      }
      return last;
    },
    close: async () => { await browser.close(); },
  };
}
