/**
 * One price refresh over a set of models: fetch -> read -> reconcile -> audit -> write.
 * Everything that touches the outside world comes in through `Ports`, so the whole flow is testable offline
 * (scripts/check-price-run.ts). With `apply: false` nothing is written anywhere.
 */
import { auditChange, extractWithAi, type Budget, type AiSettings, type Messages } from "./ai.ts";
import { extractAnchored, type ExtractedPrice, type KnownTrim, type PageText } from "./extract.ts";
import type { PageFetcher } from "./fetcher.ts";
import type { History, LoadedModel, ApplyResult } from "./store.ts";
import { planPriceWrites, type RpcItem } from "../vehicle-engine/price-writer.ts";
import { normalizeTrimName, reconcileModel, type Observation } from "../vehicle-engine/trim-reconcile.ts";

type Row = Record<string, any>;

export type Ports = {
  fetch: PageFetcher;
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
export type ModelJob = { model_id: string; targets: Target[] };
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
};

const dedupeName = (s: string) => normalizeTrimName(s);

export async function refreshModel(job: ModelJob, ports: Ports, ai: AiPort | null, opt: RunOptions): Promise<ModelReport> {
  const report: ModelReport = { model_id: job.model_id, status: "OK", reason: "", applied: [], held: [], pending: [], jumps: [], proposals: [], skipped: [], fetch_errors: [], observations: 0 };
  const loaded = await ports.loadModel(job.model_id);
  if (!loaded) { report.status = "UNKNOWN_MODEL"; report.reason = "model not in the master"; return report; }
  const nameOf = new Map(loaded.trims.map((t) => [t.trim_id, t.name]));
  const known: KnownTrim[] = loaded.trims.map((t) => ({ trim_id: t.trim_id, name: t.name, aliases: t.aliases }));

  // 1. fetch every page of the model; one failed page stops the whole model (a partial lineup would look like discontinued trims)
  const pages: { target: Target; page: PageText; unchanged: boolean }[] = [];
  for (const target of job.targets) {
    const state = opt.source_state.get(target.id);
    const out = await ports.fetch(target.url);
    const base = { target_id: target.id, url: target.url, model_ids: [job.model_id], last_attempt_at: opt.now.toISOString() };
    if (!out.ok) {
      report.fetch_errors.push(`${target.id}: ${out.error}`);
      const failCount = (state?.fail_count ?? 0) + 1;
      const status = out.kind === "BLOCKED" ? "BLOCKED" : failCount >= 3 ? "BROKEN" : "FAILED";
      if (opt.apply) await ports.saveSourceState({ ...base, status, fail_count: failCount, last_error: out.error });
      continue;
    }
    const unchanged = state?.content_hash === out.page.content_hash;
    pages.push({ target, page: out.page, unchanged });
    if (opt.apply) await ports.saveSourceState({ ...base, status: unchanged ? "UNCHANGED" : "OK", fail_count: 0, last_error: null,
      content_hash: out.page.content_hash, last_success_at: opt.now.toISOString() });
  }
  const extractionOk = report.fetch_errors.length === 0 && pages.length === job.targets.length;

  // 2. read prices: anchored reader first (free), AI only where it can add something and the page actually changed
  type Obs = ExtractedPrice & { target_id: string; url: string; content_hash: string };
  const observations: Obs[] = [];
  if (extractionOk) {
    for (const { target, page, unchanged } of pages) {
      const anchored = extractAnchored(page, known, loaded.brand_name, loaded.model_name);
      const rows: ExtractedPrice[] = [...anchored.observations];
      const currentIds = new Set(loaded.trims.filter((t) => t.status === "CURRENT").map((t) => t.trim_id));
      const missingCurrent = anchored.not_found.some((id) => currentIds.has(id));
      if (ai && opt.use_ai && !unchanged && (missingCurrent || anchored.observations.length === 0)) {
        const aiOut = await extractWithAi(page, known, { ...ai, model_name: `${loaded.brand_name} ${loaded.model_name}` });
        const have = new Set(rows.map((r) => dedupeName(r.name_raw)));
        for (const row of aiOut.rows) if (!have.has(dedupeName(row.name_raw))) rows.push(row);
        for (const r of aiOut.rejected) report.skipped.push(`AI row refused (${r.name || "?"}): ${r.reason}`);
      }
      for (const r of rows) observations.push({ ...r, target_id: target.id, url: page.url, content_hash: page.content_hash });
    }
  }
  report.observations = observations.length;

  // 3. reconcile
  const history = await ports.loadHistory(job.model_id, opt.now);
  const trimStates = loaded.trims.map((t) => ({ ...t, last_seen_at: history.last_seen.get(t.trim_id) ?? null }));
  const obsForReconcile: Observation[] = observations.map((o) => ({ name_raw: o.name_raw, amount_thb: o.amount_thb, vat_included: o.vat_included }));
  const plan = reconcileModel({
    model: { id: job.model_id, brand_name: loaded.brand_name, model_name: loaded.model_name },
    trims: trimStates, observations: obsForReconcile, extraction_ok: extractionOk,
    headline: pages[0]?.page.text.split("\n").find((l) => l.trim())?.slice(0, 200),
    prior_amounts: history.prior_amounts, model_first_observed_at: history.first_observed, read_dates: history.read_dates,
    lineup_complete: job.targets.length > 0 && job.targets.every((t) => t.lineup_complete === true), today: opt.today,
  });
  report.status = plan.status; report.reason = plan.reason;
  const sourceHash = pages.map((p) => p.page.content_hash).sort().join("+") || null;

  // 4. record what was seen (immutable) -- the next run's "same value twice" rule reads these
  const matchedTrim = new Map(plan.matches.map((m) => [m.obs_index, m.trim_id]));
  if (opt.apply && observations.length) {
    await ports.insertObservations(observations.map((o, i) => ({
      run_id: opt.run_id, source_kind: "SCRAPE", field_key: "LIST_PRICE", model_id: job.model_id, trim_id: matchedTrim.get(i) ?? null,
      trim_name_raw: o.name_raw, amount_thb: o.amount_thb, vat_included: o.vat_included, source_url: o.url, content_hash: o.content_hash,
      raw: { evidence: o.evidence, method: o.method, target_id: o.target_id }, observed_at: opt.now.toISOString() })));
  }
  const evidenceFor = new Map<string, ExtractedPrice>();
  for (const m of plan.matches) evidenceFor.set(m.trim_id, observations[m.obs_index]);

  // 5. cards for a human: structure changes, big jumps, broken source
  const propose = async (kind: string, key: string, trimId: string | null, payload: Row) => {
    if (opt.apply) await ports.proposeInbox({ kind, dedupe_key: `${job.model_id}:${key}`, model_id: job.model_id, trim_id: trimId, source_hash: sourceHash, payload });
  };
  if (plan.status === "SOURCE_BROKEN") await propose("SOURCE_BROKEN", "SOURCE_BROKEN", null, { reason: plan.reason, urls: job.targets.map((t) => t.url) });
  for (const p of plan.proposals) {
    report.proposals.push(p.kind + ("name_raw" in p ? `: ${p.name_raw}` : "trim_id" in p ? `: ${p.trim_id}` : ""));
    const keyPart = "trim_id" in p ? p.trim_id : "name_raw" in p ? dedupeName(p.name_raw) : (p as any).reason;
    await propose("STRUCTURE", `${p.kind}:${keyPart}`, "trim_id" in p ? p.trim_id : null, { proposal: p, urls: job.targets.map((t) => t.url) });
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
    const urls = job.targets.map((t) => t.url).join(" ");
    const { items, skipped } = planPriceWrites(loaded.snapshot, applies, {
      asOf: opt.today, actor_kind: "OFFICIAL", source: `price_refresh:${job.model_id.split(".")[0]}`, source_ref: urls.slice(0, 500),
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
