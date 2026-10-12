/**
 * Reading list prices out of a rendered OEM page. Pure: text in, observations out.
 *
 * Two readers, one rule. The anchored reader needs no AI: it looks for the trim names the master already knows and
 * takes the first plausible price after each name, before the next known name. The AI reader (./ai.ts) may also
 * discover trims the master does not know. For BOTH, a number is only an observation if the page literally contains
 * it next to the name (`validateEvidence`) -- a model can never invent a price, only misread one, and the
 * reconcile engine's two-run and 15 % rules plus the auditor are there for misreads.
 */
import { normalizeTrimName, tokensOf } from "../vehicle-engine/trim-reconcile.ts";

export type PageText = { url: string; text: string; content_hash: string; fetched_at: string };
export type KnownTrim = { trim_id: string; name: string; aliases?: string[] };

export type ExtractedPrice = {
  name_raw: string;
  amount_thb: number;
  vat_included: boolean | null;
  /** The page text around the price, as the reader saw it. Shown to the auditor and kept with the observation. */
  evidence: string;
  method: "ANCHORED" | "AI";
  /** Set when the anchored reader tied this row to a known trim (hint for reconcile); not authoritative. */
  trim_id?: string;
};

/** Anything cheaper than this is a monthly instalment, a deposit or an accessory, not a list price. */
export const MIN_LIST_PRICE_THB = 150_000;
export const MAX_LIST_PRICE_THB = 60_000_000;

const AMOUNT = /(?<![\d,.])(\d{1,3}(?:,\d{3})+)(?![\d,])/g;
const INSTALMENT_WORDS = ["ผ่อน", "ดาวน์", "เดือน", "ต่อเดือน", "monthly", "month", "installment", "instalment", "deposit", "down", "จอง", "ส่วนลด", "discount", "save", "ประหยัด"];
const REFERENCE_WORDS = ["msrp", "ราคาป้าย"];

/** Replace comma-formatted amounts by `§<digits>` so they survive tokenization as single tokens. */
export function markAmounts(text: string): string {
  return text.replace(AMOUNT, (_, n: string) => ` §${n.replace(/,/g, "")} `);
}

export function amountsIn(text: string): number[] {
  return [...text.matchAll(AMOUNT)].map((m) => Number(m[1].replace(/,/g, "")));
}

const fmt = (n: number) => n.toLocaleString("en-US");

/** Page text -> tokens, with prices kept whole (`§569000`). Same normalization as trim names. */
export function pageTokens(text: string): string[] {
  const marked = markAmounts(text.replace(/[​ ]/g, " "));
  const out: string[] = [];
  // tokensOf cannot see `§`, so split on the markers and tokenize the text between them.
  for (const part of marked.split(/(§\d+)/)) {
    if (/^§\d+$/.test(part)) out.push(part);
    else out.push(...tokensOf(part));
  }
  return out;
}

function findSequence(haystack: string[], needle: string[], from = 0): number[] {
  const hits: number[] = [];
  if (!needle.length) return hits;
  outer: for (let i = from; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) if (haystack[i + j] !== needle[j]) continue outer;
    hits.push(i);
  }
  return hits;
}

const render = (tokens: string[]) => tokens.map((t) => (t.startsWith("§") ? fmt(Number(t.slice(1))) : t)).join(" ");

export type AnchoredResult = {
  observations: ExtractedPrice[];
  /** Known trims whose name was found but whose prices disagreed or were missing: reported, never guessed. */
  ambiguous: { trim_id: string; reason: string }[];
  not_found: string[];
};

const WINDOW = 28; // tokens after a trim name in which its price must appear

/**
 * @param trims  the model's trims (all statuses: a HISTORICAL trim reappearing is itself a finding)
 */
export function extractAnchored(page: PageText, trims: KnownTrim[], brand: string, model: string): AnchoredResult {
  const tokens = pageTokens(page.text);
  const result: AnchoredResult = { observations: [], ambiguous: [], not_found: [] };

  // Every known name (and alias) as a token sequence, longest first so "sport plus" wins over "sport".
  type Anchor = { trim: KnownTrim; seq: string[] };
  const anchors: Anchor[] = [];
  for (const trim of trims) {
    for (const name of [trim.name, ...(trim.aliases ?? [])]) {
      const seq = tokensOf(name, brand, model);
      if (seq.length) anchors.push({ trim, seq });
    }
  }
  anchors.sort((a, b) => b.seq.length - a.seq.length);

  // All occurrences, with a longer name masking the shorter name it contains at the same spot.
  type Hit = { trim: KnownTrim; start: number; end: number };
  const hits: Hit[] = [];
  const covered = new Array<boolean>(tokens.length).fill(false);
  for (const anchor of anchors) {
    for (const start of findSequence(tokens, anchor.seq)) {
      const end = start + anchor.seq.length;
      if (covered.slice(start, end).some(Boolean)) continue;
      for (let k = start; k < end; k++) covered[k] = true;
      hits.push({ trim: anchor.trim, start, end });
    }
  }
  hits.sort((a, b) => a.start - b.start);

  const perTrim = new Map<string, { amount: number; evidence: string }[]>();
  hits.forEach((hit, idx) => {
    const limit = Math.min(hit.end + WINDOW, idx + 1 < hits.length ? hits[idx + 1].start : tokens.length);
    for (let k = hit.end; k < limit; k++) {
      const token = tokens[k];
      if (!token.startsWith("§")) continue;
      const amount = Number(token.slice(1));
      if (amount < MIN_LIST_PRICE_THB || amount > MAX_LIST_PRICE_THB) continue;
      const before = tokens.slice(Math.max(hit.end, k - 4), k);
      if (before.some((t) => INSTALMENT_WORDS.some((w) => t.includes(w)))) continue;
      if (before.some((t) => REFERENCE_WORDS.includes(t))) continue;
      const evidence = render(tokens.slice(Math.max(0, hit.start - 3), Math.min(tokens.length, k + 6)));
      const list = perTrim.get(hit.trim.trim_id) ?? [];
      list.push({ amount, evidence });
      perTrim.set(hit.trim.trim_id, list);
      break; // the first plausible price after the name is the one that belongs to it
    }
  });

  for (const trim of trims) {
    const found = perTrim.get(trim.trim_id);
    if (!found) {
      result.not_found.push(trim.trim_id);
      continue;
    }
    const amounts = new Set(found.map((f) => f.amount));
    if (amounts.size > 1) {
      result.ambiguous.push({ trim_id: trim.trim_id, reason: `the page shows ${[...amounts].map(fmt).join(" and ")} after this name` });
      continue;
    }
    const best = found[0];
    const nearby = best.evidence.toLowerCase();
    const vat = /ไม่รวม\s*vat|excl(?:uding|\.)?\s*vat|before vat/.test(nearby) ? false : null;
    result.observations.push({ name_raw: trim.name, amount_thb: best.amount, vat_included: vat, evidence: best.evidence,
      method: "ANCHORED", trim_id: trim.trim_id });
  }
  return result;
}

/**
 * The literal-evidence rule for any reader. The amount must appear in the page as written (comma-grouped), the quote
 * must be a substring of the page after whitespace normalization, and the quote must contain both the amount and the
 * name (or, for names the page spells differently, every token of the name).
 */
export function validateEvidence(page: PageText, row: { name_raw: string; amount_thb: number; quote: string }): boolean {
  if (!(row.amount_thb >= MIN_LIST_PRICE_THB && row.amount_thb <= MAX_LIST_PRICE_THB)) return false;
  const squash = (s: string) => s.replace(/[\s​ ]+/g, " ").trim().toLowerCase();
  const text = squash(page.text);
  const quote = squash(row.quote);
  if (quote.length < 4 || !text.includes(quote)) return false;
  if (!amountsIn(row.quote).includes(row.amount_thb)) return false;
  const quoteTokens = new Set(tokensOf(row.quote));
  const nameTokens = tokensOf(row.name_raw);
  return nameTokens.length > 0 && nameTokens.every((t) => quoteTokens.has(t));
}

export { normalizeTrimName };
