export type HistoricalModelBaseline = {
  canonical_model_id: string;
  catalog_year: number;
  origin_country: string | null;
  import_type: string | null;
};

export type HistoricalModelChange = {
  canonical_model_id: string;
  effective_month: string;
  origin_country: string | null;
  import_type: string | null;
  note?: string | null;
};

export type HistoricalModelStatePayload = {
  catalog_years: number[];
  model_year_baselines: HistoricalModelBaseline[];
  monthly_changes: HistoricalModelChange[];
  seed_rows?: number;
  aliased_seed_rows?: number;
};

type HistoricalResolvedState = {
  origin_country: string;
  import_type: string;
  baseline_found: boolean;
};

type HistoricalModelStateIndex = {
  baselines: Map<string, HistoricalModelBaseline>;
  changes: Map<string, HistoricalModelChange[]>;
};

let activeCache: { releaseId: string; index: HistoricalModelStateIndex } | null = null;

function baselineKey(modelId: string, year: number) {
  return `${modelId}\u0000${year}`;
}

function monthToken(value: string) {
  return String(value || "").slice(0, 7);
}

export function compileHistoricalModelState(payload: HistoricalModelStatePayload): HistoricalModelStateIndex {
  const baselines = new Map<string, HistoricalModelBaseline>();
  for (const row of payload.model_year_baselines || []) {
    if (!row?.canonical_model_id || !Number.isFinite(Number(row.catalog_year))) continue;
    baselines.set(baselineKey(String(row.canonical_model_id), Number(row.catalog_year)), row);
  }

  const changes = new Map<string, HistoricalModelChange[]>();
  for (const row of payload.monthly_changes || []) {
    if (!row?.canonical_model_id || !/^\d{4}-\d{2}$/.test(String(row.effective_month || ""))) continue;
    const key = String(row.canonical_model_id);
    const list = changes.get(key) || [];
    list.push(row);
    changes.set(key, list);
  }
  for (const list of changes.values()) {
    list.sort((a, b) => String(a.effective_month).localeCompare(String(b.effective_month)));
  }
  return { baselines, changes };
}

export function resolveHistoricalModelState(
  index: HistoricalModelStateIndex,
  modelId: string | null | undefined,
  period: string,
): HistoricalResolvedState {
  if (!modelId) return { origin_country: "UNKNOWN", import_type: "UNKNOWN", baseline_found: false };
  const year = Number(String(period).slice(0, 4));
  if (!Number.isFinite(year)) return { origin_country: "UNKNOWN", import_type: "UNKNOWN", baseline_found: false };
  const baseline = index.baselines.get(baselineKey(String(modelId), year));
  if (!baseline) return { origin_country: "UNKNOWN", import_type: "UNKNOWN", baseline_found: false };

  let originCountry = String(baseline.origin_country || "UNKNOWN");
  let importType = String(baseline.import_type || "UNKNOWN");
  const asOf = monthToken(period);
  for (const change of index.changes.get(String(modelId)) || []) {
    if (String(change.effective_month) > asOf) break;
    if (change.origin_country != null && String(change.origin_country).trim()) {
      originCountry = String(change.origin_country);
    }
    if (change.import_type != null && String(change.import_type).trim()) {
      importType = String(change.import_type);
    }
  }
  return { origin_country: originCountry, import_type: importType, baseline_found: true };
}

export async function getActiveHistoricalModelState(db: any): Promise<HistoricalModelStateIndex | null> {
  const { data: stateRow, error: stateError } = await db
    .from("canonical_vehicle_state")
    .select("active_release_id")
    .eq("scope", "vehicle_catalog")
    .maybeSingle();
  if (stateError) throw new Error(`canonical release state query failed: ${stateError.message}`);
  const releaseId = String(stateRow?.active_release_id || "");
  if (!releaseId) return null;
  if (activeCache?.releaseId === releaseId) return activeCache.index;

  const { data: releaseRow, error: releaseError } = await db
    .from("canonical_vehicle_releases")
    .select("release_id,payload")
    .eq("release_id", releaseId)
    .maybeSingle();
  if (releaseError) throw new Error(`canonical release payload query failed: ${releaseError.message}`);
  const payload = (releaseRow?.payload as any)?.historical_model_state as HistoricalModelStatePayload | undefined;
  if (!payload || !Array.isArray(payload.model_year_baselines) || !Array.isArray(payload.monthly_changes)) return null;
  const index = compileHistoricalModelState(payload);
  activeCache = { releaseId, index };
  return index;
}
