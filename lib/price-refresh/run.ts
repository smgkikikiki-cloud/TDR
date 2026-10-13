/**
 * One price refresh over a set of models: fetch -> read -> reconcile -> audit -> write.
 * Everything that touches the outside world comes in through `Ports`, so the whole flow is testable offline
 * (scripts/check-price-run.ts). With `apply: false` nothing is written anywhere.
 */
import { auditChange, extractWithAi, type Budget, type AiSettings, type Messages } from "./ai.ts";
import type { ExtractedPrice, KnownTrim } from "./extract.ts";
import type { FetchOutcome, PageFetcher } from "./fetcher.ts";
import { EVIDENCE_ONLY_ROLES, legacySource, lineupDeclared, type ResolvedSource } from "./playbook.ts";
import { emptyRead, mergeSources, readSource, type SourceRead } from "./source.ts";
import type { History, LoadedModel, ApplyResult } from "./store.ts";
import { planPriceWrites, type RpcItem } from "../vehicle-engine/price-writer.ts";
import { normalizeTrimName, reconcileModel, type Observation } from "../vehicle-engine/trim-reconcile.ts";

type Row = Record<string, any>;

export type Ports = {
  /** Rendered browser (strategy BROWSER). */
  fetch: PageFetcher;
  /** Plain HTTP text (strategy HTML) and PDF text (strategy PDF). A strategy without an adapter fails that source, never silently falls back. */
  fetchHtml?: PageFetcher;
  fetchPdf?: PageFetcher;
  loadModel(modelId: string): Promise<LoadedModel | null>;
  loadHistory(modelId: string, now: Date): Promise<History>;
  loadApprovedJumps(modelId: string): Promise<Row[]>;
  markJumpApplied(card: Row): Promise<void>;
  insertObservations(rows: Row[]): Promise<void>;
  proposeInbox(p: { kind: string; dedupe_key: string; model_id: string | null; trim_id: string | null; source_hash: string | null; payload: Row }): Promise<any>;
  applyPriceChanges(batchId: string, items: RpcItem[]): Promise<ApplyResult[]>;
  saveSourceState(row: Row): Promise<void>;
};

export type AiPort = { budget: Budget; messages: Messages; settings: AiSettings; onUsage: (skill: string, model: string, i: number, o: number, c: number) => void };

export type Target = { id: string; url: string; lineup_complete?: boolean };
/** `sources` (from a playbook) wins; `targets` is the legacy registry path (browser + anchored reader, nothing declared complete). */
export type ModelJob = { model_id: string; targets: Target[]; sources?: ResolvedSource[] };
export type SourceStateMap = Map<string, Row>;

export type RunOptions = {
  run_id: string; now: Date; today: string; apply: boolean; use_ai: boolean; require_audit: boolean;
  source_state: SourceStateMap;
};

export type ModelReport = {
  model_id: string; status: string; reason: string;
  applied: { trim_id: string; name: string; from: number | null; to: number }[];
  held: { trim_id: string; name: string; amount_thb: number; why: string }[];
  pending: { trim_id: string; name: string; amount_thb: number }[];
  jumps: { trim_id: string; name: string; from: number; to: number }[];
  proposals: string[];
  skipped: string[];
  fetch_errors: string[];
  observations: number;
  /** One line per source: how it was read and whether it was used. */
  sources: { id: string; role: string; state: string; used: boolean; degraded: boolean; detail: string }[];
  promotions: number;
  conflicts: string[];
  lineup_complete: boolean;
};

const dedupeName = (s: string) => normalizeTrimName(s);

export async function refreshModel(job: ModelJob, ports: Ports, ai: AiPort | null, opt: RunOptions): Promise<ModelReport> {
  const report: ModelReport = { model_id: job.model_id, status: "OK", reason: "", applied: [], held: [], pending: [], jumps: [], proposals: [], skipped: [], fetch_errors: [], observations: 0, sources: [], promotions: 0, conflicts: [], lineup_complete: false };
  const loaded = await ports.loadModel(job.model_id);
  if (!loaded) { report.status = "UNKNOWN_MODEL"; report.reason = "model not in the master"; return report; }
  const nameOf = new Map(loaded.trims.map((t) => [t.trim_id, t.name]));
  const known: KnownTrim[] = loaded.trims.map((t) => ({ trim_id: t.trim_id, name: t.name, aliases: t.aliases }));

  // 1. fetch and read every source of the model, most trusted first. A required source that cannot be used (and has no
  //    usable fallback) stops the whole model: a partial lineup would look like discontinued trims.
  const sources = (job.sources ?? job.targets.map((t) => ({ ...legacySource(t, job.model_id), lineup_complete: false })))
    .filter((src) => !EVIDENCE_ONLY_ROLES.includes(src.role))
    .sort((x, y) => x.priority - y.priority);
  const primaries = sources.filter((src) => !src.fallback_of);
  const reads: SourceRead[] = [];
  const degradedIds = new Set<string>();
  let extractionOk = primaries.length > 0;

  const fetchOne = async (src: ResolvedSource): Promise<SourceRead> => {
    const adapter = src.fetch.kind === "PDF" ? ports.fetchPdf : src.fetch.kind === "HTML" ? ports.fetchHtml : ports.fetch;
    const stateKey = src.target_id ?? src.id;
    const state = opt.source_state.get(stateKey);
    const base = { target_id: stateKey, url: src.url, model_ids: [job.model_id], last_attempt_at: opt.now.toISOString() };
    const out: FetchOutcome = adapter ? await adapter(src.url, { wait_for_text: src.fetch.kind === "BROWSER" ? src.fetch.wait_for_text : undefined })
      : { ok: false, kind: "FAILED", error: `no ${src.fetch.kind} adapter available in this run` };
    if (!out.ok) {
      report.fetch_errors.push(`${src.id}: ${out.error}`);
      const failCount = (state?.fail_count ?? 0) + 1;
      const status = out.kind === "BLOCKED" ? "BLOCKED" : failCount >= 3 ? "BROKEN" : "FAILED";
      if (opt.apply) await ports.saveSourceState({ ...base, status, fail_count: failCount, last_error: out.error });
      return emptyRead(src, "FAILED", out.error);
    }
    const unchanged = state?.content_hash === out.page.content_hash;
    if (opt.apply) await ports.saveSourceState({ ...base, status: unchanged ? "UNCHANGED" : "OK", fail_count: 0, last_error: null,
      content_hash: out.page.content_hash, last_success_at: opt.now.toISOString() });
    const read = readSource(src, out.page, known, loaded.brand_name, loaded.model_name, opt.today);
    // The AI reader only helps an anchored read that missed CURRENT trims, and only when the page changed.
    const currentIds = new Set(loaded.trims.filter((t) => t.status === "CURRENT").map((t) => t.trim_id));
    const missingCurrent = read.not_found.some((id) => currentIds.has(id));
    if (ai && opt.use_ai && src.extraction.mode === "ANCHORED" && src.authority.prices && read.state !== "STALE" && read.state !== "SECTION_MISSING"
      && !unchanged && (missingCurrent || read.observations.length === 0)) {
      const aiOut = await extractWithAi(out.page, known, { ...ai, model_name: `${loaded.brand_name} ${loaded.model_name}` });
      const have = new Set(read.observations.map((r) => dedupeName(r.name_raw)));
      for (const row of aiOut.rows) if (!have.has(dedupeName(row.name_raw))) read.observations.push(row);
      for (const r of aiOut.rejected) report.skipped.push(`AI row refused (${r.name || "?"}): ${r.reason}`);
      if (read.state === "EMPTY" && read.observations.length) { read.state = "OK"; read.detail = ""; }
    }
    return read;
  };

  for (const primary of primaries) {
    let read = await fetchOne(primary);
    let usable = read.state === "OK";
    reads.push(read);
    if (!usable) {
      for (const fb of sources.filter((x) => x.fallback_of === primary.id)) {
        const fbRead = await fetchOne(fb);
        reads.push(fbRead);
        if (fbRead.state === "OK") { usable = true; degradedIds.add(fb.id); break; }
      }
    }
    if (!usable && primary.required !== false) extractionOk = false;
  }
  const used = reads.filter((r) => r.state === "OK");
  report.sources = reads.map((r) => ({ id: r.source.id, role: r.source.role, state: r.state, used: r.state === "OK", degraded: degradedIds.has(r.source.id), detail: r.detail }));
  const merged = mergeSources(extractionOk ? used : []);
  report.promotions = merged.promotions.length;
  report.conflicts = merged.conflicts.map((c) => `${c.name}: ${c.amounts.join(" vs ")}`);
  // Completeness is declared, never inferred: a verified source, read successfully now, and not a degraded fallback.
  const lineupComplete = extractionOk && used.some((r) => !degradedIds.has(r.source.id) && r.source.authority.existence && lineupDeclared(r.source, opt.today));
  report.lineup_complete = lineupComplete;
  type Obs = (typeof merged.rows)[number];
  const observations: Obs[] = merged.rows;
  report.observations = observations.length;
  const urls = [...new Set(used.map((r) => r.source.url))];

  // 3. reconcile
  const history = await ports.loadHistory(job.model_id, opt.now);
  const trimStates = loaded.trims.map((t) => ({ ...t, last_seen_at: history.last_seen.get(t.trim_id) ?? null }));
  const obsForReconcile: Observation[] = observations.map((o) => ({ name_raw: o.name_raw, amount_thb: o.amount_thb, vat_included: o.vat_included }));
  const plan = reconcileModel({
    model: { id: job.model_id, brand_name: loaded.brand_name, model_name: loaded.model_name },
    trims: trimStates, observations: obsForReconcile, extraction_ok: extractionOk,
    headline: used[0]?.page?.text.split("\n").find((l) => l.trim())?.slice(0, 200),
    prior_amounts: history.prior_amounts, model_first_observed_at: history.first_observed, read_dates: history.read_dates,
    lineup_complete: lineupComplete, today: opt.today,
  });
  report.status = plan.status; report.reason = plan.reason;
  const sourceHash = used.map((r) => r.page!.content_hash).sort().join("+") || null;

  // 4. record what was seen (immutable) -- the next run's "same value twice" rule reads these
  const matchedTrim = new Map(plan.matches.map((m) => [m.obs_index, m.trim_id]));
  if (opt.apply && observations.length) {
    await ports.insertObservations(observations.map((o, i) => ({
      run_id: opt.run_id, source_kind: "SCRAPE", field_key: "LIST_PRICE", model_id: job.model_id, trim_id: matchedTrim.get(i) ?? null,
      trim_name_raw: o.name_raw, amount_thb: o.amount_thb, vat_included: o.vat_included, source_url: o.url, content_hash: o.content_hash,
      raw: { evidence: o.evidence, method: o.method, source_id: o.source_id }, observed_at: opt.now.toISOString() })));
  }
  // Promotions are evidence about a campaign, stored as CAMPAIGN_PRICE observations. They never reach the writer.
  if (opt.apply && merged.promotions.length) {
    await ports.insertObservations(merged.promotions.map((o) => ({
      run_id: opt.run_id, source_kind: "SCRAPE", field_key: "CAMPAIGN_PRICE", model_id: job.model_id, trim_id: o.trim_id ?? null,
      trim_name_raw: o.name_raw, amount_thb: o.amount_thb, vat_included: o.vat_included, source_url: o.url, content_hash: o.content_hash,
      raw: { evidence: o.evidence, method: o.method, source_id: o.source_id }, observed_at: opt.now.toISOString() })));
  }
  const evidenceFor = new Map<string, { evidence: string }>();
  for (const m of plan.matches) evidenceFor.set(m.trim_id, observations[m.obs_index]);

  // 5. cards for a human: structure changes, big jumps, broken source
  const propose = async (kind: string, key: string, trimId: string | null, payload: Row) => {
    if (opt.apply) await ports.proposeInbox({ kind, dedupe_key: `${job.model_id}:${key}`, model_id: job.model_id, trim_id: trimId, source_hash: sourceHash, payload });
  };
  if (plan.status === "SOURCE_BROKEN") await propose("SOURCE_BROKEN", "SOURCE_BROKEN", null, { reason: plan.reason, urls });
  for (const p of plan.proposals) {
    report.proposals.push(p.kind + ("name_raw" in p ? `: ${p.name_raw}` : "trim_id" in p ? `: ${p.trim_id}` : ""));
    const keyPart = "trim_id" in p ? p.trim_id : "name_raw" in p ? dedupeName(p.name_raw) : (p as any).reason;
    await propose("STRUCTURE", `${p.kind}:${keyPart}`, "trim_id" in p ? p.trim_id : null, { proposal: p, urls });
  }
  for (const j of plan.price_jumps) {
    report.jumps.push({ trim_id: j.trim_id, name: nameOf.get(j.trim_id) ?? j.trim_id, from: j.prior_amount, to: j.amount_thb });
    await propose("PRICE_JUMP", `PRICE_JUMP:${j.trim_id}:${j.amount_thb}`, j.trim_id,
      { trim_id: j.trim_id, amount_thb: j.amount_thb, prior_amount: j.prior_amount, ratio: j.ratio, evidence: evidenceFor.get(j.trim_id)?.evidence ?? "" });
  }
  for (const p of plan.price_pending) report.pending.push({ ...p, name: nameOf.get(p.trim_id) ?? p.trim_id });

  // 6. approved jump cards: apply exactly the approved amount, once, and only if the page still shows it
  const applies: { trim_id: string; amount_thb: number; vat_included: boolean | null; approved_inbox_id?: string | null }[] = [];
  const cards = await ports.loadApprovedJumps(job.model_id);
  const usedCards: Row[] = [];
  for (const card of cards) {
    const still = plan.price_jumps.find((j) => j.trim_id === card.payload?.trim_id && j.amount_thb === card.payload?.amount_thb);
    if (still) { applies.push({ trim_id: still.trim_id, amount_thb: still.amount_thb, vat_included: null, approved_inbox_id: card.id }); usedCards.push(card); }
  }

  // 7. the auditor may only veto
  for (const a of plan.price_applies) {
    const evidence = evidenceFor.get(a.trim_id);
    if (ai && opt.use_ai && evidence) {
      const verdict = await auditChange({ trim_name: nameOf.get(a.trim_id) ?? a.trim_id, old_amount_thb: a.prior_amount, new_amount_thb: a.amount_thb, evidence: evidence.evidence }, ai);
      if (verdict.verdict === "WRONG" || verdict.verdict === "UNSURE" || (verdict.verdict === "SKIPPED" && opt.require_audit)) {
        report.held.push({ trim_id: a.trim_id, name: nameOf.get(a.trim_id) ?? a.trim_id, amount_thb: a.amount_thb, why: `auditor ${verdict.verdict}: ${verdict.reason}` });
        continue;
      }
    } else if (opt.require_audit) {
      report.held.push({ trim_id: a.trim_id, name: nameOf.get(a.trim_id) ?? a.trim_id, amount_thb: a.amount_thb, why: "audit required but no AI available" });
      continue;
    }
    applies.push({ trim_id: a.trim_id, amount_thb: a.amount_thb, vat_included: a.vat_included });
  }

  // 8. plan and write
  if (applies.length) {
    const urlText = urls.join(" ");
    const { items, skipped } = planPriceWrites(loaded.snapshot, applies, {
      asOf: opt.today, actor_kind: "OFFICIAL", source: `price_refresh:${job.model_id.split(".")[0]}`, source_ref: urlText.slice(0, 500),
      reviewer: "price-refresh", reason: `price refresh ${opt.run_id}` });
    for (const s of skipped) report.skipped.push(`${nameOf.get(s.trim_id) ?? s.trim_id}: ${s.why}${s.detail ? ` (${s.detail})` : ""}`);
    const priorOf = new Map(loaded.trims.map((t) => [t.trim_id, t.price_thb]));
    if (opt.apply) {
      const results = await ports.applyPriceChanges(`${opt.run_id}:${job.model_id}`, items);
      for (const r of results) {
        const item = applies.find((a) => a.trim_id === r.trim_id)!;
        if (r.status === "APPLIED") report.applied.push({ trim_id: r.trim_id, name: nameOf.get(r.trim_id) ?? r.trim_id, from: priorOf.get(r.trim_id) ?? null, to: item.amount_thb });
        else report.held.push({ trim_id: r.trim_id, name: nameOf.get(r.trim_id) ?? r.trim_id, amount_thb: item.amount_thb, why: `${r.status}${r.error ? `: ${r.error}` : ""}` });
      }
      for (const card of usedCards) if (results.some((r) => r.trim_id === card.payload.trim_id && r.status === "APPLIED")) await ports.markJumpApplied(card);
    } else {
      for (const it of items) {
        const a = applies.find((x) => x.trim_id === it.trim_id)!;
        report.applied.push({ trim_id: it.trim_id, name: nameOf.get(it.trim_id) ?? it.trim_id, from: priorOf.get(it.trim_id) ?? null, to: a.amount_thb });
      }
    }
  }
  return report;
}
