/**
 * Read-only aggregation for the Canonical Vehicle Editor workspace
 * (/admin/vehicles/[modelId]). Every field it returns is read straight from
 * the current_vehicle_* / current_market_trims / current_spec_facts release
 * projections and canonical_input_batches — the same tables every other
 * admin bench (vehicle-input, eco-trims, retail-lifecycle) already reads.
 * This module never writes; all mutation goes through
 * app/admin/vehicle-editor-actions.ts -> lib/canonical-command-builder.ts ->
 * lib/canonical-input-queue.ts, same as the rest of Admin.
 */
import { adminDb } from "@/lib/supabase";
import { oemTargetsForModel, type OemEvidenceTarget } from "@/lib/price-evidence-registry";

export type WorkspaceBrand = { canonicalId: string; nameEn: string; nameTh: string; originCountry: string | null };
export type WorkspaceModel = {
  canonicalId: string;
  tdrModelId: string | null;
  brandId: string;
  nameEn: string;
  nameTh: string;
  generationId: string | null;
  status: string | null;
  segment: string | null;
  bodyType: string | null;
  payload: Record<string, unknown>;
};
export type WorkspaceGeneration = {
  canonicalId: string;
  modelId: string;
  code: string;
  segment: string | null;
  launched: string | null;
  ended: string | null;
};
export type WorkspaceTrim = {
  canonicalId: string;
  modelId: string;
  generationId: string;
  variantId: string | null;
  name: string;
  powertrain: string;
  status: string;
  payload: Record<string, unknown>;
  currentListPrice: { amount_thb?: number; price_type?: string } | null;
  sourceRefs: Record<string, string[]>;
};
export type WorkspaceSpecFact = {
  factId: string;
  trimId: string;
  fieldKey: string;
  verificationStatus: string | null;
  payload: Record<string, unknown>;
};
export type WorkspaceBatch = {
  batchKey: string;
  sourceKind: string;
  itemCount: number;
  status: string;
  pullRequestUrl: string | null;
  releaseId: string | null;
  error: string | null;
  createdAt: string;
  actor: string;
};

export type VehicleWorkspace = {
  releaseId: string;
  releaseYear: number;
  brand: WorkspaceBrand;
  model: WorkspaceModel;
  generation: WorkspaceGeneration | null;
  trims: WorkspaceTrim[];
  specFactsByTrim: Map<string, WorkspaceSpecFact[]>;
  evidenceTargets: OemEvidenceTarget[];
  relatedBatches: WorkspaceBatch[];
};

function releaseYearFromPayload(release: { as_of?: string; payload?: unknown } | null): number {
  const payload = release?.payload && typeof release.payload === "object"
    ? release.payload as Record<string, unknown> : {};
  const year = Number(payload.year || String(release?.as_of || "").slice(0, 4));
  return Number.isInteger(year) && year >= 2000 && year <= 2100 ? year : new Date().getFullYear();
}

export async function loadVehicleWorkspace(modelId: string): Promise<VehicleWorkspace | null> {
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");

  const { data: model, error: modelError } = await db.from("current_vehicle_models")
    .select("release_id,canonical_id,tdr_model_id,brand_id,name_en,name_th,generation_id,status,segment,body_type,payload")
    .eq("canonical_id", modelId).maybeSingle();
  if (modelError) throw modelError;
  if (!model) return null;

  const [
    { data: brand, error: brandError },
    { data: generation, error: generationError },
    { data: trims, error: trimsError },
    { data: release, error: releaseError },
    { data: batches, error: batchesError },
  ] = await Promise.all([
    db.from("current_vehicle_brands").select("canonical_id,name_en,name_th,origin_country").eq("canonical_id", model.brand_id).maybeSingle(),
    model.generation_id
      ? db.from("current_vehicle_generations").select("canonical_id,model_id,code,segment,launched,ended").eq("canonical_id", model.generation_id).maybeSingle()
      : Promise.resolve({ data: null, error: null }),
    db.from("current_market_trims")
      .select("canonical_id,model_id,generation_id,variant_id,name,powertrain,status,payload,current_list_price,source_refs")
      .eq("model_id", modelId).order("name", { ascending: true }).limit(500),
    db.from("canonical_vehicle_releases").select("release_id,as_of,payload").eq("release_id", model.release_id).maybeSingle(),
    db.from("canonical_input_batches")
      .select("batch_key,source_kind,item_count,status,pull_request_url,release_id,error,created_at,actor,payload")
      .order("created_at", { ascending: false }).limit(60),
  ]);
  if (brandError) throw brandError;
  if (generationError) throw generationError;
  if (trimsError) throw trimsError;
  if (releaseError) throw releaseError;
  if (batchesError) throw batchesError;
  if (!brand) throw new Error("หา canonical brand ของรุ่นนี้ไม่ได้");

  const trimRows: WorkspaceTrim[] = (trims || []).map((row: any) => ({
    canonicalId: row.canonical_id,
    modelId: row.model_id,
    generationId: row.generation_id,
    variantId: row.variant_id,
    name: row.name,
    powertrain: row.powertrain,
    status: row.status,
    payload: row.payload || {},
    currentListPrice: row.current_list_price || null,
    sourceRefs: row.source_refs || {},
  }));

  const trimIds = trimRows.map((row) => row.canonicalId);
  const { data: specFacts, error: specError } = trimIds.length
    ? await db.from("current_spec_facts")
        .select("fact_id,trim_id,field_key,verification_status,payload")
        .in("trim_id", trimIds).limit(5000)
    : { data: [] as any[], error: null };
  if (specError) throw specError;

  const specFactsByTrim = new Map<string, WorkspaceSpecFact[]>();
  for (const fact of specFacts || []) {
    const bucket = specFactsByTrim.get(fact.trim_id) || [];
    bucket.push({
      factId: fact.fact_id, trimId: fact.trim_id, fieldKey: fact.field_key,
      verificationStatus: fact.verification_status, payload: fact.payload || {},
    });
    specFactsByTrim.set(fact.trim_id, bucket);
  }

  // canonical_input_batches carries no model FK; a batch is "related" when its
  // payload mentions this model's canonical_id anywhere in its commands. Good
  // enough at admin-bench data volumes (60 most recent batches), same
  // "read the last N and filter in memory" approach vehicle-input/page.tsx
  // already uses for its own pipeline-status table.
  const relatedBatches: WorkspaceBatch[] = (batches || [])
    .filter((row: any) => JSON.stringify(row.payload || {}).includes(modelId))
    .slice(0, 15)
    .map((row: any) => ({
      batchKey: row.batch_key, sourceKind: row.source_kind, itemCount: row.item_count,
      status: row.status, pullRequestUrl: row.pull_request_url, releaseId: row.release_id,
      error: row.error, createdAt: row.created_at, actor: row.actor,
    }));

  return {
    releaseId: model.release_id,
    releaseYear: releaseYearFromPayload(release),
    brand: { canonicalId: brand.canonical_id, nameEn: brand.name_en, nameTh: brand.name_th || "", originCountry: brand.origin_country || null },
    model: {
      canonicalId: model.canonical_id, tdrModelId: model.tdr_model_id || null, brandId: model.brand_id,
      nameEn: model.name_en, nameTh: model.name_th || "", generationId: model.generation_id,
      status: model.status, segment: model.segment, bodyType: model.body_type, payload: model.payload || {},
    },
    generation: generation ? {
      canonicalId: generation.canonical_id, modelId: generation.model_id, code: generation.code,
      segment: generation.segment, launched: generation.launched, ended: generation.ended,
    } : null,
    trims: trimRows,
    specFactsByTrim,
    evidenceTargets: oemTargetsForModel(modelId),
    relatedBatches,
  };
}

export async function listVehicleModelsForPicker(searchTerm: string): Promise<Array<{
  canonicalId: string; brandId: string; nameEn: string; nameTh: string; status: string | null;
}>> {
  const db = adminDb();
  if (!db) return [];
  let query = db.from("current_vehicle_models")
    .select("canonical_id,brand_id,name_en,name_th,status")
    .order("brand_id", { ascending: true }).order("name_en", { ascending: true }).limit(500);
  const term = searchTerm.trim();
  if (term) query = query.or(`name_en.ilike.%${term}%,name_th.ilike.%${term}%,canonical_id.ilike.%${term}%`);
  const { data, error } = await query;
  if (error) throw error;
  return (data || []).map((row: any) => ({
    canonicalId: row.canonical_id, brandId: row.brand_id, nameEn: row.name_en, nameTh: row.name_th || "", status: row.status,
  }));
}

/** Live release_id for one model, used by prepare/confirm actions to compare
 * against the fingerprint carried in the edit session (see
 * lib/canonical-command-builder.ts's isStaleRelease). Deliberately its own
 * tiny query rather than reusing loadVehicleWorkspace, so the staleness
 * check stays cheap and does not depend on unrelated joins succeeding. */
export async function liveModelReleaseId(modelId: string): Promise<string | null> {
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data, error } = await db.from("current_vehicle_models").select("release_id").eq("canonical_id", modelId).maybeSingle();
  if (error) throw error;
  return data?.release_id || null;
}
