/**
 * OEM playbooks: one versioned JSON file per brand under config/price-fetcher/playbooks/, validated here.
 *
 * A playbook says WHERE a maker's truth lives (which pages, in what order of trust), HOW to fetch each page
 * (plain HTML, a rendered browser, or a PDF), HOW to read it (anchored on known grade names, or one regex per row),
 * and WHAT the numbers on it mean (MSRP vs promotion). It never says what the prices ARE: that always comes from a
 * fetched page, through the same reconcile / audit / writer as before.
 *
 * Safety defaults (VEHICLE_DB_V3 5.1, 9.1; audit 2026-10-13):
 *  - `lineup_complete` is false unless a source carries a dated, signed `lineup_verification` AND the playbook is
 *    VERIFIED. A successful fetch or a partial read never implies completeness.
 *  - DRAFT playbooks may be used in dry runs only; `lineup_complete` is ignored for them.
 *  - Brochures and announcements are evidence only: they can never carry prices or existence authority.
 */
import { type PriceSemantics } from "./extract.ts";

export const SOURCE_ROLES = ["MODEL_PAGE", "PRICE_LIST", "PRICE_LIST_PDF", "BROCHURE", "ANNOUNCEMENT"] as const;
export type SourceRole = typeof SOURCE_ROLES[number];
export const EVIDENCE_ONLY_ROLES: readonly SourceRole[] = ["BROCHURE", "ANNOUNCEMENT"];

export type FetchSpec = { kind: "HTML" } | { kind: "BROWSER"; wait_for_text?: string } | { kind: "PDF" };
export type Section = { start?: string; end?: string };
export type ExtractionSpec =
  | { mode: "ANCHORED"; section?: Section }
  | { mode: "ROW_REGEX"; section?: Section; row_regex: string; skip_line_regex?: string[] };
export type LineupVerification = { verified_on: string; verified_by: string; evidence_ref: string; note?: string };
export type AsOfSpec = { pattern: string; stale_after_days: number; required?: boolean };

export type SourceSpec = {
  id: string;
  /** The registry target this source corresponds to (targets.json), if any. */
  target_id?: string;
  url: string;
  role: SourceRole;
  /** Canonical vehicle_models ids this page speaks for. */
  models: string[];
  fetch: FetchSpec;
  /** 1 = most trusted. Lower number wins when two sources give different facts. */
  priority: number;
  authority: { prices: boolean; existence: boolean };
  extraction: ExtractionSpec;
  price_semantics?: Partial<PriceSemantics>;
  /** Default false. See the header. */
  lineup_complete?: boolean;
  lineup_verification?: LineupVerification;
  /** Default true: if this source cannot be read (and has no usable fallback) the whole model is stopped. */
  required?: boolean;
  /** Fetched only when the named primary source is unusable (failed, stale, empty). */
  fallback_of?: string;
  as_of?: AsOfSpec;
};

export type PlaybookStatus = "DRAFT" | "VERIFIED";
export type Playbook = {
  schema_version: 1;
  brand: string;
  playbook_version: string;
  status: PlaybookStatus;
  /** Required for VERIFIED: the real pages a person compared the sources against. */
  evidence?: { url: string; captured_on: string; note: string }[];
  sources: SourceSpec[];
};

export const LINEUP_VERIFICATION_MAX_AGE_DAYS = 90;

const isDate = (v: unknown) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v));
const isStr = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const MODEL_ID = /^[a-z0-9_]+\.[a-z0-9_]+$/;

function regexProblem(source: string, groups: string[]): string | null {
  try {
    const re = new RegExp(source, "i");
    const names = [...source.matchAll(/\(\?<([a-z_]+)>/g)].map((m) => m[1]);
    const missing = groups.filter((g) => !names.includes(g));
    void re;
    return missing.length ? `needs named group(s): ${missing.join(", ")}` : null;
  } catch (e) {
    return `does not compile (${(e as Error).message})`;
  }
}

/** Every reason a playbook cannot be trusted. Empty list = valid. */
export function validatePlaybook(input: unknown): string[] {
  const problems: string[] = [];
  const p = input as Partial<Playbook> | null;
  if (!p || typeof p !== "object") return ["playbook is not an object"];
  if (p.schema_version !== 1) problems.push("schema_version must be 1");
  if (!isStr(p.brand)) problems.push("brand is required");
  if (!isStr(p.playbook_version)) problems.push("playbook_version is required");
  if (p.status !== "DRAFT" && p.status !== "VERIFIED") problems.push("status must be DRAFT or VERIFIED");
  if (p.status === "VERIFIED") {
    const ev = p.evidence;
    if (!Array.isArray(ev) || ev.length === 0) problems.push("VERIFIED needs evidence: the real pages it was checked against");
    else ev.forEach((e, i) => { if (!isStr(e?.url) || !isDate(e?.captured_on) || !isStr(e?.note)) problems.push(`evidence[${i}] needs url, captured_on (YYYY-MM-DD) and note`); });
  }
  if (!Array.isArray(p.sources) || p.sources.length === 0) return [...problems, "sources must be a non-empty list"];

  const ids = new Set<string>();
  const byId = new Map<string, SourceSpec>();
  for (const s of p.sources) if (s && isStr(s.id)) byId.set(s.id, s);
  p.sources.forEach((s, i) => {
    const at = `source ${s?.id ?? `#${i}`}`;
    if (!s || !isStr(s.id)) { problems.push(`source #${i}: id is required`); return; }
    if (ids.has(s.id)) problems.push(`${at}: duplicate id`);
    ids.add(s.id);
    if (!isStr(s.url) || !/^https:\/\//.test(s.url)) problems.push(`${at}: url must be https`);
    if (!SOURCE_ROLES.includes(s.role)) problems.push(`${at}: role must be one of ${SOURCE_ROLES.join(", ")}`);
    if (!Array.isArray(s.models) || s.models.length === 0 || !s.models.every((m) => MODEL_ID.test(m))) problems.push(`${at}: models must be canonical model ids like "brand.model"`);
    if (!Number.isInteger(s.priority) || s.priority < 1) problems.push(`${at}: priority must be an integer >= 1`);
    if (typeof s.authority?.prices !== "boolean" || typeof s.authority?.existence !== "boolean") problems.push(`${at}: authority.prices and authority.existence must be booleans`);
    const kind = s.fetch?.kind;
    if (kind !== "HTML" && kind !== "BROWSER" && kind !== "PDF") problems.push(`${at}: fetch.kind must be HTML, BROWSER or PDF`);
    if (s.role === "PRICE_LIST_PDF" && kind !== "PDF") problems.push(`${at}: PRICE_LIST_PDF must be fetched as PDF`);
    if (kind === "PDF" && s.role !== "PRICE_LIST_PDF" && !EVIDENCE_ONLY_ROLES.includes(s.role)) problems.push(`${at}: a PDF source must have role PRICE_LIST_PDF (or an evidence-only role)`);
    if (EVIDENCE_ONLY_ROLES.includes(s.role) && (s.authority?.prices || s.authority?.existence || s.lineup_complete)) {
      problems.push(`${at}: ${s.role} is evidence only: no price authority, no existence authority, never lineup_complete`);
    }
    // extraction
    const ex = s.extraction;
    if (!ex || (ex.mode !== "ANCHORED" && ex.mode !== "ROW_REGEX")) problems.push(`${at}: extraction.mode must be ANCHORED or ROW_REGEX`);
    else {
      for (const part of ["start", "end"] as const) {
        const v = ex.section?.[part];
        if (v !== undefined && !isStr(v)) problems.push(`${at}: extraction.section.${part} must be non-empty text`);
      }
      if (ex.mode === "ROW_REGEX") {
        const bad = isStr(ex.row_regex) ? regexProblem(ex.row_regex, ["name", "price"]) : "row_regex is required";
        if (bad) problems.push(`${at}: row_regex ${bad}`);
        for (const r of ex.skip_line_regex ?? []) { const b = regexProblem(r, []); if (b) problems.push(`${at}: skip_line_regex ${b}`); }
        if (!s.authority?.prices) problems.push(`${at}: ROW_REGEX reads prices, so authority.prices must be true`);
      }
    }
    if (s.as_of) {
      const bad = isStr(s.as_of.pattern) ? regexProblem(s.as_of.pattern, ["date"]) : "pattern is required";
      if (bad) problems.push(`${at}: as_of.pattern ${bad}`);
      if (!Number.isInteger(s.as_of.stale_after_days) || s.as_of.stale_after_days < 1) problems.push(`${at}: as_of.stale_after_days must be an integer >= 1`);
    }
    // completeness: explicit, dated, signed
    if (s.lineup_complete !== undefined && typeof s.lineup_complete !== "boolean") problems.push(`${at}: lineup_complete must be boolean`);
    if (s.lineup_complete === true) {
      const v = s.lineup_verification;
      if (!v || !isDate(v.verified_on) || !isStr(v.verified_by) || !isStr(v.evidence_ref)) problems.push(`${at}: lineup_complete=true needs lineup_verification {verified_on, verified_by, evidence_ref}`);
      if (!s.authority?.existence) problems.push(`${at}: lineup_complete=true needs authority.existence`);
      if (p.status !== "VERIFIED") problems.push(`${at}: only a VERIFIED playbook may declare lineup_complete`);
    }
    if (s.fallback_of !== undefined) {
      const primary = byId.get(s.fallback_of);
      if (!primary) problems.push(`${at}: fallback_of "${s.fallback_of}" is not a source in this playbook`);
      else if (primary.fallback_of) problems.push(`${at}: fallback chains are not allowed`);
      else if (primary.id === s.id) problems.push(`${at}: cannot fall back to itself`);
      else if (!s.models.every((m) => primary.models.includes(m))) problems.push(`${at}: a fallback may only speak for models its primary covers`);
    }
  });
  return problems;
}

export type ResolvedSource = SourceSpec & { brand: string; playbook_version: string; playbook_status: PlaybookStatus };

/** Which playbooks may run: DRAFT only in dry runs; invalid ones never (reported to the caller). */
export function usablePlaybooks(playbooks: Playbook[], mode: { apply: boolean }): { usable: Playbook[]; rejected: { brand: string; why: string[] }[] } {
  const usable: Playbook[] = [];
  const rejected: { brand: string; why: string[] }[] = [];
  for (const pb of playbooks) {
    const why = validatePlaybook(pb);
    if (!why.length && pb.status === "DRAFT" && mode.apply) why.push("DRAFT playbooks are dry-run only");
    if (why.length) rejected.push({ brand: String(pb?.brand ?? "?"), why });
    else usable.push(pb);
  }
  return { usable, rejected };
}

/** model id -> its sources, most trusted first. */
export function sourcesByModel(playbooks: Playbook[]): Map<string, ResolvedSource[]> {
  const out = new Map<string, ResolvedSource[]>();
  for (const pb of playbooks) {
    for (const s of pb.sources) {
      for (const model of s.models) {
        const list = out.get(model) ?? [];
        list.push({ ...s, brand: pb.brand, playbook_version: pb.playbook_version, playbook_status: pb.status });
        out.set(model, list);
      }
    }
  }
  for (const list of out.values()) list.sort((a, b) => a.priority - b.priority || a.id.localeCompare(b.id));
  return out;
}

/**
 * Is this source entitled to say "this is the whole lineup"? Only an explicit, fresh, signed verification in a VERIFIED
 * playbook counts. (The caller must additionally have read the source successfully in this run.)
 */
export function lineupDeclared(source: ResolvedSource, today: string): boolean {
  if (source.lineup_complete !== true || source.playbook_status !== "VERIFIED") return false;
  const v = source.lineup_verification;
  if (!v || !isDate(v.verified_on)) return false;
  const ageDays = Math.floor((Date.parse(today) - Date.parse(v.verified_on)) / 86_400_000);
  return ageDays >= 0 && ageDays <= LINEUP_VERIFICATION_MAX_AGE_DAYS;
}

/** The behaviour before playbooks: one browser-read model page per registry target, nothing declared complete. */
export function legacySource(target: { id: string; url: string }, modelId: string): ResolvedSource {
  return {
    id: target.id, target_id: target.id, url: target.url, role: "MODEL_PAGE", models: [modelId], fetch: { kind: "BROWSER" }, priority: 1,
    authority: { prices: true, existence: true }, extraction: { mode: "ANCHORED" }, lineup_complete: false, required: true,
    brand: modelId.split(".")[0], playbook_version: "legacy-registry", playbook_status: "DRAFT",
  };
}
