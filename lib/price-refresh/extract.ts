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
  method: "ANCHORED" | "AI" | "ROW";
  /** LIST = a retail list price (MSRP). PROMOTION = a campaign / discounted price: never a LIST_PRICE observation. Default LIST. */
  kind?: "LIST" | "PROMOTION";
  /** Set when the anchored reader tied this row to a known trim (hint for reconcile); not authoritative. */
  trim_id?: string;
};

/** Anything cheaper than this is a monthly instalment, a deposit or an accessory, not a list price. */
export const MIN_LIST_PRICE_THB = 150_000;
export const MAX_LIST_PRICE_THB = 60_000_000;

const AMOUNT = /(?<![\d,.])(\d{1,3}(?:,\d{3})+)(?![\d,])/g;
/**
 * Words that tell what an amount on a maker's page is. Markers are matched as substrings of the few tokens around the
 * amount (4 before, 1 after). A playbook may add to every list; it cannot remove the built-in skip words.
 */
export type PriceSemantics = {
  /** Instalments, deposits, and discount deltas: the amount is not a price of the car at all (always skipped). */
  skip_markers: string[];
  /** The amount is a campaign / discounted price: reported as a PROMOTION, never as a list price. */
  promotion_markers: string[];
  /** The amount is explicitly the maker's recommended / MSRP list price. */
  msrp_markers: string[];
  /** Weaker "this is the grade's price" words ("starting price"). */
  list_markers: string[];
  /** Both an MSRP-marked amount and another plain amount are shown for one grade: AMBIGUOUS (default) refuses to guess. */
  mixed_msrp: "AMBIGUOUS" | "MSRP_IS_LIST";
  /** Only amounts next to an msrp/list marker count; an unmarked number is never taken as a price. */
  require_list_marker: boolean;
};

export const BUILTIN_SKIP_MARKERS = ["ผ่อน", "ดาวน์", "เดือน", "ต่อเดือน", "monthly", "month", "installment", "instalment", "deposit", "down", "จอง", "ส่วนลด", "discount", "save", "ประหยัด"];
export const DEFAULT_SEMANTICS: PriceSemantics = {
  skip_markers: BUILTIN_SKIP_MARKERS,
  promotion_markers: ["โปรโมชัน", "โปรโมชั่น", "promotion", "promo", "special", "ราคาพิเศษ", "ราคาสุทธิ", "net price", "after", "หลังหัก", "แคมเปญ", "campaign", "flash", "sale"],
  msrp_markers: ["msrp", "ราคาป้าย", "ราคาแนะนำ", "recommended retail", "list price", "rrp"],
  list_markers: ["ราคาเริ่มต้น", "starting", "retail price", "price", "ราคา"],
  mixed_msrp: "AMBIGUOUS",
  require_list_marker: false,
};

/** Merge a playbook's partial semantics over the defaults (lists are extended, the built-in skip words always stay). */
export function resolveSemantics(partial: Partial<PriceSemantics> | undefined): PriceSemantics {
  const p = partial ?? {};
  const more = (base: string[], extra?: string[]) => [...new Set([...base, ...(extra ?? []).map((x) => x.toLowerCase())])];
  return {
    skip_markers: more(DEFAULT_SEMANTICS.skip_markers, p.skip_markers),
    promotion_markers: more(DEFAULT_SEMANTICS.promotion_markers, p.promotion_markers),
    msrp_markers: more(DEFAULT_SEMANTICS.msrp_markers, p.msrp_markers),
    list_markers: more(DEFAULT_SEMANTICS.list_markers, p.list_markers),
    mixed_msrp: p.mixed_msrp ?? DEFAULT_SEMANTICS.mixed_msrp,
    require_list_marker: p.require_list_marker ?? DEFAULT_SEMANTICS.require_list_marker,
  };
}

export type AmountClass = "SKIP" | "PROMOTION" | "MSRP" | "LIST_MARKED" | "PLAIN";

/** What is the amount? Decided from the words around it only. Order matters: skip > promotion > msrp > list-marker. */
export function classifyAmount(before: string[], sem: PriceSemantics): AmountClass {
  const has = (tokens: string[], words: string[]) => tokens.some((t) => words.some((w) => t.includes(w)));
  if (has(before, sem.skip_markers)) return "SKIP";
  // Words AFTER the amount are not used: on line-based pages they belong to the next line ("1,279,000 / MSRP : 1,799,000").
  if (has(before, sem.promotion_markers)) return "PROMOTION";
  if (has(before, sem.msrp_markers)) return "MSRP";
  if (has(before, sem.list_markers)) return "LIST_MARKED";
  return "PLAIN";
}

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
  /** LIST prices only. Promotions are never in here. */
  observations: ExtractedPrice[];
  /** Campaign / discounted prices found next to a known grade: evidence, never a list price. */
  promotions: ExtractedPrice[];
  /** Known grades whose name appears on the page, with or without a price (existence evidence, e.g. a model page with no prices). */
  names_seen: { trim_id: string; name: string }[];
  /** Known trims whose name was found but whose prices disagreed or were missing: reported, never guessed. */
  ambiguous: { trim_id: string; reason: string }[];
  not_found: string[];
};

const WINDOW = 28; // tokens after a trim name in which its price must appear

/**
 * @param trims  the model's trims (all statuses: a HISTORICAL trim reappearing is itself a finding)
 */
export function extractAnchored(page: PageText, trims: KnownTrim[], brand: string, model: string,
  semantics: PriceSemantics = DEFAULT_SEMANTICS): AnchoredResult {
  const tokens = pageTokens(page.text);
  const result: AnchoredResult = { observations: [], promotions: [], names_seen: [], ambiguous: [], not_found: [] };

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

  type Candidate = { amount: number; evidence: string; cls: AmountClass };
  const perTrim = new Map<string, Candidate[]>();
  const seenNames = new Set<string>();
  hits.forEach((hit, idx) => {
    if (!seenNames.has(hit.trim.trim_id)) {
      seenNames.add(hit.trim.trim_id);
      result.names_seen.push({ trim_id: hit.trim.trim_id, name: hit.trim.name });
    }
    const nextStart = idx + 1 < hits.length ? hits[idx + 1].start : tokens.length;
    const limit = Math.min(hit.end + WINDOW, nextStart);
    for (let k = hit.end; k < limit; k++) {
      const token = tokens[k];
      if (!token.startsWith("§")) continue;
      const amount = Number(token.slice(1));
      if (amount < MIN_LIST_PRICE_THB || amount > MAX_LIST_PRICE_THB) continue;
      const before = tokens.slice(Math.max(hit.end, k - 4), k);
      const cls = classifyAmount(before, semantics);
      if (cls === "SKIP") continue;
      const evidence = render(tokens.slice(Math.max(0, hit.start - 3), Math.min(tokens.length, k + 6)));
      const list = perTrim.get(hit.trim.trim_id) ?? [];
      list.push({ amount, evidence, cls });
      perTrim.set(hit.trim.trim_id, list);
    }
  });

  for (const trim of trims) {
    const found = perTrim.get(trim.trim_id);
    if (!found) {
      if (!seenNames.has(trim.trim_id)) result.not_found.push(trim.trim_id);
      else result.ambiguous.push({ trim_id: trim.trim_id, reason: "the name is on the page but no price was found next to it" });
      continue;
    }
    const row = (c: Candidate, kind: "LIST" | "PROMOTION"): ExtractedPrice => {
      const vat = /ไม่รวม\s*vat|excl(?:uding|\.)?\s*vat|before vat/.test(c.evidence.toLowerCase()) ? false : null;
      return { name_raw: trim.name, amount_thb: c.amount, vat_included: vat, evidence: c.evidence, method: "ANCHORED", trim_id: trim.trim_id, kind };
    };
    const promos = found.filter((c) => c.cls === "PROMOTION");
    const msrp = found.filter((c) => c.cls === "MSRP");
    const plain = found.filter((c) => c.cls === "LIST_MARKED" || (c.cls === "PLAIN" && !semantics.require_list_marker));
    for (const c of promos) result.promotions.push(row(c, "PROMOTION"));

    let chosen: Candidate | null = null;
    if (msrp.length) {
      const msrpAmounts = new Set(msrp.map((c) => c.amount));
      const others = plain.filter((c) => !msrpAmounts.has(c.amount));
      if (msrpAmounts.size > 1) {
        result.ambiguous.push({ trim_id: trim.trim_id, reason: `two MSRP figures: ${[...msrpAmounts].map(fmt).join(" and ")}` });
        continue;
      }
      if (others.length && semantics.mixed_msrp === "AMBIGUOUS") {
        result.ambiguous.push({ trim_id: trim.trim_id, reason: `MSRP ${fmt(msrp[0].amount)} and another price ${fmt(others[0].amount)} are both shown; the playbook has not said which is the list price` });
        continue;
      }
      chosen = msrp[0];
      for (const c of others) result.promotions.push(row(c, "PROMOTION"));
    } else if (plain.length) {
      const amounts = new Set(plain.map((c) => c.amount));
      // The first plausible price after the name is the grade's; a later, different plain price is only a conflict
      // if the same name is repeated elsewhere with another price (checked via separate hits below).
      chosen = plain[0];
      const repeated = plain.filter((c) => c.amount !== chosen!.amount);
      if (amounts.size > 1 && repeated.length && hitsFor(trim.trim_id, hits) > 1) {
        result.ambiguous.push({ trim_id: trim.trim_id, reason: `the page shows ${[...amounts].map(fmt).join(" and ")} after this name` });
        continue;
      }
    }
    if (chosen) result.observations.push(row(chosen, "LIST"));
    else if (!promos.length) result.ambiguous.push({ trim_id: trim.trim_id, reason: "the name is on the page but no list price was found next to it" });
  }
  return result;
}

const hitsFor = (trimId: string, hits: { trim: KnownTrim }[]) => hits.filter((h) => h.trim.trim_id === trimId).length;

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
