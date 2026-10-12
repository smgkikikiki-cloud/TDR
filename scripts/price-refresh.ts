/**
 * One-click price refresh (VEHICLE_DB_V3 §9.1). Run by .github/workflows/price-refresh.yml; the admin "Refresh All"
 * button dispatches that workflow. Default is a DRY RUN that writes nothing; `--apply` writes.
 *
 *   node --experimental-strip-types scripts/price-refresh.ts [--apply] [--models a,b] [--targets x,y] [--no-ai] [--require-audit] [--trigger name]
 * Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ANTHROPIC_API_KEY (optional; without it no AI is used)
 */
import { readFileSync, writeFileSync, appendFileSync } from "node:fs";
import { Budget, anthropicMessages, DEFAULT_AI_SETTINGS } from "../lib/price-refresh/ai.ts";
import { openBrowserFetcher } from "../lib/price-refresh/fetcher.ts";
import { refreshModel, type AiPort, type ModelJob, type ModelReport, type Ports } from "../lib/price-refresh/run.ts";
import * as store from "../lib/price-refresh/store.ts";

const FEED = "automotive/vehicle_master/vehreg/data/2026/market/pricefeed";
const argv = process.argv.slice(2);
const flag = (name: string) => argv.includes(`--${name}`);
const value = (name: string) => { const i = argv.indexOf(`--${name}`); return i >= 0 ? argv[i + 1] : undefined; };
const list = (name: string) => (value(name) ?? "").split(",").map((s) => s.trim()).filter(Boolean);

const apply = flag("apply");
const now = new Date();
const today = new Date(now.getTime() + 7 * 3_600_000).toISOString().slice(0, 10);   // Thai calendar day
const runId = `pr-${now.toISOString().replace(/[-:T.Z]/g, "").slice(0, 14)}-${Math.random().toString(36).slice(2, 6)}`;

function jobs(): ModelJob[] {
  const targets = JSON.parse(readFileSync(`${FEED}/targets.json`, "utf8"));
  const map = JSON.parse(readFileSync(`${FEED}/target_models.json`, "utf8")).targets as Record<string, string>;
  const onlyModels = list("models");
  const onlyTargets = list("targets");
  const byModel = new Map<string, ModelJob>();
  for (const t of (Array.isArray(targets) ? targets : targets.targets)) {
    const model = map[t.id];
    if (!model || t.role !== "CURRENT_MODEL_PAGE") continue;
    if (onlyModels.length && !onlyModels.includes(model)) continue;
    if (onlyTargets.length && !onlyTargets.includes(t.id)) continue;
    const job = byModel.get(model) ?? { model_id: model, targets: [] };
    job.targets.push({ id: t.id, url: t.url });
    byModel.set(model, job);
  }
  return [...byModel.values()];
}

/** A dry run must work before migration v66 exists: runner tables that are missing read as empty. */
async function soft<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try { return await fn(); } catch (e) { if (apply) throw e; console.log(`  (dry run) ${String((e as Error).message).slice(0, 120)}`); return fallback; }
}

async function main() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SECRET_KEY;
  if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required");
  const rest = new store.Rest(url, key);
  const todo = jobs();
  console.log(`${apply ? "APPLY" : "DRY RUN"} ${runId}: ${todo.length} models, ${todo.reduce((n, j) => n + j.targets.length, 0)} pages`);

  const settings = await soft(() => store.loadAiSettings(rest), DEFAULT_AI_SETTINGS);
  const usage = await soft(() => store.loadUsage(rest, now), []);
  const sourceState = await soft(() => store.loadSourceStates(rest), new Map());
  const budget = new Budget(settings, usage, now);
  const apiKey = process.env.ANTHROPIC_API_KEY;
  const useAi = !flag("no-ai") && !!apiKey && settings.monthly_cap_usd > 0;
  const pendingUsage: Parameters<AiPort["onUsage"]>[] = [];
  const ai: AiPort | null = useAi ? { budget, messages: anthropicMessages(apiKey!), settings, onUsage: (...a) => { pendingUsage.push(a); } } : null;
  console.log(useAi ? `AI on: cap $${settings.monthly_cap_usd}/month, model ${settings.model}` : "AI off (no key, cap 0 or --no-ai): anchored reader only");

  if (apply) await store.startRun(rest, runId, value("trigger") ?? "manual", false);
  const browser = await openBrowserFetcher();
  const ports: Ports = {
    fetch: browser.fetch,
    loadModel: (id) => store.loadModel(rest, id),
    loadHistory: (id, at) => soft(() => store.loadHistory(rest, id, at), { prior_amounts: new Map(), last_seen: new Map(), first_observed: null }),
    loadApprovedJumps: (id) => soft(() => store.loadApprovedJumps(rest, id), []),
    markJumpApplied: (card) => store.markJumpApplied(rest, card),
    insertObservations: (rows) => store.insertObservations(rest, rows),
    proposeInbox: (p) => store.proposeInbox(rest, p),
    applyPriceChanges: (batch, items) => store.applyPriceChanges(rest, batch, items),
    saveSourceState: (row) => store.saveSourceState(rest, row),
  };

  const reports: ModelReport[] = [];
  try {
    for (const job of todo) {
      try {
        const r = await refreshModel(job, ports, ai, { run_id: runId, now, today, apply, use_ai: useAi, require_audit: flag("require-audit"), source_state: sourceState });
        reports.push(r);
        console.log(`${r.model_id.padEnd(32)} ${r.status.padEnd(14)} obs ${r.observations} applied ${r.applied.length} pending ${r.pending.length} held ${r.held.length} jumps ${r.jumps.length} cards ${r.proposals.length}${r.fetch_errors.length ? ` ERR ${r.fetch_errors[0]}` : ""}`);
      } catch (e) {
        // one model failing must not stop the others
        reports.push({ model_id: job.model_id, status: "ERROR", reason: String((e as Error).message).slice(0, 300), applied: [], held: [], pending: [], jumps: [], proposals: [], skipped: [], fetch_errors: [], observations: 0 });
        console.log(`${job.model_id.padEnd(32)} ERROR ${String((e as Error).message).slice(0, 200)}`);
      }
      if (ai?.budget.halted) console.log(`  AI halted: ${ai.budget.halted}`);
    }
  } finally {
    await browser.close();
  }

  if (apply) {
    for (const u of pendingUsage) await store.recordUsage(rest, runId, u[0], u[1], u[2], u[3], u[4]);
    await store.finishRun(rest, runId, summarize(reports));
  }
  writeFileSync("price-refresh-report.json", JSON.stringify({ run_id: runId, apply, today, reports }, null, 2));
  const md = markdown(reports);
  console.log("\n" + md);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, md + "\n");
}

function summarize(reports: ModelReport[]) {
  const sum = (f: (r: ModelReport) => number) => reports.reduce((n, r) => n + f(r), 0);
  return { models: reports.length, applied: sum((r) => r.applied.length), pending: sum((r) => r.pending.length), held: sum((r) => r.held.length),
    jumps: sum((r) => r.jumps.length), cards: sum((r) => r.proposals.length), errors: reports.filter((r) => r.status === "ERROR").length,
    stopped: reports.filter((r) => r.status === "BATCH_STOPPED" || r.status === "SOURCE_BROKEN").length };
}

function markdown(reports: ModelReport[]): string {
  const s = summarize(reports);
  const baht = (n: number | null) => (n === null ? "-" : n.toLocaleString("en-US"));
  const lines = [`## Price refresh ${runId} (${apply ? "applied" : "dry run"})`, "",
    `models ${s.models} · changed ${s.applied} · waiting for 2nd sighting ${s.pending} · held ${s.held} · big jumps ${s.jumps} · cards ${s.cards} · stopped ${s.stopped} · errors ${s.errors}`, ""];
  for (const r of reports) {
    for (const a of r.applied) lines.push(`- ✅ ${r.model_id} · ${a.name}: ${baht(a.from)} → ${baht(a.to)}`);
    for (const h of r.held) lines.push(`- ⏸ ${r.model_id} · ${h.name}: ${baht(h.amount_thb)} held (${h.why})`);
    for (const j of r.jumps) lines.push(`- ⚠️ ${r.model_id} · ${j.name}: ${baht(j.from)} → ${baht(j.to)} needs approval`);
    for (const p of r.pending) lines.push(`- 👀 ${r.model_id} · ${p.name}: saw ${baht(p.amount_thb)} once`);
    if (r.status !== "OK") lines.push(`- ⛔ ${r.model_id}: ${r.status} ${r.reason}`);
  }
  return lines.join("\n");
}

main().catch((e) => { console.error(e); process.exit(1); });
