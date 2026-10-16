/** Pure helpers for the News feature (no database, safe in client and check scripts). */

/** An article counts as "breaking" for this long after it is published. */
export const BREAKING_WINDOW_HOURS = 24;

export function isBreaking(publishedAt: string | null | undefined, now: number = Date.now()): boolean {
  if (!publishedAt) return false;
  const t = Date.parse(publishedAt);
  if (Number.isNaN(t)) return false;
  const age = now - t;
  return age >= 0 && age < BREAKING_WINDOW_HOURS * 3600_000;
}

/** Body text is stored as plain text; a blank line starts a new paragraph. */
export function splitParagraphs(body: string): string[] {
  return String(body || "")
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
}

export type ExternalLink = { title: string; url: string };

/** Admin textarea format: one link per line, "ชื่อลิงก์ | https://…". */
export function parseExternalLinks(text: string): ExternalLink[] {
  const out: ExternalLink[] = [];
  for (const line of String(text || "").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const bar = trimmed.lastIndexOf("|");
    const title = bar >= 0 ? trimmed.slice(0, bar).trim() : "";
    const url = (bar >= 0 ? trimmed.slice(bar + 1) : trimmed).trim();
    if (!/^https?:\/\/\S+$/i.test(url)) throw new Error(`ลิงก์ไม่ถูกต้อง: ${trimmed}`);
    out.push({ title: title || url, url });
  }
  return out;
}

export function formatExternalLinks(links: ExternalLink[] | null | undefined): string {
  return (links || []).map((l) => `${l.title} | ${l.url}`).join("\n");
}

/** Comma / newline separated tag names -> unique, trimmed, non-empty names. */
export function parseTagNames(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of String(text || "").split(/[,\n]/)) {
    const name = raw.trim().replace(/^#/, "").slice(0, 40);
    const key = name.toLowerCase();
    if (!name || seen.has(key)) continue;
    seen.add(key);
    out.push(name);
  }
  return out;
}

export function newsSlugify(value: string): string {
  const slug = value.normalize("NFKD").toLowerCase().replace(/[^a-z0-9ก-๙]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
  return slug || "news";
}
