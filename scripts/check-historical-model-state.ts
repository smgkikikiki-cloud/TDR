import {
  compileHistoricalModelState,
  resolveHistoricalModelState,
  type HistoricalModelStatePayload,
} from "../lib/historical-model-state.ts";

let failed = 0;
function check(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  } else {
    console.log(`  ok   ${name}`);
  }
}

const payload: HistoricalModelStatePayload = {
  catalog_years: [2024, 2025],
  model_year_baselines: [
    { canonical_model_id: "model-a", catalog_year: 2024, origin_country: "CN", import_type: "CBU" },
    { canonical_model_id: "model-a", catalog_year: 2025, origin_country: "JP", import_type: "CBU" },
  ],
  monthly_changes: [
    { canonical_model_id: "model-a", effective_month: "2024-07", origin_country: "TH", import_type: null },
    { canonical_model_id: "model-a", effective_month: "2024-09", origin_country: null, import_type: "CKD" },
    { canonical_model_id: "model-a", effective_month: "2025-05", origin_country: "ID", import_type: null },
  ],
};

const index = compileHistoricalModelState(payload);

console.log("historical model state — year baseline plus sparse per-field carry-forward");
check("before first change uses that year's catalog baseline",
  resolveHistoricalModelState(index, "model-a", "2024-01-01"),
  { origin_country: "CN", import_type: "CBU", baseline_found: true });
check("origin-only change does not erase import type",
  resolveHistoricalModelState(index, "model-a", "2024-08-01"),
  { origin_country: "TH", import_type: "CBU", baseline_found: true });
check("later import-only change preserves carried origin",
  resolveHistoricalModelState(index, "model-a", "2024-10-01"),
  { origin_country: "TH", import_type: "CKD", baseline_found: true });
check("reviewed changes carry across catalog-year boundaries like legacy monthly_state",
  resolveHistoricalModelState(index, "model-a", "2025-01-01"),
  { origin_country: "TH", import_type: "CKD", baseline_found: true });
check("newer field-specific change wins without resetting sibling state",
  resolveHistoricalModelState(index, "model-a", "2025-06-01"),
  { origin_country: "ID", import_type: "CKD", baseline_found: true });
check("missing year baseline fails closed instead of backcasting current state",
  resolveHistoricalModelState(index, "model-a", "2023-12-01"),
  { origin_country: "UNKNOWN", import_type: "UNKNOWN", baseline_found: false });
check("unmapped model stays unknown",
  resolveHistoricalModelState(index, null, "2025-06-01"),
  { origin_country: "UNKNOWN", import_type: "UNKNOWN", baseline_found: false });

console.log(failed ? `\n${failed} check(s) failed` : "\nall historical model state checks passed");
process.exit(failed ? 1 : 0);
