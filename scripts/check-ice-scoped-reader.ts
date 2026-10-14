import assert from "node:assert/strict";
import fs from "node:fs";
import { readScopedRegistrationRows, scopedReaderTotals } from "../lib/ice-scoped-reader.ts";

const fixturePath = process.argv[2]
  ?? "automotive/vehicle_master/tests/fixtures/ice_scoped_reader_shared.json";
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8")) as {
  master_version: string;
  materialized: string[];
  scoped_only: string[];
  owner: Array<{
    group_id: string; reg_type: string; action: "APPROVED" | "EXCLUDED" | "PENDING";
    canonical_id: string | null; decision_ref: string; master_version: string;
  }>;
  legacy: Array<{ group_id: string; canonical_id: string; status: "AUTO" | "APPROVED" | "PROPOSED" }>;
  models: Array<{ canonical_id: string; segment: string | null; body_type: string | null }>;
  facts: Array<{
    period: string; province: string; reg_type: string; brand: string;
    model_group_id: string; model_name: string; reg_count: number;
  }>;
};
const rows = readScopedRegistrationRows(
  fixture.facts, fixture.owner.map(row => ({
    model_group_id: row.group_id, reg_type_scope: row.reg_type, status: row.action,
    canonical_model_id: row.canonical_id, decision_ref: row.decision_ref,
    master_version: row.master_version,
  })), fixture.legacy.map(row => ({
    model_group_id: row.group_id, canonical_model_id: row.canonical_id, status: row.status,
  })), fixture.materialized, fixture.master_version, fixture.scoped_only,
);
const summary = scopedReaderTotals(rows, fixture.models);
assert.equal(summary.raw_registrations, fixture.facts.reduce((sum, row) => sum + row.reg_count, 0));
assert.equal(summary.resolved_fact_count, fixture.facts.length);
assert.deepEqual(summary.mapping_status_totals, {
  AMBIGUOUS_LEGACY_ACTIVE: 8,
  LEGACY_ACTIVE: 11,
  OWNER_APPROVED: 53,
  OWNER_EXCLUDED: 5,
  PENDING_MATERIALIZATION: 17,
  SCOPED_CLASS_UNRESOLVED: 2,
  UNMATCHED: 13,
});
assert.deepEqual(summary.canonical_model_totals, {
  "UNMAPPED": 45, "brand.cab": 7, "brand.shared": 46, "legacy.ok": 11,
});
assert.deepEqual(summary.segment_totals, { "Pickup": 7, "SUV": 46, "Sedan": 11, "ไม่ระบุ": 45 });
assert.deepEqual(summary.body_type_totals, { "Other Cab": 7, "SUV": 46, "Sedan": 11, "ไม่ระบุ": 45 });
console.log(JSON.stringify(summary));
