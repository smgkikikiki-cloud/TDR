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

// model-a's powertrain/market_position genuinely change year over year (a
// real case this exact scenario caught: toyota.corolla_cross was MIXED
// 2021-2023 -- an ICE variant alongside the HEV -- then HEV-only from 2024
// once the ICE variant was discontinued). oem_group/brand_origin/market_scope
// stay flat across years here to keep the fixture legible; the same
// mechanism applies to a value that does change (an OEM ownership move, a
// CORE->NICHE reclassification).
const payload: HistoricalModelStatePayload = {
  catalog_years: [2024, 2025],
  model_year_baselines: [
    { canonical_model_id: "model-a", catalog_year: 2024, origin_country: "CN", import_type: "CBU",
      powertrain: "MIXED", market_position: "VOLUME", oem_group: "Toyota Motor", brand_origin: "JP", market_scope: "CORE" },
    { canonical_model_id: "model-a", catalog_year: 2025, origin_country: "JP", import_type: "CBU",
      powertrain: "HEV", market_position: "UPPER", oem_group: "Toyota Motor", brand_origin: "JP", market_scope: "CORE" },
  ],
  monthly_changes: [
    { canonical_model_id: "model-a", effective_month: "2024-07", origin_country: "TH", import_type: null },
    { canonical_model_id: "model-a", effective_month: "2024-09", origin_country: null, import_type: "CKD" },
    { canonical_model_id: "model-a", effective_month: "2025-05", origin_country: "ID", import_type: null },
  ],
};

const index = compileHistoricalModelState(payload);

const y2024 = { powertrain: "MIXED", market_position: "VOLUME", oem_group: "Toyota Motor", brand_origin: "JP", market_scope: "CORE" };
const y2025 = { powertrain: "HEV", market_position: "UPPER", oem_group: "Toyota Motor", brand_origin: "JP", market_scope: "CORE" };
const unresolved = {
  origin_country: "UNKNOWN", import_type: "UNKNOWN", powertrain: "UNKNOWN",
  market_position: "UNKNOWN", oem_group: "UNKNOWN", brand_origin: "UNKNOWN",
  market_scope: "UNKNOWN", baseline_found: false,
};

console.log("historical model state — year baseline plus sparse per-field carry-forward (origin/import)");
check("before first change uses that year's catalog baseline",
  resolveHistoricalModelState(index, "model-a", "2024-01-01"),
  { origin_country: "CN", import_type: "CBU", ...y2024, baseline_found: true });
check("origin-only change does not erase import type",
  resolveHistoricalModelState(index, "model-a", "2024-08-01"),
  { origin_country: "TH", import_type: "CBU", ...y2024, baseline_found: true });
check("later import-only change preserves carried origin",
  resolveHistoricalModelState(index, "model-a", "2024-10-01"),
  { origin_country: "TH", import_type: "CKD", ...y2024, baseline_found: true });
check("reviewed changes carry across catalog-year boundaries like legacy monthly_state",
  resolveHistoricalModelState(index, "model-a", "2025-01-01"),
  { origin_country: "TH", import_type: "CKD", ...y2025, baseline_found: true });
check("newer field-specific change wins without resetting sibling state",
  resolveHistoricalModelState(index, "model-a", "2025-06-01"),
  { origin_country: "ID", import_type: "CKD", ...y2025, baseline_found: true });
check("missing year baseline fails closed instead of backcasting current state",
  resolveHistoricalModelState(index, "model-a", "2023-12-01"), unresolved);
check("unmapped model stays unknown",
  resolveHistoricalModelState(index, null, "2025-06-01"), unresolved);

console.log("\nhistorical model state — powertrain/market_position/oem_group/brand_origin/market_scope resolve from the year baseline alone");
check("2024 reads the 2024 catalog's powertrain and market position, not 2025's",
  resolveHistoricalModelState(index, "model-a", "2024-11-15"),
  { origin_country: "TH", import_type: "CKD", ...y2024, baseline_found: true });
check("crossing into 2025 immediately reads 2025's catalog values -- no monthly carry-forward delay, unlike origin/import",
  resolveHistoricalModelState(index, "model-a", "2025-02-01"),
  { origin_country: "TH", import_type: "CKD", ...y2025, baseline_found: true });
check("a nameplate that gained a hybrid variant does not read MIXED for the year it was still ICE-only",
  resolveHistoricalModelState(index, "model-a", "2024-01-01").powertrain, "MIXED");
check("...and reads its real single-powertrain year once it actually was one",
  resolveHistoricalModelState(index, "model-a", "2025-01-01").powertrain, "HEV");

console.log(failed ? `\n${failed} check(s) failed` : "\nall historical model state checks passed");
process.exit(failed ? 1 : 0);
