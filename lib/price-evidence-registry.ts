import targetsRegistry from "@/automotive/vehicle_master/vehreg/data/2026/market/pricefeed/targets.json";

export type OemEvidenceTarget = {
  id: string;
  sourceId: string;
  url: string;
  role: string;
  modelId: string;
  notes: string;
};

type RegistryTarget = {
  id?: unknown;
  source_id?: unknown;
  url?: unknown;
  role?: unknown;
  model_hint?: unknown;
  notes?: unknown;
  enabled?: unknown;
};

type RegistryProfile = {
  source_id?: unknown;
  kind?: unknown;
};

function registryRows(): RegistryTarget[] {
  return Array.isArray((targetsRegistry as any)?.targets)
    ? (targetsRegistry as any).targets as RegistryTarget[]
    : [];
}

function oemSourceIds(): Set<string> {
  const profiles = Array.isArray((targetsRegistry as any)?.source_profiles)
    ? (targetsRegistry as any).source_profiles as RegistryProfile[]
    : [];
  return new Set(profiles
    .filter((row) => String(row?.kind || "").trim().toUpperCase() === "OEM")
    .map((row) => String(row?.source_id || "").trim())
    .filter(Boolean));
}

export function oemTargetsForModel(modelId: string): OemEvidenceTarget[] {
  const canonicalModelId = String(modelId || "").trim();
  if (!canonicalModelId) return [];
  const sourceIds = oemSourceIds();
  return registryRows()
    .filter((row) => row?.enabled !== false)
    .filter((row) => String(row?.model_hint || "").trim() === canonicalModelId)
    .filter((row) => sourceIds.has(String(row?.source_id || "").trim()))
    .map((row) => ({
      id: String(row?.id || "").trim(),
      sourceId: String(row?.source_id || "").trim(),
      url: String(row?.url || "").trim(),
      role: String(row?.role || "").trim(),
      modelId: canonicalModelId,
      notes: String(row?.notes || "").trim(),
    }))
    .filter((row) => row.id && row.sourceId && row.url)
    .sort((a, b) => a.id.localeCompare(b.id));
}

export function resolveOemTarget(targetId: string, modelId: string): OemEvidenceTarget | null {
  const wanted = String(targetId || "").trim();
  if (!wanted) return null;
  return oemTargetsForModel(modelId).find((row) => row.id === wanted) || null;
}
