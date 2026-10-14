/**
 * R6 OFFLINE ONLY: exercise ALL 244 FROZEN owner decisions against all 1,407
 * real Ice M7.0 registration-class scope totals. Never touches a database,
 * grants production approval, changes evidence files, or writes owner state.
 *
 * Scope totals stand in for the original period/province fact rows. Separate
 * read-only live DB QA must still prove source parity and v2 PostgreSQL behavior.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import { IceScopedResolver, scopedCoverage } from "../lib/ice-scoped-crosswalk.ts";
import type { OwnerScopedDecision } from "../lib/ice-scoped-crosswalk.ts";
import type { IceRegTrendRow } from "../lib/ice-market-engine.ts";

const base = "data/packages/ice_crosswalk_r6_offline_recovery_M7.0/";
type CsvRow = Record<string, string>;

function readCsv(path: string): CsvRow[] {
  const input = fs.readFileSync(path, "utf8").replace(/^\uFEFF/, "");
  const rawRows: string[][] = [];
  let fields: string[] = [], field = "", quoted = false;
  for (let i = 0; i < input.length; i++) {
    const char = input[i];
    if (quoted) {
      if (char === '"') {
        if (input[i + 1] === '"') { field += '"'; i++; }
        else quoted = false;
      } else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") { fields.push(field); field = ""; }
    else if (char === "\n") {
      fields.push(field.replace(/\r$/, ""));
      if (fields.some(Boolean)) rawRows.push(fields);
      fields = []; field = "";
    } else field += char;
  }
  assert.equal(quoted, false, "unclosed quote in " + path);
  if (field || fields.length) { fields.push(field); rawRows.push(fields); }
  const header = rawRows.shift();
  assert(header && header.length > 2, "missing header in " + path);
  return rawRows.map((row, i) => {
    assert.equal(row.length, header.length, "bad CSV column count " + path + " line " + (i + 2));
    return Object.fromEntries(header.map((key, j) => [key, row[j]]));
  });
}

const owner = readCsv(base + "owner_decision_ledger_244.csv");
const scopes = readCsv(base + "qa/filtered_identity_manifest/final_scope_dispositions.csv");
assert.equal(owner.length, 244);
assert.equal(scopes.length, 1407);
assert.equal(new Set(owner.map(x => x.decision_id)).size, 244);
assert.equal(new Set(owner.map(x => x.model_group_id)).size, 244);
assert(owner.every(x => x.reg_type_scope === ""), "original owner ledger is group-grain ALL only; do not silently invent class overrides");
assert.deepEqual(Object.fromEntries(
  ["KEEP_EXISTING_AUTO", "OWNER_LINK_EXISTING", "OWNER_CREATE_IDENTITY", "OWNER_EXCLUDE_FROM_COUNT"]
    .map(action => [action, owner.filter(x => x.owner_action === action).length]),
), {
  KEEP_EXISTING_AUTO: 63, OWNER_LINK_EXISTING: 92,
  OWNER_CREATE_IDENTITY: 38, OWNER_EXCLUDE_FROM_COUNT: 51,
});

const approvedCreates = new Set(owner.filter(x => x.owner_action === "OWNER_CREATE_IDENTITY")
  .map(x => x.canonical_target_id));
assert.equal(approvedCreates.size, 38, "frozen CREATE targets must be distinct");
// Only the EXISTING subset is materialized for this specific offline replay:
// production presence is checked separately by R6's READ-ONLY live reconciliation.
const existingTargets = new Set<string>();
for (const d of owner) {
  if (d.owner_action === "KEEP_EXISTING_AUTO") existingTargets.add(d.canonical_target_id);
  if (d.owner_action === "OWNER_LINK_EXISTING" && !approvedCreates.has(d.canonical_target_id)) {
    existingTargets.add(d.canonical_target_id);
  }
}
assert(owner.filter(x => x.owner_action === "OWNER_LINK_EXISTING"
  && approvedCreates.has(x.canonical_target_id)).length === 28,
  "all 28 nonmaterialized LINK targets must depend on already-approved frozen CREATEs");

const decisions: OwnerScopedDecision[] = owner.map(d => {
  assert(d.model_group_id && d.decision_id,
    "owner record missing source or evidence " + d.decision_id);
  if (d.owner_action === "OWNER_EXCLUDE_FROM_COUNT") {
    assert.equal(d.canonical_target_id, "", "owner exclusion cannot carry a canonical target");
  } else assert(d.canonical_target_id, "owner target missing " + d.decision_id);
  let status: OwnerScopedDecision["status"];
  if (d.owner_action === "OWNER_EXCLUDE_FROM_COUNT") status = "EXCLUDED";
  else if (d.owner_action === "OWNER_CREATE_IDENTITY") status = "PENDING";
  else status = "APPROVED";
  return {
    model_group_id: d.model_group_id,
    reg_type_scope: "ALL",
    status,
    canonical_model_id: status === "APPROVED" ? d.canonical_target_id : null,
    decision_ref: d.decision_id,
    master_version: "7.0",
  };
});
const uniqScopes = new Set<string>();
const unitsFor = (r: CsvRow): number => {
  const n = Number(r.registrations);
  assert(Number.isSafeInteger(n) && n >= 0, "invalid Ice unit count");
  return n;
};
const facts: IceRegTrendRow[] = scopes.map(s => {
  const key = JSON.stringify([s.model_group_id, s.reg_type]);
  assert(!uniqScopes.has(key), "duplicate class scope " + key);
  uniqScopes.add(key);
  return {
    period: "M7.0_ALL_PERIODS_SCOPE_AGGREGATE_ONLY",
    province: "ALL_PROVINCES_SCOPE_AGGREGATE_ONLY",
    reg_type: s.reg_type, brand: s.brand,
    model_group_id: s.model_group_id, model_name: s.ice_model_name,
    reg_count: unitsFor(s),
  };
});
assert.equal(new Set(facts.map(x => x.model_group_id)).size, 1200);
const scopeTargets = new Map<string, Set<string>>();
for (const s of scopes) {
  if (!s.canonical_id) continue;
  const targets = scopeTargets.get(s.model_group_id) ?? new Set<string>();
  targets.add(s.canonical_id);
  scopeTargets.set(s.model_group_id, targets);
}
const classSplitGroups = new Set([...scopeTargets].filter(([, ts]) => ts.size > 1).map(([g]) => g));
assert.equal(classSplitGroups.size, 9, "class-split candidate count changed; needs human review");
assert(!owner.some(x => classSplitGroups.has(x.model_group_id)),
  "new owner decision on a class-split group: must review scoped precedence before ALL application");

const resolver = new IceScopedResolver(
  decisions, [], [...existingTargets], "7.0", [...classSplitGroups],
);
const resolved = resolver.resolveRows(facts);
assert.equal(resolved.length, 1407, "one output per source scope; no multiplied fact");
const rawUnits = facts.reduce((n, x) => n + x.reg_count, 0);
const resultUnits = resolved.reduce((n, x) => n + x.reg_count, 0);
assert.equal(rawUnits, 4_141_987);
assert.equal(resultUnits, 4_141_987, "Ice registrations may neither vanish nor multiply");
const ownerByGroup = new Map(owner.map(x => [x.model_group_id, x]));
const seen = new Set<string>();
const statusUnits: Record<string, number> = {};
for (const fact of resolved) {
  statusUnits[fact.mapping_status] = (statusUnits[fact.mapping_status] ?? 0) + fact.reg_count;
  const d = ownerByGroup.get(fact.model_group_id);
  if (!d) {
    assert.equal(fact.canonical_model_id, null, "no unapproved canonical guesses");
    assert.equal(fact.owner_decision_ref, null);
    continue;
  }
  seen.add(d.decision_id);
  assert.equal(fact.owner_decision_ref, d.decision_id,
    "approved source decision must take precedence on every class scope");
  const expected = d.owner_action === "OWNER_EXCLUDE_FROM_COUNT" ? "OWNER_EXCLUDED"
    : d.owner_action === "OWNER_CREATE_IDENTITY" ? "OWNER_PENDING"
    : d.owner_action === "OWNER_LINK_EXISTING" && approvedCreates.has(d.canonical_target_id)
      ? "PENDING_MATERIALIZATION" : "OWNER_APPROVED";
  assert.equal(fact.mapping_status, expected, "incorrect decision precedence " + d.decision_id);
  assert.equal(fact.canonical_model_id,
    expected === "OWNER_APPROVED" ? d.canonical_target_id : null,
    "pending or excluded decision cannot create a live canonical link");
}
assert.equal(seen.size, 244, "must exercise EVERY original owner decision, not just read the ledger");
for (const g of classSplitGroups) {
  assert(resolved.filter(x => x.model_group_id === g)
    .every(x => x.mapping_status === "SCOPED_CLASS_UNRESOLVED" && x.canonical_model_id === null),
    "class split cannot be flattened or auto-linked without exact-class authority " + g);
}
const coverage = scopedCoverage(resolved);
assert.equal(coverage.fixed_denominator, 4_141_987);
assert.equal(Object.values(statusUnits).reduce((a, n) => a + n, 0), 4_141_987);
assert(coverage.covered_units < coverage.fixed_denominator,
  "owner replay is a partial mapping, not R6 approval or ≥99.1% acceptance");
console.log(JSON.stringify({
  type: "r6_offline_owner_244_replay", status: "PASS_OFFLINE_ONLY",
  original_owner_decisions_exercised: seen.size,
  class_scopes: resolved.length, source_groups: 1200,
  frozen_source_units: rawUnits, resolved_units: resultUnits,
  class_split_groups_requiring_exact_scope: classSplitGroups.size,
  owner_create_targets_still_pending: approvedCreates.size,
  existing_canonical_targets_simulated: existingTargets.size,
  status_units: statusUnits,
  candidate_coverage_not_production_approval: coverage,
}, null, 2));
