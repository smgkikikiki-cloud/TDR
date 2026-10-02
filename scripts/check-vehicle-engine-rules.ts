/**
 * Phase 0 step 4 rule parity: every case in
 * automotive/vehicle_master/tests/fixtures/engine_rule_corpus.json was run
 * through the Python engine (tools/engine_rule_corpus.py); the TypeScript port
 * in lib/vehicle-engine/ must give the same result -- same accept/reject, same
 * value, same message.
 *
 * Database-enforced rules are checked against the same engine in
 * automotive/vehicle_master/tests/test_vehicle_engine_rules_migration_v59.py.
 */
import fs from "node:fs";
import { loadSpecFieldRegistry } from "../lib/spec-field-registry.ts";
import { validateCatalogResolution } from "../lib/vehicle-engine/entities.ts";
import {
  parseCampaign, parsePriceRow, planAppendPrice, planClosePrice, planCorrectPrice, type PricePlan,
} from "../lib/vehicle-engine/pricing.ts";
import { indexes, priceRecord, recomputeModel, recomputeTrim, type MasterRows } from "../lib/vehicle-engine/served.ts";
import { planCurrentRetailSet, planModelOperationalState, planTrimLifecycleReview } from "../lib/vehicle-engine/sidecars.ts";
import { validateFactAgainstRegistry, validateSpecRegistry } from "../lib/vehicle-engine/specs.ts";
import { FacetError, parseFacet, type FacetName } from "../lib/vehicle-engine/taxonomy.ts";

type Row = Record<string, any>;
const corpus = JSON.parse(fs.readFileSync("automotive/vehicle_master/tests/fixtures/engine_rule_corpus.json", "utf8"));

let failed = 0;
let passed = 0;
const canon = (v: unknown): string => v === null || v === undefined ? "null" : Array.isArray(v) ? `[${v.map(canon).join(",")}]`
  : typeof v === "object" ? `{${Object.keys(v as object).sort().map((k) => `${JSON.stringify(k)}:${canon((v as Row)[k])}`).join(",")}}`
  : JSON.stringify(v);

function same(section: string, name: string, got: unknown, want: unknown) {
  if (canon(got) === canon(want)) {
    passed++;
    return;
  }
  failed++;
  if (failed <= 40) console.log(`  FAIL ${section}: ${name}\n       got  ${canon(got).slice(0, 600)}\n       want ${canon(want).slice(0, 600)}`);
}

/** Python-style outcome of a TS call. */
function outcome(fn: () => unknown): Row {
  try {
    return { ok: true, value: fn() };
  } catch (error: any) {
    return { ok: false, error: String(error?.message ?? error), ...(error instanceof FacetError ? { error_type: error.pythonType } : {}) };
  }
}
const pyOutcome = (c: Row, keepType = false) => c.ok
  ? { ok: true, value: c.value }
  : { ok: false, error: c.error, ...(keepType ? { error_type: c.error_type } : {}) };

const sortRows = (rows: Row[]) => [...rows].map(priceRecord).sort((a, b) => (canon(a) < canon(b) ? -1 : 1));

function applyPlan(before: Row[], plan: PricePlan): Row[] {
  if (!plan.changed) return before;
  const rows = before.map((r) => ({ ...r }));
  for (const edit of plan.edits) {
    if (edit.kind === "update") Object.assign(rows[edit.recordIndex], edit.changes);
    else rows.push(edit.row);
  }
  return rows;
}

// 1. Facet parsing --------------------------------------------------------
for (const c of corpus.taxonomy) {
  same("taxonomy", `${c.facet}(${JSON.stringify(c.raw)})`,
    outcome(() => parseFacet(c.facet as FacetName, c.raw)), pyOutcome(c, true));
}

// 2. Resolution-chain rules ------------------------------------------------
for (const c of corpus.resolution) {
  same("resolution", c.name, validateCatalogResolution(c.rows, c.year), c.problems);
}

// 3. Price rows and campaigns: parsing -------------------------------------
const knownTrims = new Set(["acme.a.g1.trim.base_ice"]);
const knownGaps: string[] = [];
for (const c of corpus.price_parse) {
  if (c.js_integral_float) {
    // Python rejects 899000.0 (a float); after JSON.parse it is 899000. Not
    // comparable in JavaScript -- reported, not counted (ENGINE_RULES.md F2).
    knownGaps.push(`price_parse ${JSON.stringify(c.raw)}: Python ${c.ok ? "accepts" : "rejects"}, TS cannot see the float`);
    continue;
  }
  same("price_parse", JSON.stringify(c.raw), outcome(() => parsePriceRow(c.raw, knownTrims)), pyOutcome(c));
}
for (const c of corpus.campaign_parse) {
  same("campaign_parse", JSON.stringify(c.raw), outcome(() => parseCampaign(c.raw)), pyOutcome(c));
}

// 4. Registry and registry-dependent fact rules -----------------------------
for (const c of corpus.registry) {
  same("registry", c.name, outcome(() => validateSpecRegistry(c.registry, c.profiles ?? undefined)), pyOutcome(c));
}
const registry = new Map(loadSpecFieldRegistry(2026).map((f) => [f.key, f]));
for (const c of corpus.facts) {
  same("facts", JSON.stringify(c.fact), validateFactAgainstRegistry(c.fact, registry, c.trim_powertrain), c.problems);
}

// 5. Write planners ---------------------------------------------------------
for (const c of corpus.price_planners) {
  const a = c.args;
  const got = outcome(() => {
    const plan = c.op === "correct"
      ? planCorrectPrice(c.before, {
        trimId: a.trim_id, priceType: a.price_type, amountThb: a.amount_thb, reason: a.reason, reviewer: a.reviewer,
        mode: a.mode, effectiveFrom: a.effective_from ?? null, campaignId: a.campaign_id ?? null,
        optionId: a.option_id ?? null, asOf: a.as_of,
      })
      : planClosePrice(c.before, {
        trimId: a.trim_id, priceType: a.price_type, ends: a.ends, reason: a.reason, reviewer: a.reviewer,
        campaignId: a.campaign_id ?? null, optionId: a.option_id ?? null, asOf: a.as_of,
      });
    return { changed: plan.changed, after: sortRows(applyPlan(c.before, plan)) };
  });
  same("price_planners", c.name, got, c.ok ? { ok: true, value: { changed: c.value.changed, after: sortRows(c.value.after) } } : pyOutcome(c));
}
for (const c of corpus.append_price) {
  const got = outcome(() => ({ after: sortRows(applyPlan(c.before, planAppendPrice(c.before, c.record, { reason: "case", reviewer: "Owner" }) as PricePlan)) }));
  same("append_price", c.name, got, c.ok ? { ok: true, value: { after: sortRows(c.value.after) } } : pyOutcome(c));
}
for (const c of corpus.sidecars) {
  let got: Row;
  if (c.kind === "trim_lifecycle") {
    got = outcome(() => {
      const plan = planTrimLifecycleReview({
        trimId: c.call.trim_id, action: c.call.action, reviewer: c.call.reviewer, reviewedAt: c.call.reviewed_at,
        sourceRef: c.call.source_ref, notes: c.call.notes, bootstrap: c.bootstrap,
      }, { trimExists: c.trim_exists, parentRetailStatus: c.parent_retail_status, approvedSet: c.approved ? new Set(c.approved) : null });
      return { decisions: plan.kind === "upsert" ? [plan.row] : [] };
    });
  } else if (c.kind === "current_retail") {
    got = outcome(() => ({ models: [planCurrentRetailSet({
      modelId: c.call.model_id, trimIds: c.call.trim_ids, reviewer: c.call.reviewer, reviewedAt: c.call.reviewed_at,
      sourceRef: c.call.source_ref, notes: c.call.notes })] }));
  } else {
    got = outcome(() => {
      const plan = planModelOperationalState({ modelId: c.call.model_id, action: c.call.action, reviewer: c.call.reviewer,
        reviewedAt: c.call.reviewed_at, sourceRef: c.call.source_ref, notes: c.call.notes }, true);
      return { decisions: plan.kind === "upsert" ? [plan.row] : [] };
    });
  }
  same("sidecars", `${c.kind}: ${c.name}`, got, pyOutcome(c));
}

// 6. Served values at a pinned as_of ---------------------------------------
for (const c of corpus.served) {
  const r = c.rows;
  const rows: MasterRows = {
    models: r.models, generations: r.generations, variants: r.variants, trims: r.trims, prices: r.prices,
    campaigns: r.campaigns, facts: r.facts, eco: r.eco, registry,
    lifecycle: {
      approved: new Map(Object.entries(r.approved).map(([k, v]) => [k, new Set(v as string[])])),
      decisions: new Map(r.decisions.map((d: Row) => [d.trim_id, d])),
      maintenance: new Set(r.maintenance),
    },
  };
  const cache = indexes(rows);
  for (const want of c.expected.trims) {
    const trim = r.trims.find((t: Row) => t.canonical_id === want.canonical_id);
    same("served", `${c.name}: trim ${want.canonical_id}`, { canonical_id: want.canonical_id, ...recomputeTrim(trim, rows, c.as_of, cache) }, want);
  }
  for (const want of c.expected.models) {
    const model = r.models.find((m: Row) => m.canonical_id === want.canonical_id);
    same("served", `${c.name}: model ${want.canonical_id}`, { canonical_id: want.canonical_id, ...recomputeModel(model, rows, c.as_of, cache) }, want);
  }
}

for (const gap of knownGaps) console.log(`  known gap (not compared): ${gap}`);
console.log(failed ? `\n${failed} of ${passed + failed} engine rule parity case(s) failed` : `\nall ${passed} engine rule parity cases passed (${knownGaps.length} known gap(s) listed above)`);
process.exit(failed ? 1 : 0);
