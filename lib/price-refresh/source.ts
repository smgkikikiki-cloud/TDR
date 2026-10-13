/**
 * Reading one playbook source (a fetched page) and combining several sources of one model.
 * Pure: page text in, evidence out. The numbers are only ever copied from the page; nothing here writes anything.
 */
import { amountsIn, classifyAmount, extractAnchored, MAX_LIST_PRICE_THB, MIN_LIST_PRICE_THB, pageTokens, resolveSemantics,
  type ExtractedPrice, type KnownTrim, type PageText } from "./extract.ts";
import type { ResolvedSource, Section } from "./playbook.ts";
import { normalizeTrimName } from "../vehicle-engine/trim-reconcile.ts";

export type SourceState = "OK" | "STALE" | "EMPTY" | "SECTION_MISSING" | "FAILED" | "SKIPPED";

export type PricedRow = ExtractedPrice & { amount_thb: number };
export type SourceRead = {
  source: ResolvedSource;
  state: SourceState;
  detail: string;
  as_of: string | null;
  page: PageText | null;
  /** LIST prices read from this source (empty when it has no price authority). */
  observations: ExtractedPrice[];
  /** Campaign / discounted prices: evidence only. */
  promotions: ExtractedPrice[];
  /** Known grades present on the page, priced or not. */
  names_seen: { trim_id: string; name: string }[];
  ambiguous: { trim_id: string; reason: string }[];
  not_found: string[];
  skipped_rows: string[];
};

export const emptyRead = (source: ResolvedSource, state: SourceState, detail: string, page: PageText | null = null): SourceRead =>
  ({ source, state, detail, as_of: null, page, observations: [], promotions: [], names_seen: [], ambiguous: [], not_found: [], skipped_rows: [] });

/** Text between two markers (case-insensitive). null = a marker the playbook relies on is not on the page. */
export function clipSection(text: string, section: Section | undefined): string | null {
  if (!section || (!section.start && !section.end)) return text;
  const lower = text.toLowerCase();
  let from = 0;
  if (section.start) {
    from = lower.indexOf(section.start.toLowerCase());
    if (from < 0) return null;
    from += section.start.length;
  }
  let to = text.length;
  if (section.end) {
    const e = lower.indexOf(section.end.toLowerCase(), from);
    if (e < 0) return null;
    to = e;
  }
  return text.slice(from, to);
}

/** YYYY-MM-DD from "2026-09-23", "23/09/2026", "23-09-2569" (Buddhist year). null if it is not a real date. */
export function parseDate(raw: string): string | null {
  const t = raw.trim();
  let y: number, m: number, d: number;
  let r = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t);
  if (r) { y = +r[1]; m = +r[2]; d = +r[3]; }
  else if ((r = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/.exec(t))) { d = +r[1]; m = +r[2]; y = +r[3]; }
  else return null;
  if (y > 2400) y -= 543;
  const iso = `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const back = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(back.getTime()) || back.toISOString().slice(0, 10) !== iso ? null : iso;
}

const days = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);

function readRows(text: string, source: ResolvedSource): { list: ExtractedPrice[]; promos: ExtractedPrice[]; skipped: string[] } {
  const ex = source.extraction;
  if (ex.mode !== "ROW_REGEX") return { list: [], promos: [], skipped: [] };
  const sem = resolveSemantics(source.price_semantics);
  const row = new RegExp(ex.row_regex, "i");
  const skips = (ex.skip_line_regex ?? []).map((r) => new RegExp(r, "i"));
  const list: ExtractedPrice[] = [];
  const promos: ExtractedPrice[] = [];
  const skipped: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();   // inner spacing is kept: PDF price lists separate columns with runs of spaces
    if (!line || skips.some((s) => s.test(line))) continue;
    const m = row.exec(line);
    if (!m?.groups?.name || !m.groups.price) continue;
    const amount = amountsIn(m.groups.price)[0] ?? Number(m.groups.price.replace(/[^\d]/g, ""));
    if (!(amount >= MIN_LIST_PRICE_THB && amount <= MAX_LIST_PRICE_THB)) { skipped.push(`${line.slice(0, 80)} (amount out of range)`); continue; }
    const before = pageTokens(line.slice(0, m.index + m[0].indexOf(m.groups.price))).slice(-4);
    const cls = classifyAmount(before, sem);
    if (cls === "SKIP") { skipped.push(`${line.slice(0, 80)} (instalment / discount)`); continue; }
    const base = { name_raw: m.groups.name.trim(), amount_thb: amount, vat_included: null, evidence: line, method: "ROW" as const };
    if (cls === "PROMOTION") promos.push({ ...base, kind: "PROMOTION" });
    else if (cls === "PLAIN" && sem.require_list_marker && !m.groups.listmark) skipped.push(`${line.slice(0, 80)} (no list marker)`);
    else list.push({ ...base, kind: "LIST" });
    if (m.groups.promo) {
      const promo = amountsIn(m.groups.promo)[0];
      if (promo >= MIN_LIST_PRICE_THB && promo <= MAX_LIST_PRICE_THB) promos.push({ ...base, amount_thb: promo, kind: "PROMOTION" });
    }
  }
  return { list, promos, skipped };
}

export function readSource(source: ResolvedSource, page: PageText, known: KnownTrim[], brand: string, model: string, today: string): SourceRead {
  const read = emptyRead(source, "OK", "", page);

  if (source.as_of) {
    const m = new RegExp(source.as_of.pattern, "i").exec(page.text);
    const date = m?.groups?.date ? parseDate(m.groups.date) : null;
    read.as_of = date;
    if (!date) {
      if (source.as_of.required) return { ...read, state: "STALE", detail: "no readable date on the page and the playbook requires one" };
    } else if (days(date, today) > source.as_of.stale_after_days) {
      return { ...read, state: "STALE", detail: `page dated ${date}, older than ${source.as_of.stale_after_days} days` };
    }
  }

  const text = clipSection(page.text, source.extraction.section);
  if (text === null) return { ...read, state: "SECTION_MISSING", detail: "a section marker from the playbook is not on the page (layout changed?)" };
  const clipped = { ...page, text };
  const semantics = resolveSemantics(source.price_semantics);

  if (source.extraction.mode === "ROW_REGEX") {
    const { list, promos, skipped } = readRows(text, source);
    read.observations = list;
    read.promotions = promos;
    read.skipped_rows = skipped;
  } else {
    const a = extractAnchored(clipped, known, brand, model, semantics);
    read.observations = source.authority.prices ? a.observations : [];   // a source without price authority never supplies a price
    read.promotions = a.promotions;
    read.names_seen = a.names_seen;
    read.ambiguous = a.ambiguous;
    read.not_found = a.not_found;
  }
  const anything = read.observations.length + read.names_seen.length + read.promotions.length;
  if (!anything) return { ...read, state: "EMPTY", detail: "nothing recognisable was read from the page" };
  return read;
}

// ---------------------------------------------------------------------------------------------------------------------

export type MergedRow = {
  name_raw: string;
  /** null = the grade exists on the page but no (agreed) list price was read. Never guessed. */
  amount_thb: number | null;
  vat_included: boolean | null;
  evidence: string;
  method: ExtractedPrice["method"];
  source_id: string;
  url: string;
  content_hash: string;
  trim_id?: string;
};

export type Merged = {
  rows: MergedRow[];
  promotions: (ExtractedPrice & { source_id: string; url: string; content_hash: string })[];
  /** Two price-authoritative sources disagree on a grade: no price is emitted for it. */
  conflicts: { name: string; amounts: number[]; sources: string[] }[];
};

/** One grade = one normalized name, whatever source or reader it came from, so a priced row and a name-only row never duplicate. */
const keyOf = (r: { name_raw: string }) => normalizeTrimName(r.name_raw);

/**
 * Combine the usable reads of one model, most trusted first. A grade priced identically by two sources is one row
 * (evidence from the more trusted one); priced differently = a conflict and no price; named by an existence-only source
 * = a row without a price. Promotions are passed through separately and are never rows.
 */
export function mergeSources(reads: SourceRead[]): Merged {
  const ordered = reads.filter((r) => r.state === "OK").sort((a, b) => a.source.priority - b.source.priority);
  const rows = new Map<string, MergedRow>();
  const amounts = new Map<string, Map<number, string[]>>();
  const out: Merged = { rows: [], promotions: [], conflicts: [] };
  const meta = (r: SourceRead) => ({ source_id: r.source.id, url: r.page!.url, content_hash: r.page!.content_hash });

  for (const read of ordered) {
    for (const o of read.observations) {
      const key = keyOf(o);
      const per = amounts.get(key) ?? new Map<number, string[]>();
      per.set(o.amount_thb, [...(per.get(o.amount_thb) ?? []), read.source.id]);
      amounts.set(key, per);
      if (!rows.has(key)) rows.set(key, { name_raw: o.name_raw, amount_thb: o.amount_thb, vat_included: o.vat_included, evidence: o.evidence, method: o.method, trim_id: o.trim_id, ...meta(read) });
    }
    for (const n of read.names_seen) {
      const key = keyOf({ name_raw: n.name });
      if (!rows.has(key)) rows.set(key, { name_raw: n.name, amount_thb: null, vat_included: null, evidence: `grade named on ${read.source.role} page`, method: "ANCHORED", trim_id: n.trim_id, ...meta(read) });
    }
    for (const p of read.promotions) out.promotions.push({ ...p, ...meta(read) });
  }
  for (const [key, per] of amounts) {
    if (per.size > 1) {
      const row = rows.get(key)!;
      out.conflicts.push({ name: row.name_raw, amounts: [...per.keys()].sort((a, b) => a - b), sources: [...new Set([...per.values()].flat())] });
      row.amount_thb = null;
      row.evidence = `sources disagree: ${[...per.keys()].join(" vs ")}`;
    }
  }
  out.rows = [...rows.values()];
  return out;
}
