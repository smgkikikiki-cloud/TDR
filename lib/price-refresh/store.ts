/**
 * Supabase (PostgREST) access for the price refresh run. Service-role only; used from CI, never from the browser.
 * Nothing here decides anything: it loads the rows the pure modules need and sends their results to the database.
 */
import type { ModelSnapshot, RpcItem } from "../vehicle-engine/price-writer.ts";
import type { TrimState } from "../vehicle-engine/trim-reconcile.ts";
import { DEFAULT_AI_SETTINGS, type AiSettings, type UsageRecord } from "./ai.ts";

type Row = Record<string, any>;

export class Rest {
  private base: string;
  private key: string;
  private fetchImpl: typeof fetch;
  constructor(url: string, serviceKey: string, fetchImpl: typeof fetch = fetch) {
    this.base = url.replace(/\/+$/, "");
    this.key = serviceKey;
    this.fetchImpl = fetchImpl;
  }
  private headers(extra: Record<string, string> = {}) {
    return { apikey: this.key, authorization: `Bearer ${this.key}`, "content-type": "application/json", ...extra };
  }
  private async send(path: string, init: RequestInit): Promise<any> {
    const response = await this.fetchImpl(`${this.base}${path}`, init);
    const text = await response.text();
    if (!response.ok) throw new Error(`Supabase ${init.method ?? "GET"} ${path.split("?")[0]} -> ${response.status}: ${text.slice(0, 300)}`);
    return text ? JSON.parse(text) : null;
  }
  /** GET /rest/v1/<table>?<query>, following pages of 1000 rows. */
  async select(table: string, query: string): Promise<Row[]> {
    const out: Row[] = [];
    for (let from = 0; ; from += 1000) {
      const page = await this.send(`/rest/v1/${table}?${query}`, { method: "GET", headers: this.headers({ range: `${from}-${from + 999}`, "range-unit": "items" }) });
      out.push(...page);
      if (page.length < 1000) return out;
    }
  }
  async insert(table: string, rows: Row[]): Promise<void> {
    if (rows.length) await this.send(`/rest/v1/${table}`, { method: "POST", headers: this.headers({ prefer: "return=minimal" }), body: JSON.stringify(rows) });
  }
  async upsert(table: string, rows: Row[], onConflict: string): Promise<void> {
    if (rows.length) await this.send(`/rest/v1/${table}?on_conflict=${onConflict}`, {
      method: "POST", headers: this.headers({ prefer: "resolution=merge-duplicates,return=minimal" }), body: JSON.stringify(rows) });
  }
  async patch(table: string, query: string, values: Row): Promise<void> {
    await this.send(`/rest/v1/${table}?${query}`, { method: "PATCH", headers: this.headers({ prefer: "return=minimal" }), body: JSON.stringify(values) });
  }
  async rpc(name: string, args: Row): Promise<any> {
    return this.send(`/rest/v1/rpc/${name}`, { method: "POST", headers: this.headers(), body: JSON.stringify(args) });
  }
}

const eq = (value: string) => `eq.${encodeURIComponent(value)}`;

// --- settings, usage, runs ------------------------------------------------------------------------------------------

export async function loadAiSettings(rest: Rest): Promise<AiSettings> {
  const rows = await rest.select("vm_settings", "select=key,value");
  const map = new Map(rows.map((r) => [r.key as string, r.value]));
  const num = (key: string, fallback: number) => (typeof map.get(key) === "number" ? (map.get(key) as number) : fallback);
  const rate = map.get("agent_rate_usd_per_mtok") ?? DEFAULT_AI_SETTINGS.rate_usd_per_mtok;
  return {
    monthly_cap_usd: num("agent_monthly_cap_usd", 0),
    cycle_start_day: num("agent_cycle_start_day", 1),
    model: typeof map.get("agent_model") === "string" ? map.get("agent_model") : DEFAULT_AI_SETTINGS.model,
    rate_usd_per_mtok: { input: Number(rate.input), output: Number(rate.output) },
  };
}

/** Usage from the last 62 days: enough for any billing cycle. */
export async function loadUsage(rest: Rest, now: Date): Promise<UsageRecord[]> {
  const since = new Date(now.getTime() - 62 * 86_400_000).toISOString();
  const rows = await rest.select("vm_agent_usage", `select=created_at,cost_usd&created_at=gte.${encodeURIComponent(since)}`);
  return rows.map((r) => ({ at: r.created_at, cost_usd: Number(r.cost_usd) }));
}

export const recordUsage = (rest: Rest, runId: string, skill: string, model: string, input: number, output: number, cost: number) =>
  rest.insert("vm_agent_usage", [{ run_id: runId, skill, model, input_tokens: input, output_tokens: output, cost_usd: cost }]);

export const startRun = (rest: Rest, runId: string, trigger: string, dryRun: boolean) =>
  rest.insert("vm_runs", [{ run_id: runId, trigger, dry_run: dryRun }]);
export const finishRun = (rest: Rest, runId: string, summary: Row) =>
  rest.patch("vm_runs", `run_id=${eq(runId)}`, { finished_at: new Date().toISOString(), summary });

// --- master snapshot ------------------------------------------------------------------------------------------------

export type LoadedModel = { snapshot: ModelSnapshot; brand_name: string; model_name: string; trims: TrimState[] };

export async function loadModel(rest: Rest, modelId: string): Promise<LoadedModel | null> {
  const models = await rest.select("vehicle_models", `select=*&canonical_id=${eq(modelId)}&deleted_at=is.null`);
  if (!models.length) return null;
  const model = models[0];
  const [brands, generations, trims, decisions, approvedSets, maintenance, campaigns] = await Promise.all([
    rest.select("vehicle_brands", `select=name_en&canonical_id=${eq(model.brand_id)}`),
    rest.select("vehicle_generations", `select=*&model_id=${eq(modelId)}&deleted_at=is.null`),
    rest.select("vehicle_trims", `select=*&model_id=${eq(modelId)}&deleted_at=is.null`),
    rest.select("vehicle_trim_lifecycle_decisions", "select=*"),
    rest.select("vehicle_current_retail_sets", `select=*&model_id=${eq(modelId)}`),
    rest.select("vehicle_model_operational_states", `select=model_id&model_id=${eq(modelId)}`),
    rest.select("vehicle_campaigns", `select=*&brand_id=${eq(model.brand_id)}`),
  ]);
  const trimIds = trims.map((t) => t.canonical_id as string);
  const ledger = trimIds.length
    ? await rest.select("vehicle_price_ledger", `select=*&trim_id=in.(${trimIds.map(encodeURIComponent).join(",")})`)
    : [];
  const trimIdSet = new Set(trimIds);
  const prices = ledger.map((r) => ({ ...r.payload, ...stripNulls(r), record_id: r.record_id }));
  const snapshot: ModelSnapshot = {
    model,
    generations: generations.map((g) => ({ ...g.payload, id: g.payload?.id ?? g.canonical_id, model_id: g.model_id, launched: g.launched, ended: g.ended, code: g.code })),
    trims,
    prices,
    campaigns: new Map(campaigns.map((c) => [c.campaign_id, c.payload])),
    lifecycle: {
      approved: new Map(approvedSets.map((s) => [s.model_id, new Set<string>(s.trim_ids)])),
      decisions: new Map(decisions.filter((d) => trimIdSet.has(d.trim_id)).map((d) => [d.trim_id, d])),
      maintenance: new Set(maintenance.map((m) => m.model_id as string)),
    },
  };
  const states: TrimState[] = trims.map((t) => ({
    trim_id: t.canonical_id, name: t.name, aliases: Array.isArray(t.payload?.aliases) ? t.payload.aliases : [],
    status: t.status, price_thb: t.current_list_price?.amount_thb ?? null, name_locked: t.payload?.name_locked === true,
  }));
  return { snapshot, brand_name: brands[0]?.name_en ?? model.brand_id, model_name: model.name_en, trims: states };
}

/** Columns win over the payload copy, but only when the column carries a value. */
function stripNulls(row: Row): Row {
  const out: Row = {};
  for (const [k, v] of Object.entries(row)) if (v !== null && v !== undefined && k !== "payload") out[k] = v;
  for (const k of ["effective_to", "retracted_at"]) if (row[k] === null) out[k] = null;
  return out;
}

// --- prior sightings (for the "same value in two runs" rule and the 7-day rule) ---------------------------------------

export type History = { prior_amounts: Map<string, number>; last_seen: Map<string, string>; first_observed: string | null; read_dates: string[] };

/** `minAgeHours`: a sighting counts as "the previous run" only if it is at least this old (two reads minutes apart are one sighting). */
export async function loadHistory(rest: Rest, modelId: string, now: Date, minAgeHours = 6): Promise<History> {
  const rows = await rest.select("vm_observations",
    `select=trim_id,amount_thb,observed_at,field_key&model_id=${eq(modelId)}&source_kind=eq.SCRAPE&order=observed_at.desc&limit=5000`);
  const cutoff = now.getTime() - minAgeHours * 3_600_000;
  const prior = new Map<string, number>();
  const lastSeen = new Map<string, string>();
  let first: string | null = null;
  const readDates = new Set<string>();
  for (const r of rows) {
    readDates.add(String(r.observed_at).slice(0, 10));
    if (!first || r.observed_at < first) first = r.observed_at;
    if (!r.trim_id) continue;
    if (!lastSeen.has(r.trim_id)) lastSeen.set(r.trim_id, String(r.observed_at).slice(0, 10));
    if (r.field_key === "LIST_PRICE" && r.amount_thb && !prior.has(r.trim_id) && new Date(r.observed_at).getTime() <= cutoff) {
      prior.set(r.trim_id, Number(r.amount_thb));
    }
  }
  return { prior_amounts: prior, last_seen: lastSeen, first_observed: first ? String(first).slice(0, 10) : null, read_dates: [...readDates].sort() };
}

export const insertObservations = (rest: Rest, rows: Row[]) => rest.insert("vm_observations", rows);

// --- source state ----------------------------------------------------------------------------------------------------

export async function loadSourceStates(rest: Rest): Promise<Map<string, Row>> {
  return new Map((await rest.select("vm_source_state", "select=*")).map((r) => [r.target_id as string, r]));
}
export const saveSourceState = (rest: Rest, row: Row) => rest.upsert("vm_source_state", [{ ...row, updated_at: new Date().toISOString() }], "target_id");

// --- inbox -----------------------------------------------------------------------------------------------------------

export const proposeInbox = (rest: Rest, p: { kind: string; dedupe_key: string; model_id: string | null; trim_id: string | null;
  source_hash: string | null; payload: Row }) =>
  rest.rpc("vm_inbox_propose", { p_kind: p.kind, p_dedupe_key: p.dedupe_key, p_model_id: p.model_id, p_trim_id: p.trim_id,
    p_source_hash: p.source_hash, p_payload: p.payload });

/** PRICE_JUMP cards an admin approved and that were not applied yet. */
export async function loadApprovedJumps(rest: Rest, modelId: string): Promise<Row[]> {
  const rows = await rest.select("vm_inbox", `select=*&kind=eq.PRICE_JUMP&status=eq.APPROVED&model_id=${eq(modelId)}`);
  return rows.filter((r) => !r.payload?.applied_at);
}
export const markJumpApplied = (rest: Rest, card: Row) =>
  rest.patch("vm_inbox", `id=${eq(card.id)}`, { payload: { ...card.payload, applied_at: new Date().toISOString() }, updated_at: new Date().toISOString() });

// --- the write ------------------------------------------------------------------------------------------------------

export type ApplyResult = { trim_id: string; status: string; error?: string };
export async function applyPriceChanges(rest: Rest, batchId: string, items: RpcItem[]): Promise<ApplyResult[]> {
  if (!items.length) return [];
  const result = await rest.rpc("vm_apply_price_changes", { p_batch_id: batchId, p_items: items });
  return Array.isArray(result) ? result : (result?.results ?? []);
}
