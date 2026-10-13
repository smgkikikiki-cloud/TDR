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

export type FetchOptions = { wait_for_text?: string };
export type PageFetcher = (url: string, options?: FetchOptions) => Promise<FetchOutcome>;

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

  async function fetchOnce(url: string, options?: FetchOptions): Promise<FetchOutcome> {
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
      if (options?.wait_for_text) await page.getByText(options.wait_for_text).first().waitFor({ timeout: 15_000 }).catch(() => {});
      await page.waitForTimeout(1_500);
      const text: string = await page.evaluate(() => (document.body?.innerText ?? ""));
      if (text.trim().length < 200) return { ok: false, kind: "FAILED", error: "page rendered almost no text" };
      return { ok: true, page: { url, text, content_hash: sha256(text), fetched_at: new Date().toISOString() } };
    } finally {
      await page.close().catch(() => {});
    }
  }

  return {
    fetch: async (url, options) => {
      let last: FetchOutcome = { ok: false, kind: "FAILED", error: "not attempted" };
      for (let attempt = 0; attempt < 3; attempt++) {
        try { last = await fetchOnce(url, options); } catch (e) { last = { ok: false, kind: "FAILED", error: String((e as Error).message).slice(0, 200) }; }
        if (last.ok || last.kind === "BLOCKED") return last;
        await sleep(2_000 * (attempt + 1));
      }
      return last;
    },
    close: async () => { await browser.close(); },
  };
}

// --- plain HTML and PDF adapters (no browser) -------------------------------------------------------------------------

/** Visible text of an HTML document: scripts/styles dropped, block and table-cell ends become line breaks so a table row stays one line. */
export function htmlToText(html: string): string {
  return html
    .replace(/<(script|style|noscript)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<\/(td|th)>/gi, " | ")
    .replace(/<(br|\/p|\/div|\/tr|\/li|\/h[1-6]|\/table|\/section)\b[^>]*>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<").replace(/&gt;/gi, ">").replace(/&quot;/gi, '"').replace(/&#39;/gi, "'")
    .replace(/[ \t\u00a0]+/g, " ").replace(/ ?\n ?/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

type Http = { ok: boolean; status: number; bytes: Uint8Array };
async function httpGet(url: string, fetchImpl: typeof fetch): Promise<Http> {
  const response = await fetchImpl(url, { headers: { "user-agent": USER_AGENT, "accept-language": "th,en;q=0.8" }, signal: AbortSignal.timeout(40_000) });
  return { ok: response.ok, status: response.status, bytes: new Uint8Array(await response.arrayBuffer()) };
}

/** Polite plain-HTTP fetcher shared by the HTML and PDF strategies: robots.txt honoured, one request per host per pause, a refusal is BLOCKED. */
export function openHttpFetchers(options: { pauseMs?: number; fetchImpl?: typeof fetch; pdfToText?: (bytes: Uint8Array) => Promise<string> } = {}):
  { html: PageFetcher; pdf: PageFetcher } {
  const pauseMs = options.pauseMs ?? 2_500;
  const fetchImpl = options.fetchImpl ?? fetch;
  const lastHit = new Map<string, number>();
  const robots = new Map<string, string | null>();

  async function guarded(url: string, read: (bytes: Uint8Array) => Promise<string>): Promise<FetchOutcome> {
    const u = new URL(url);
    if (!robots.has(u.origin)) {
      try { const r = await httpGet(`${u.origin}/robots.txt`, fetchImpl); robots.set(u.origin, r.ok ? new TextDecoder().decode(r.bytes) : null); }
      catch { robots.set(u.origin, null); }
    }
    const txt = robots.get(u.origin);
    if (txt && !robotsAllows(txt, u.pathname + u.search)) return { ok: false, kind: "BLOCKED", error: "robots.txt disallows this path" };
    const wait = (lastHit.get(u.host) ?? 0) + pauseMs - Date.now();
    if (wait > 0) await sleep(wait);
    lastHit.set(u.host, Date.now());
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const r = await httpGet(url, fetchImpl);
        if ([401, 403, 429].includes(r.status)) return { ok: false, kind: "BLOCKED", error: `HTTP ${r.status}` };
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const text = await read(r.bytes);
        if (text.trim().length < 100) return { ok: false, kind: "FAILED", error: "document has almost no text" };
        return { ok: true, page: { url, text, content_hash: sha256(text), fetched_at: new Date().toISOString() } };
      } catch (e) {
        if (attempt === 2) return { ok: false, kind: "FAILED", error: String((e as Error).message).slice(0, 200) };
        await sleep(2_000 * (attempt + 1));
      }
    }
    return { ok: false, kind: "FAILED", error: "not attempted" };
  }
  const pdfToText = options.pdfToText ?? (async (bytes) => {
    // poppler's pdftotext (present on GitHub's ubuntu runners); -layout keeps a price-list row on one line.
    const { execFile } = await import("node:child_process");
    const { mkdtempSync, writeFileSync, rmSync } = await import("node:fs");
    const { tmpdir } = await import("node:os");
    const dir = mkdtempSync(`${tmpdir()}/pricepdf-`);
    try {
      writeFileSync(`${dir}/in.pdf`, bytes);
      return await new Promise<string>((resolve, reject) =>
        execFile("pdftotext", ["-layout", `${dir}/in.pdf`, "-"], { maxBuffer: 64 * 1024 * 1024 }, (err: Error | null, out: string) => (err ? reject(err) : resolve(out))));
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
  return {
    html: (url) => guarded(url, async (b) => htmlToText(new TextDecoder().decode(b))),
    pdf: (url) => guarded(url, pdfToText),
  };
}
