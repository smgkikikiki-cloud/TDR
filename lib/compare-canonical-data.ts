import { getCanonicalModels } from "@/lib/canonical-data";
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
  const [{ data: rawTrims, error }, modelRows] = await Promise.all([
    db.from("current_market_trims")
      .select(COMPARE_COLUMNS)
      .in("canonical_id", requested),
    getCanonicalModels(1000),
  ]);
  if (error) throw error;

  const models = new Map((modelRows || []).map((row: any) => [row.canonical_id, row]));
  const byId = new Map(
    (rawTrims || [])
      .filter(isCurrentTrim)
      .map((raw: any) => [raw.canonical_id, richCompareTrim(raw, models.get(raw.model_id) || null)]),
  );

  // Preserve request order so comparison columns never jump around because of
  // database row order.
  return requested.map((id) => byId.get(id)).filter(Boolean);
}
