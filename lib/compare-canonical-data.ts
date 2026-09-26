import { publicDb } from "@/lib/supabase";
import { paginateAll } from "@/lib/paginate-all";

/**
 * Compare has three deliberately different read shapes:
 *
 * 1. opening the picker reads the small model projection (~321 rows);
 * 2. opening one model reads only that model's CURRENT trim rows;
 * 3. running a comparison reads rich payloads for at most four selected trims.
 *
 * Do not collapse these back into a full current_market_trims scan. The trim
 * projection carries large JSON payload/history columns and the picker does not
 * need to know every trim in Thailand just to let somebody choose a model.
 */

const PICKER_COLUMNS = "canonical_id,model_id,name,powertrain,status,current_list_price";
const COMPARE_COLUMNS = "canonical_id,model_id,generation_id,variant_id,name,powertrain,status,payload,current_list_price,campaign_quote";
const MODEL_NAME_COLUMNS = "canonical_id,name_en,name_th,status,payload";
const COMPARE_MODEL_COLUMNS = "canonical_id,slug,name_en,name_th,generation_id,segment,body_type,status,payload";
const MEDIA_COLUMNS = "vehicle_id,visual_key,public_url,image_type,confidence,width,height,source_url,source_type";

type CompareMediaRow = {
  vehicle_id: string;
  visual_key: string;
  public_url: string;
  image_type: string;
  confidence: number | null;
  width: number | null;
  height: number | null;
  source_url: string | null;
  source_type: string | null;
};

type CompareMediaBinding = {
  entity_id: string;
  entity_type: "model" | "generation";
  visual_key: string;
  inherited_from: string | null;
};

const MEDIA_PRIORITY: Record<string, number> = { hero: 0, front_3q: 1 };

function primaryExteriorMedia(rows: CompareMediaRow[]) {
  return rows
    .filter((row) => row.image_type === "hero" || row.image_type === "front_3q")
    .sort((a, b) => {
      const priority = (MEDIA_PRIORITY[a.image_type] ?? 99) - (MEDIA_PRIORITY[b.image_type] ?? 99);
      return priority || Number(b.confidence || 0) - Number(a.confidence || 0);
    })[0] || null;
}

function isCurrentTrim(row: any) {
  return row?.status === "CURRENT";
}

function isCurrentModel(row: any) {
  return row?.status === "CURRENT";
}

function slimModel(row: any) {
  const brand = row.payload?.brand || {};
  return {
    id: row.canonical_id,
    brand: brand.name_en || brand.name_th || "",
    model: row.name_en || row.name_th || row.canonical_id,
  };
}

function modelName(row: any) {
  if (!row) return null;
  const brand = row.payload?.brand || {};
  return {
    brand_name: brand.name_en || brand.name_th || "",
    model_name: row.name_en || row.name_th || row.canonical_id,
  };
}

function slimTrim(raw: any, model: { brand_name: string; model_name: string } | null) {
  const list = raw.current_list_price || null;
  return {
    id: raw.canonical_id,
    model_id: raw.model_id,
    brand_name: model?.brand_name || "",
    model_name: model?.model_name || raw.model_id,
    name: raw.name,
    powertrain: raw.powertrain ?? null,
    price_baht: list?.amount_thb ?? null,
  };
}

async function allSlimModelRows(db: any, pageSize = 1000) {
  return paginateAll<any>(
    (from, to) => db.from("current_vehicle_models")
      .select(MODEL_NAME_COLUMNS)
      .order("canonical_id")
      .range(from, to),
    pageSize,
  );
}

export async function getCanonicalCompareModelOptions() {
  const db = publicDb();
  if (!db) return [];

  const rows = await allSlimModelRows(db);
  return rows
    .filter(isCurrentModel)
    .map(slimModel)
    .sort((a: any, b: any) =>
      `${a.brand} ${a.model}`.localeCompare(`${b.brand} ${b.model}`, "th"),
    );
}

export async function getCanonicalCompareTrimOptionsForModel(modelId: string) {
  const db = publicDb();
  if (!db || !modelId) return [];

  const [{ data: rawTrims, error: trimError }, { data: rawModel, error: modelError }] = await Promise.all([
    db.from("current_market_trims")
      .select(PICKER_COLUMNS)
      .eq("model_id", modelId)
      .eq("status", "CURRENT")
      .order("canonical_id"),
    db.from("current_vehicle_models")
      .select(MODEL_NAME_COLUMNS)
      .eq("canonical_id", modelId)
      .maybeSingle(),
  ]);
  if (trimError) throw trimError;
  if (modelError) throw modelError;

  const model = rawModel && isCurrentModel(rawModel) ? modelName(rawModel) : null;
  if (!model) return [];

  return (rawTrims || [])
    .filter(isCurrentTrim)
    .map((raw: any) => slimTrim(raw, model));
}

export async function getCanonicalCompareTrimOptionsByIds(ids: string[]) {
  const db = publicDb();
  const requested = [...new Set(ids.filter(Boolean))].slice(0, 4);
  if (!db || !requested.length) return [];

  const { data: rawTrims, error: trimError } = await db.from("current_market_trims")
    .select(PICKER_COLUMNS)
    .in("canonical_id", requested);
  if (trimError) throw trimError;

  const currentTrims = (rawTrims || []).filter(isCurrentTrim);
  const modelIds = [...new Set(currentTrims.map((row: any) => row.model_id).filter(Boolean))];
  if (!modelIds.length) return [];

  const { data: rawModels, error: modelError } = await db.from("current_vehicle_models")
    .select(MODEL_NAME_COLUMNS)
    .in("canonical_id", modelIds);
  if (modelError) throw modelError;

  const models = new Map(
    (rawModels || [])
      .filter(isCurrentModel)
      .map((row: any) => [row.canonical_id, modelName(row)]),
  );
  const trims = new Map(
    currentTrims.map((raw: any) => [raw.canonical_id, slimTrim(raw, models.get(raw.model_id) || null)]),
  );

  return requested.map((id) => trims.get(id)).filter(Boolean);
}

/**
 * Compare needs model metadata for at most four selected cars. Keep media
 * lookup at the same grain too: only bindings/assets for those models and
 * their current generations are read. A model binding with no usable hero is
 * an intentional blank override and therefore blocks generation fallback,
 * matching lib/canonical-data.ts.
 */
async function targetedCompareModels(db: any, modelIds: string[]) {
  const requested = [...new Set(modelIds.filter(Boolean))].slice(0, 4);
  if (!requested.length) return new Map<string, any>();

  const { data: rawModels, error: modelError } = await db.from("current_vehicle_models")
    .select(COMPARE_MODEL_COLUMNS)
    .in("canonical_id", requested)
    .eq("status", "CURRENT");
  if (modelError) throw modelError;

  const models = rawModels || [];
  const entityIds = [...new Set(models.flatMap((raw: any) => {
    const generationId = raw.generation_id || raw.payload?.generation_id || null;
    return [raw.canonical_id, generationId].filter(Boolean);
  }))] as string[];

  const mediaIndex = new Map<string, CompareMediaRow | null>();
  if (entityIds.length) {
    const { data: bindingData, error: bindingError } = await db.from("vehicle_media_bindings")
      .select("entity_id,entity_type,visual_key,inherited_from")
      .in("entity_id", entityIds)
      .in("entity_type", ["model", "generation"]);
    if (bindingError) throw bindingError;

    const bindings = (bindingData || []) as CompareMediaBinding[];
    const visualKeys = [...new Set(bindings.map((binding) => binding.visual_key).filter(Boolean))];

    const boundAssetsPromise = visualKeys.length
      ? db.from("vehicle_media_assets")
          .select(MEDIA_COLUMNS)
          .in("visual_key", visualKeys)
          .in("image_type", ["hero", "front_3q"])
          .order("confidence", { ascending: false })
      : Promise.resolve({ data: [], error: null });
    const legacyAssetsPromise = db.from("vehicle_media_assets")
      .select(MEDIA_COLUMNS)
      .in("vehicle_id", entityIds)
      .in("image_type", ["hero", "front_3q"])
      .order("confidence", { ascending: false });

    const [boundAssetsResult, legacyAssetsResult] = await Promise.all([
      boundAssetsPromise,
      legacyAssetsPromise,
    ]);
    if (boundAssetsResult.error) throw boundAssetsResult.error;
    if (legacyAssetsResult.error) throw legacyAssetsResult.error;

    const allAssets = [...(boundAssetsResult.data || []), ...(legacyAssetsResult.data || [])] as CompareMediaRow[];
    const assetsByVisualKey = new Map<string, CompareMediaRow[]>();
    for (const row of allAssets) {
      const bucket = assetsByVisualKey.get(row.visual_key) || [];
      bucket.push(row);
      assetsByVisualKey.set(row.visual_key, bucket);
    }

    for (const binding of bindings) {
      const chosen = primaryExteriorMedia(assetsByVisualKey.get(binding.visual_key) || []);
      if (chosen || binding.entity_type === "model") mediaIndex.set(binding.entity_id, chosen);
    }

    const legacyByVehicle = new Map<string, CompareMediaRow[]>();
    for (const row of (legacyAssetsResult.data || []) as CompareMediaRow[]) {
      if (mediaIndex.has(row.vehicle_id)) continue;
      const bucket = legacyByVehicle.get(row.vehicle_id) || [];
      bucket.push(row);
      legacyByVehicle.set(row.vehicle_id, bucket);
    }
    for (const [vehicleId, rows] of legacyByVehicle) {
      const chosen = primaryExteriorMedia(rows);
      if (chosen && !mediaIndex.has(vehicleId)) mediaIndex.set(vehicleId, chosen);
    }
  }

  return new Map(models.map((raw: any) => {
    const payload = raw.payload || {};
    const brand = payload.brand || {};
    const generationId = raw.generation_id || payload.generation_id || null;
    const media = mediaIndex.has(raw.canonical_id)
      ? mediaIndex.get(raw.canonical_id)
      : generationId ? mediaIndex.get(generationId) : null;
    return [raw.canonical_id, {
      ...payload,
      id: raw.canonical_id,
      canonical_id: raw.canonical_id,
      slug: raw.slug,
      name_en: raw.name_en,
      name_th: raw.name_th,
      generation_id: generationId,
      segment: raw.segment,
      body_type: raw.body_type,
      status: raw.status,
      brands: {
        id: brand.id,
        slug: brand.slug,
        name_en: brand.name_en,
        name_th: brand.name_th,
      },
      image_url: media?.public_url || null,
    }];
  }));
}

function richCompareTrim(raw: any, model: any) {
  const detail = raw.payload || {};
  const specs = detail.specs || {};
  const list = raw.current_list_price || detail.current_list_price || null;

  return {
    ...specs,
    id: raw.canonical_id,
    canonical_id: raw.canonical_id,
    name: raw.name,
    model_id: raw.model_id,
    generation_id: raw.generation_id,
    variant_id: raw.variant_id,
    powertrain: raw.powertrain || specs.powertrain || null,
    price_baht: list?.amount_thb ?? null,
    current_list_price: list,
    campaign_quote: raw.campaign_quote || {},
    comparable_specs: Array.isArray(detail.comparable_specs) ? detail.comparable_specs : null,

    model_slug: model?.slug || null,
    brand_name: detail.brand || model?.brands?.name_en || "",
    model_name: detail.model || model?.name_en || raw.model_id,
    image_url: model?.image_url || null,
    segment: model?.segment || null,
    body_type: model?.body_type || null,
    production_type: model?.production_type || null,
    production_country: model?.production_country || null,
    model_seats: model?.seats || null,
    cab_type: model?.cab_type || null,
    retail_status: raw.status || null,
    launch_year: model?.launch_year || null,
    launch_quarter: model?.launch_quarter || null,
  };
}

export async function getCanonicalCompareTrimsByIds(ids: string[]) {
  const db = publicDb();
  const requested = [...new Set(ids.filter(Boolean))].slice(0, 4);
  if (!db || !requested.length) return [];

  // Rich JSON is fetched only for the rows the reader actually selected.
  const { data: rawTrims, error } = await db.from("current_market_trims")
    .select(COMPARE_COLUMNS)
    .in("canonical_id", requested);
  if (error) throw error;

  const currentTrims = (rawTrims || []).filter(isCurrentTrim);
  const modelIds = [...new Set(currentTrims.map((row: any) => row.model_id).filter(Boolean))];
  const models = await targetedCompareModels(db, modelIds);
  const byId = new Map(
    currentTrims.map((raw: any) => [raw.canonical_id, richCompareTrim(raw, models.get(raw.model_id) || null)]),
  );

  // Preserve request order so comparison columns never jump around because of
  // database row order.
  return requested.map((id) => byId.get(id)).filter(Boolean);
}
