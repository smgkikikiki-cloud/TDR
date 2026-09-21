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
import { trimEditorFields } from "@/lib/spec-field-registry";
import { normalizeTrimForEditor, type NormalizedTrim } from "@/lib/trim-editor-state";

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
  /** The raw projection row. Kept for provenance/debugging only -- nothing
   * reads a field out of it directly, because the nesting is not something
   * callers should have to know (see lib/trim-editor-state.ts). */
  payload: Record<string, unknown>;
  currentListPrice: { amount_thb?: number; price_type?: string } | null;
  /** Every price ever recorded for this trim, newest first. */
  prices: WorkspacePrice[];
  /** The campaign currently quoted for this trim, if any. */
  campaign: WorkspaceCampaign | null;
  sourceRefs: Record<string, string[]>;
  /** THE editor state: flat, one entry per UI field, MarketTrim columns and
   * comparable-spec facts already folded together. Page, diff, server action
   * and validation all read this and nothing else. */
  editor: NormalizedTrim;
};
export type WorkspacePrice = {
  amountThb: number;
  priceType: string;
  effectiveFrom: string | null;
  effectiveTo: string | null;
  observedAt: string | null;
  campaignId: string | null;
  optionId: string | null;
  source: string | null;
};
/** The live campaign behind a trim's promotion price, as the release
 *  projected it. Gifts and the window belong to the campaign. */
export type WorkspaceCampaign = {
  campaignId: string | null;
  optionId: string | null;
  amountThb: number | null;
  gifts: string;
  starts: string | null;
  ends: string | null;
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

/** The campaign a trim is currently quoting, out of the release's own
 *  campaign_quote. Options are alternatives, and the manual price form
 *  edits one promotion, so the first live option is the one it shows. */
function firstCampaignOffer(quote: unknown): WorkspaceCampaign | null {
  const offers = (quote as any)?.campaign_options;
  const offer = Array.isArray(offers) ? offers[0] : null;
  if (!offer) return null;
  return {
    campaignId: offer.campaign_id ?? null,
    optionId: offer.option_id ?? null,
    amountThb: typeof offer.amount_thb === "number" ? offer.amount_thb : null,
    gifts: String(offer.gifts || ""),
    starts: offer.campaign_starts ?? null,
    ends: offer.campaign_ends ?? offer.valid_to ?? null,
  };
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
    { data: prices },
  ] = await Promise.all([
    db.from("current_vehicle_brands").select("canonical_id,name_en,name_th,origin_country").eq("canonical_id", model.brand_id).maybeSingle(),
    model.generation_id
      ? db.from("current_vehicle_generations").select("canonical_id,model_id,code,segment,launched,ended").eq("canonical_id", model.generation_id).maybeSingle()
      : Promise.resolve({ data: null, error: null }),
    db.from("current_market_trims")
      .select("canonical_id,model_id,generation_id,variant_id,name,powertrain,status,payload,current_list_price,campaign_quote,source_refs")
      .eq("model_id", modelId).order("name", { ascending: true }).limit(500),
    db.from("canonical_vehicle_releases").select("release_id,as_of,payload").eq("release_id", model.release_id).maybeSingle(),
    db.from("canonical_input_batches")
      .select("batch_key,source_kind,item_count,status,pull_request_url,release_id,error,created_at,actor,payload")
      .order("created_at", { ascending: false }).limit(60),
    // Price history belongs on the car, not on a separate bench: the trim's
    // own row is where somebody asks what it costs and what it cost before.
    // Scoped to this model's release -- the projection is keyed by release,
    // so reading it unfiltered stacks every release's prices on top of each
    // other and the newest one wins by luck of the sort order.
    db.from("canonical_price_projection")
      .select("trim_id,amount_thb,price_type,effective_from,effective_to,observed_at,campaign_id,option_id,source,payload")
      .eq("release_id", model.release_id)
      .order("observed_at", { ascending: false }).limit(2000),
  ]);
  if (brandError) throw brandError;
  if (generationError) throw generationError;
  if (trimsError) throw trimsError;
  if (releaseError) throw releaseError;
  if (batchesError) throw batchesError;
  if (!brand) throw new Error("หา canonical brand ของรุ่นนี้ไม่ได้");

  const trimIds = (trims || []).map((row: any) => row.canonical_id);
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

  // One normalization pass, here, for every trim. Everything downstream --
  // the form, the diff, the server action's validation -- reads
  // trim.editor.editableSpecs and never the raw payload nesting.
  const releaseYear = releaseYearFromPayload(release);
  const fields = trimEditorFields(releaseYear);
  const pricesByTrim = new Map<string, WorkspacePrice[]>();
  for (const row of (prices || []) as any[]) {
    const bucket = pricesByTrim.get(row.trim_id) || [];
    bucket.push({
      amountThb: Number(row.amount_thb), priceType: String(row.price_type || ""),
      effectiveFrom: row.effective_from || null, effectiveTo: row.effective_to || null,
      observedAt: row.observed_at || null, campaignId: row.campaign_id || null,
      optionId: row.option_id || null, source: row.source || null,
    });
    pricesByTrim.set(row.trim_id, bucket);
  }

  const trimRows: WorkspaceTrim[] = (trims || []).map((row: any) => ({
    prices: pricesByTrim.get(row.canonical_id) || [],
    // Gifts and the campaign window live on the campaign, so they are read
    // from the trim's own quote rather than guessed at from a price row.
    campaign: firstCampaignOffer(row.campaign_quote),
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
    editor: normalizeTrimForEditor({
      payload: row.payload || {},
      fields,
      extraFacts: (specFactsByTrim.get(row.canonical_id) || []).map((fact) => ({
        field_key: fact.fieldKey, ...fact.payload,
      })),
      canonicalId: row.canonical_id,
      generationId: row.generation_id,
      name: row.name,
      powertrain: row.powertrain,
      sourceRefs: row.source_refs || {},
    }),
  }));

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
    releaseYear,
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
  tdrModelId: string | null;
}>> {
  const db = adminDb();
  if (!db) return [];
  let query = db.from("current_vehicle_models")
    .select("canonical_id,brand_id,name_en,name_th,status,tdr_model_id")
    .order("brand_id", { ascending: true }).order("name_en", { ascending: true }).limit(500);
  const term = searchTerm.trim();
  if (term) query = query.or(`name_en.ilike.%${term}%,name_th.ilike.%${term}%,canonical_id.ilike.%${term}%`);
  const { data, error } = await query;
  if (error) throw error;
  return (data || []).map((row: any) => ({
    canonicalId: row.canonical_id, brandId: row.brand_id, nameEn: row.name_en,
    nameTh: row.name_th || "", status: row.status, tdrModelId: row.tdr_model_id || null,
  }));
}

/** Every trim of a set of models, for a picker that must not guess.
 *
 *  Used where a source published the grade itself and the owner is binding
 *  that label to the trim it names. Scoped to the models in play rather
 *  than listing the whole catalogue: a thousand options in a select is not
 *  a choice anybody can make. */
export async function listVehicleTrimsForPicker(modelIds: string[]): Promise<Array<{
  canonicalId: string; modelId: string; name: string;
}>> {
  const db = adminDb();
  if (!db || !modelIds.length) return [];
  const { data, error } = await db.from("current_market_trims")
    .select("canonical_id,model_id,name")
    .in("model_id", modelIds)
    .order("model_id", { ascending: true }).order("name", { ascending: true }).limit(2000);
  if (error) throw error;
  return (data || []).map((row: any) => ({
    canonicalId: row.canonical_id, modelId: row.model_id, name: row.name,
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
