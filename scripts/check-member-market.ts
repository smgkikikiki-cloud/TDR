import fs from "node:fs";
import { normalizeRequestedMarketScopes } from "../lib/market-scope.ts";
import { defaultMarketPeriod, provisionalMarketPeriods } from "../lib/member-market.ts";
import {
  getActiveMarketPriceState,
  MARKET_PRICE_MIN_COVERAGE_PCT,
  marketPriceBandForAmount,
  priceStateModelCoverage,
  resolveListPriceOn,
  resolveModelPriceBand,
  type MarketPriceState,
} from "../lib/market-price-state.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else console.log(`  ok   ${name}`);
}

console.log("paid market — scope contract");
check("no scope request defaults to CORE plus honest mixed-grain residual", normalizeRequestedMarketScopes(), ["CORE", "MIXED"]);
check("explicit all scopes removes the scope filter", normalizeRequestedMarketScopes(["all"]), undefined);
check("explicit scope stays normalized and keeps mixed residual", normalizeRequestedMarketScopes(["niche", "core", "core"]), ["NICHE", "CORE", "MIXED"]);

console.log("\npaid market — provisional month default");
const coverage = [
  ["2026-01-01", 100], ["2026-02-01", 110], ["2026-03-01", 90],
  ["2026-04-01", 105], ["2026-05-01", 95], ["2026-06-01", 100],
  ["2026-07-01", 20],
].map(([period, total]) => ({ period: String(period), total_registrations: Number(total) }));
check("stub month is labelled provisional", [...provisionalMarketPeriods(coverage)], ["2026-07"]);
check("workspace opens on latest settled month", defaultMarketPeriod(coverage), "2026-06");

console.log("\npaid market — period price contract");
check("price band lower edge", marketPriceBandForAmount(499_999), "ENTRY");
check("price band volume", marketPriceBandForAmount(500_000), "VOLUME");
check("price band upper", marketPriceBandForAmount(1_000_000), "UPPER");
check("price band luxury starts at 1.8m", marketPriceBandForAmount(1_800_000), "LUXURY");
check("paid price cohort minimum is fail-closed at 80%", MARKET_PRICE_MIN_COVERAGE_PCT, 80);

const observedOnly = [{
  trim_id: "m.g.t1", amount_thb: 900_000, price_type: "LIST_PRICE",
  effective_from: null, effective_to: null, observed_at: "2026-09-08", payload: {},
}];
check("observed-only list price is never backcast", resolveListPriceOn(observedOnly, "2026-08-31"), null);
check("observed-only list price starts on observation date", resolveListPriceOn(observedOnly, "2026-09-30"), 900_000);
check("campaign price never defines MSRP cohort", resolveListPriceOn([{ ...observedOnly[0], price_type: "CAMPAIGN_PRICE", amount_thb: 599_000 }], "2026-09-30"), null);
check("conflicting list prices at the same canonical start fail closed", resolveListPriceOn([
  observedOnly[0], { ...observedOnly[0], amount_thb: 950_000 },
], "2026-09-30"), null);

const fakeState: MarketPriceState = {
  releaseId: "test",
  trimsByModel: new Map([
    ["single", [{ trimId: "single.t1", generationId: "g1" }]],
    ["mixed", [{ trimId: "mixed.t1", generationId: "g1" }, { trimId: "mixed.t2", generationId: "g1" }]],
    ["partial", [{ trimId: "partial.t1", generationId: "g1" }, { trimId: "partial.t2", generationId: "g1" }]],
  ]),
  generations: new Map([["g1", { launched: "2020-01-01", ended: null }]]),
  listPricesByTrim: new Map([
    ["single.t1", [{ ...observedOnly[0], trim_id: "single.t1" }]],
    ["mixed.t1", [{ ...observedOnly[0], trim_id: "mixed.t1", amount_thb: 900_000 }]],
    ["mixed.t2", [{ ...observedOnly[0], trim_id: "mixed.t2", amount_thb: 1_100_000 }]],
    ["partial.t1", [{ ...observedOnly[0], trim_id: "partial.t1", amount_thb: 900_000 }]],
  ]),
};
check("one verified band resolves model cohort", resolveModelPriceBand(fakeState, "single", "2026-09"), "VOLUME");
check("cross-band model is MIXED rather than guessed", resolveModelPriceBand(fakeState, "mixed", "2026-09"), "MIXED");
check("missing active trim price makes model UNKNOWN", resolveModelPriceBand(fakeState, "partial", "2026-09"), "UNKNOWN");

console.log("\npaid market — price state reads the master-backed serving views, same results (Phase 0 step 3)");
// Stand-in for the Supabase client. Every request is capped at 1,000 rows
// like PostgREST. Rows come back in each relation's natural scan order unless
// .order() is given: the old projection-backed reads came back in index order
// (trims by canonical_id, prices by record_id); the master tables do not.
type Row = Record<string, any>;
function fakeDb(tables: Record<string, { rows: Row[]; scanOrder?: string }>) {
  const reads: { table: string; order: string | null; filters: string[] }[] = [];
  const from = (table: string) => {
    const read = { table, order: null as string | null, filters: [] as string[] };
    reads.push(read);
    const source = tables[table];
    let rows = source ? [...source.rows] : [];
    let window: [number, number] = [0, 999];
    const byKey = (key: string) => (a: Row, b: Row) => String(a[key]).localeCompare(String(b[key]));
    const result = () => {
      if (!source) return { data: null, error: { message: `relation ${table} does not exist` } };
      const key = read.order || source.scanOrder;
      const ordered = key ? [...rows].sort(byKey(key)) : rows;
      return { data: ordered.slice(window[0], Math.min(window[1], window[0] + 999) + 1), error: null };
    };
    const builder: any = {
      select: () => builder,
      eq: (column: string, value: unknown) => { read.filters.push(`${column}=${value}`); rows = rows.filter((r) => r[column] === value); return builder; },
      order: (column: string) => { read.order = column; return builder; },
      limit: (n: number) => { window = [0, n - 1]; return builder; },
      range: (a: number, b: number) => { window = [a, b]; return builder; },
      maybeSingle: async () => { const { data, error } = result(); return { data: data?.[0] ?? null, error }; },
      then: (resolve: any, reject: any) => Promise.resolve(result()).then(resolve, reject),
    };
    return builder;
  };
  return { db: { from }, reads };
}

// The loader as it was on main @ baecc3698 (before Phase 0 step 3), frozen
// here as the reference the new loader must reproduce exactly.
async function legacyMarketPriceState(db: any): Promise<MarketPriceState | null> {
  const dateOnly = (value: unknown) => { const text = String(value || "").slice(0, 10); return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : null; };
  const { data: stateRow } = await db.from("canonical_vehicle_state").select("active_release_id").limit(1).maybeSingle();
  const releaseId = String(stateRow?.active_release_id || "");
  if (!releaseId) return null;
  const [trimResult, generationResult, priceResult] = await Promise.all([
    db.from("current_market_trims").select("canonical_id,model_id,generation_id").limit(1000),
    db.from("current_vehicle_generations").select("canonical_id,launched,ended").limit(1000),
    db.from("canonical_price_projection")
      .select("trim_id,amount_thb,price_type,effective_from,effective_to,observed_at,payload")
      .eq("release_id", releaseId)
      .limit(5000),
  ]);
  const trimsByModel = new Map<string, { trimId: string; generationId: string | null }[]>();
  for (const row of trimResult.data || []) {
    if (!row.canonical_id || !row.model_id) continue;
    const list = trimsByModel.get(String(row.model_id)) || [];
    list.push({ trimId: String(row.canonical_id), generationId: row.generation_id ? String(row.generation_id) : null });
    trimsByModel.set(String(row.model_id), list);
  }
  const generations = new Map<string, { launched: string | null; ended: string | null }>();
  for (const row of generationResult.data || []) {
    if (row.canonical_id) generations.set(String(row.canonical_id), { launched: dateOnly(row.launched), ended: dateOnly(row.ended) });
  }
  const listPricesByTrim = new Map<string, any[]>();
  for (const row of priceResult.data || []) {
    if (!row.trim_id || String(row.price_type || "").toUpperCase() !== "LIST_PRICE") continue;
    const list = listPricesByTrim.get(String(row.trim_id)) || [];
    list.push(row);
    listPricesByTrim.set(String(row.trim_id), list);
  }
  return { releaseId, trimsByModel, generations, listPricesByTrim };
}

{
  const RELEASE = "vehicle-2026-a8e647b7db765c78";
  let seed = 7;
  const rand = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const hex = () => Math.floor(rand() * 16 ** 8).toString(16).padStart(8, "0");
  const shuffle = <T,>(rows: T[]) => rows.map((row) => [rand(), row] as const).sort((a, b) => a[0] - b[0]).map(([, row]) => row);

  // 323 models, 1,569 trims (production's shape): more than one 1,000-row page.
  const generations: Row[] = [];
  const trims: Row[] = [];
  for (let m = 0; m < 323; m++) {
    const model = `b${String(m % 62).padStart(2, "0")}.m${String(m).padStart(3, "0")}`;
    const generation = `${model}.g1`;
    const ended = m % 17 === 0 ? "2026-03-01" : null;
    generations.push({ canonical_id: generation, launched: m % 13 === 0 ? "2026-08-01" : "2019-01-01", ended });
    const count = m < 278 ? 5 : 4;
    for (let t = 0; t < count && trims.length < 1_569; t++) {
      trims.push({ release_id: RELEASE, canonical_id: `${generation}.trim.t${t}`, model_id: model, generation_id: generation });
    }
  }
  while (trims.length < 1_569) {
    const generation = generations[trims.length % 323].canonical_id as string;
    trims.push({ release_id: RELEASE, canonical_id: `${generation}.trim.x${trims.length}`, model_id: generation.replace(/\.g1$/, ""), generation_id: generation });
  }
  // 1,004 served prices (production's count), random record ids, mixed types,
  // dates, retractions and amounts across every band; some trims unpriced.
  const prices: Row[] = [];
  // Every third model is fully list-priced: one band, or across bands.
  trims.forEach((trim, t) => {
    const m = Number(String(trim.model_id).slice(-3));
    if (m % 3 !== 0) return;
    prices.push({
      release_id: RELEASE, record_id: hex() + hex() + hex(), trim_id: trim.canonical_id,
      amount_thb: m % 6 === 0 ? [699_000, 1_299_000][t % 2] : [349_000, 699_000, 1_299_000, 2_490_000][Math.floor(m / 6) % 4],
      price_type: "LIST_PRICE", effective_from: "2025-01-01", effective_to: null, observed_at: "2025-01-01", payload: {},
    });
  });
  for (let i = 0; prices.length < 1_004; i++) {
    const trim = trims[Math.floor(rand() * trims.length)];
    const kind = rand();
    prices.push({
      release_id: RELEASE, record_id: hex() + hex() + hex(), trim_id: trim.canonical_id,
      amount_thb: [349_000, 699_000, 1_299_000, 2_490_000][Math.floor(rand() * 4)] + (i % 3) * 10_000,
      price_type: kind < 0.8 ? "LIST_PRICE" : kind < 0.9 ? "CAMPAIGN_PRICE" : "FINANCE_PRICE",
      effective_from: rand() < 0.7 ? ["2025-06-01", "2026-01-01", "2026-07-15", "2026-09-10"][Math.floor(rand() * 4)] : null,
      effective_to: rand() < 0.1 ? "2026-08-31" : null,
      observed_at: ["2025-05-01", "2026-02-01", "2026-09-20"][Math.floor(rand() * 3)],
      payload: rand() < 0.03 ? { retracted_at: "2026-09-01" } : {},
    });
  }

  const legacy = fakeDb({
    canonical_vehicle_state: { rows: [{ scope: "vehicle_catalog", active_release_id: RELEASE }] },
    current_market_trims: { rows: shuffle(trims), scanOrder: "canonical_id" },
    current_vehicle_generations: { rows: shuffle(generations) },
    canonical_price_projection: { rows: shuffle([...prices, { ...prices[0], release_id: "vehicle-2026-older", record_id: "0", amount_thb: 1 }]), scanOrder: "record_id" },
  });
  const step3 = fakeDb({
    // The master tables' scan order is not the projection's index order.
    current_market_trims: { rows: shuffle(trims) },
    current_vehicle_generations: { rows: shuffle(generations) },
    current_price_ledger: { rows: shuffle(prices) },
    canonical_price_projection: { rows: [{ ...prices[0], amount_thb: 1 }], scanOrder: "record_id" },
    canonical_vehicle_state: { rows: [{ scope: "vehicle_catalog", active_release_id: "vehicle-2026-other" }] },
  });
  const before = await legacyMarketPriceState(legacy.db);
  const after = await getActiveMarketPriceState(step3.db);

  const periods: string[] = [];
  for (let year = 2025; year <= 2026; year++) for (let month = 1; month <= 12; month++) periods.push(`${year}-${String(month).padStart(2, "0")}`);
  const models = [...new Set(trims.map((trim) => String(trim.model_id)))].sort();
  const bands = (state: MarketPriceState | null) => periods.flatMap((period) => models.map((model) => resolveModelPriceBand(state, model, period)));
  const coverage = (state: MarketPriceState | null) => periods.map((period) => priceStateModelCoverage(state, period));

  check("fixture exceeds one 1,000-row page", [trims.length, prices.length], [1_569, 1_004]);
  check("fixture has priced, mixed and unknown models", ["ENTRY", "VOLUME", "UPPER", "LUXURY", "MIXED", "UNKNOWN"].every((band) => bands(before).includes(band as any)), true);
  check("same release id as the legacy loader", after?.releaseId, before?.releaseId);
  check("same trims loaded (the legacy 1,000-trim window)", [...(after?.trimsByModel.values() || [])].flat(), [...(before?.trimsByModel.values() || [])].flat());
  check("same list-price rows loaded (the legacy 1,000-price window)",
    [...(after?.listPricesByTrim.entries() || [])].sort().map(([k, v]) => [k, v.length]),
    [...(before?.listPricesByTrim.entries() || [])].sort().map(([k, v]) => [k, v.length]));
  check(`same band for every model × month (${models.length} × ${periods.length})`, bands(after), bands(before));
  check("same price coverage for every month", coverage(after), coverage(before));
  check("still capped: 1,000 of 1,569 trims (M4 debt, not fixed in step 3)", [...(after?.trimsByModel.values() || [])].flat().length, 1_000);

  const tablesRead = [...new Set(step3.reads.map((read) => read.table))].sort();
  check("reads only the serving views", tablesRead, ["current_market_trims", "current_price_ledger", "current_vehicle_generations"]);
  check("never reads canonical_price_projection", tablesRead.includes("canonical_price_projection"), false);
  check("trims read in canonical_id order", step3.reads.filter((r) => r.table === "current_market_trims" && r.order).map((r) => r.order), ["canonical_id"]);
  check("prices read in record_id order", step3.reads.filter((r) => r.table === "current_price_ledger").map((r) => r.order), ["record_id"]);
  check("prices are not release-filtered on the client", step3.reads.some((r) => r.filters.length > 0), false);
  check("return shape unchanged", Object.keys(after || {}).sort(), ["generations", "listPricesByTrim", "releaseId", "trimsByModel"]);

  // Control: the same capped reads without an explicit order, over the
  // master's scan order, would NOT match -- the order is what preserves it.
  const unordered = await legacyMarketPriceState(fakeDb({
    canonical_vehicle_state: { rows: [{ scope: "vehicle_catalog", active_release_id: RELEASE }] },
    current_market_trims: { rows: shuffle(trims) },
    current_vehicle_generations: { rows: shuffle(generations) },
    canonical_price_projection: { rows: shuffle(prices) },
  }).db);
  check("control: an unordered capped read over the master would change bands", JSON.stringify(bands(unordered)) === JSON.stringify(bands(before)), false);
}
{
  const { db } = fakeDb({ current_market_trims: { rows: [] }, current_vehicle_generations: { rows: [] }, current_price_ledger: { rows: [] } });
  check("no served rows means no price state", await getActiveMarketPriceState(db), null);
}
const priceStateSource = fs.readFileSync("lib/market-price-state.ts", "utf8");
check("market-price-state source has no projection read", priceStateSource.includes("canonical_price_projection"), false);

console.log("\npaid market — trend keeps the full selected scope");
const workspace = fs.readFileSync("app/member/market/MarketWorkspace.tsx", "utf8");
check("trend helper can override ranking dimension without changing applied filter state", workspace.includes('dimension: string = filters.dimension'), true);
// The trend sparkline moved server-side (folded into the same paid
// request that already consumed quota for the main ranking, instead of
// the client making up to 6 more separate fetches) -- see
// app/api/report/market/route.ts. It still uses the same neutral
// non-UI-exposed oem_group dimension so every selected
// Brand/Model/Segment/Body/Powertrain/DLT filter stays applied instead of
// opening the currently ranked dimension.
const marketRouteForTrend = fs.readFileSync("app/api/report/market/route.ts", "utf8");
check("server-side trend uses the neutral oem_group dimension, not the ranked dimension", marketRouteForTrend.includes('dimension: "oem_group"'), true);
check("server-side trend reuses the applied filters rather than reopening them", marketRouteForTrend.includes("const trendFilters = { ...filters }"), true);

console.log("\npaid market — price API stays canonical and fail-closed");
const marketApi = fs.readFileSync("app/api/report/market/route.ts", "utf8");
check("API accepts explicit canonical price band", marketApi.includes('searchParams.get("price_band")'), true);
check("API reads active canonical price state", marketApi.includes("getActiveMarketPriceState"), true);
check("API blocks low verified price coverage", marketApi.includes("verified canonical LIST_PRICE coverage is too low"), true);
check("API does not use legacy models table as a price fallback", marketApi.includes('from("models")'), false);
check("rolling price cohorts stay blocked until fact-month slicing is supported", marketApi.includes("price-band filtering is currently month-grain only"), true);

console.log(failed ? `\n${failed} check(s) failed` : "\nall member market checks passed");
process.exit(failed ? 1 : 0);