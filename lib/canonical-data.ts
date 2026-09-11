import { publicDb } from "@/lib/supabase";
import {
  canClaimCurrentCommerce,
  isCatalogVisible,
  publicCompatibilityStatus,
  publicRetailLifecycle,
} from "@/lib/public-retail-lifecycle";

const BODY: Record<string, string> = {
  HATCHBACK: "HATCHBACK", SEDAN: "SEDAN", CROSSOVER: "CROSSOVER",
  PPV: "PPV", OFFROAD: "OFFROAD", COUPE: "COUPE", MPV: "MPV",
  PICKUP: "PICKUP", WAGON: "WAGON", VAN: "VAN", TRUCK: "TRUCK", OTHER: "OTHER",
};

function modelRow(row: any) {
  const payload = row.payload || {};
  const brand = payload.brand || {};
  const lifecycle = publicRetailLifecycle(row.status);
  const verifiedCurrent = lifecycle === "CURRENT";
  return {
    ...payload,
    id: row.canonical_id,
    canonical_id: row.canonical_id,
    editorial_id: row.tdr_model_id,
    slug: row.slug,
    name_en: row.name_en,
    name_th: row.name_th,
    generation: payload.generation || row.generation_id?.split(".").at(-1) || null,
    segment: row.segment,
    body_type: BODY[row.body_type] || row.body_type,
    status: publicCompatibilityStatus(row.status),
    retail_lifecycle: lifecycle,
    retail_price_min: verifiedCurrent ? row.retail_price_min : null,
    retail_price_max: verifiedCurrent ? row.retail_price_max : null,
    brands: {
      id: brand.id,
      slug: brand.slug,
      name_en: brand.name_en,
      name_th: brand.name_th,
      logo_url: null,
    },
  };
}

function trimRow(row: any) {
  const detail = row.payload || {};
  const specs = detail.specs || {};
  const lifecycle = publicRetailLifecycle(row.status);
  const list = lifecycle === "CURRENT" ? (row.current_list_price || detail.current_list_price) : null;
  const powertrainId = `canonical-pt:${row.canonical_id}`;
  return {
    ...specs,
    id: row.canonical_id,
    canonical_id: row.canonical_id,
    name: row.name,
    model_id: row.model_id,
    generation_id: row.generation_id,
    variant_id: row.variant_id,
    status: publicCompatibilityStatus(row.status),
    retail_lifecycle: lifecycle,
    powertrain: row.powertrain || specs.powertrain || null,
    price_baht: list?.amount_thb ?? null,
    current_list_price: list || null,
    campaign_quote: lifecycle === "CURRENT" ? (row.campaign_quote || {}) : {},
    price_history: row.price_history || [],
    source_refs: row.source_refs || {},
    trim_powertrains: [{ powertrain_id: powertrainId }],
    _powertrain: {
      id: powertrainId,
      label: `${row.name} ${row.powertrain}`,
      powertrain_type: row.powertrain,
      engine_code: specs.engine_code || null,
      displacement_cc: specs.engine_cc ?? null,
      battery_capacity_kwh: specs.battery_kwh ?? null,
      transmission: specs.transmission || null,
      drivetrain: specs.drivetrain || null,
    },
  };
}

export async function getCanonicalBrands(limit = 150) {
  const db = publicDb();
  if (!db) return [];
  const { data, error } = await db.from("current_vehicle_brands").select("*")
    .order("name_en").limit(limit);
  if (error) throw error;
  return (data || []).map((row: any) => ({
    ...(row.payload || {}),
    id: row.canonical_id,
    canonical_id: row.canonical_id,
    editorial_id: row.tdr_brand_id,
    slug: row.slug,
    name_en: row.name_en,
    name_th: row.name_th,
    country_origin: row.origin_country,
    logo_url: null,
  }));
}

export async function getCanonicalBrand(slug: string) {
  const rows = await getCanonicalBrands(250);
  return rows.find((row: any) => row.slug === slug) || null;
}

export async function getCanonicalModelsByBrand(brandId: string) {
  const rows = await getCanonicalModels(600);
  return rows.filter((row: any) => row.brand_id === brandId && isCatalogVisible(row.retail_lifecycle));
}

export async function getCanonicalModels(limit = 600) {
  const db = publicDb();
  if (!db) return [];
  const { data, error } = await db.from("current_vehicle_models").select("*")
    .order("name_en").limit(limit);
  if (error) throw error;
  return (data || []).map(modelRow);
}

export async function getCanonicalModelBundle(slug: string) {
  const db = publicDb();
  if (!db) return null;
  const { data: model, error: modelError } = await db.from("current_vehicle_models")
    .select("*").eq("slug", slug).maybeSingle();
  if (modelError) throw modelError;
  if (!model) return null;
  const { data: rawTrims, error: trimError } = await db.from("current_market_trims")
    .select("*").eq("model_id", model.canonical_id).order("name");
  if (trimError) throw trimError;

  const row: any = modelRow(model);

  // UNVERIFIED trims are never labelled current or historical. A CURRENT child
  // is also withheld as a current claim until its parent model is CURRENT.
  const trims = (rawTrims || []).map(trimRow)
    .filter((trim: any) => trim.retail_lifecycle === "HISTORICAL"
      || canClaimCurrentCommerce(row.retail_lifecycle, trim.retail_lifecycle));
  const powertrains = trims.map((trim: any) => trim._powertrain);
  const numeric = (key: string) => trims
    .filter((trim: any) => canClaimCurrentCommerce(row.retail_lifecycle, trim.retail_lifecycle))
    .map((trim: any) => Number(trim[key]))
    .filter((value: number) => Number.isFinite(value) && value > 0);
  for (const [modelKey, trimKey] of [
    ["length_mm", "length_mm"], ["width_mm", "width_mm"],
    ["wheelbase_mm", "wheelbase_mm"], ["seats", "seats"],
  ]) {
    const values = numeric(trimKey);
    if (!row[modelKey] && values.length && new Set(values).size === 1) row[modelKey] = values[0];
  }
  return { ...row, powertrains_detail: powertrains,
    trims: trims.map(({ _powertrain, ...trim }: any) => trim) };
}

/** Free compare reads the same active release as the catalogue. Identity/spec
 * rows may remain visible while lifecycle is UNVERIFIED, but HISTORICAL rows
 * are excluded. Current price/campaign fields require both trim and parent
 * model to be verified CURRENT. */
export async function getCanonicalCompareTrims(limit = 600) {
  const db = publicDb();
  if (!db) return [];
  const [{ data: rawTrims, error: trimError }, { data: rawModels, error: modelError }] = await Promise.all([
    db.from("current_market_trims").select("*").order("name").limit(limit),
    db.from("current_vehicle_models").select("*").limit(600),
  ]);
  if (trimError) throw trimError;
  if (modelError) throw modelError;
  const models = new Map((rawModels || []).map((row: any) => [row.canonical_id, modelRow(row)]));
  return (rawTrims || [])
    .map((raw: any) => {
      const trim = trimRow(raw);
      const model: any = models.get(raw.model_id) || null;
      const detail = raw.payload || {};
      const modelLifecycle = model?.retail_lifecycle || "UNVERIFIED";
      const canClaimCommerce = canClaimCurrentCommerce(modelLifecycle, trim.retail_lifecycle);
      return {
        ...trim,
        price_baht: canClaimCommerce ? trim.price_baht : null,
        current_list_price: canClaimCommerce ? trim.current_list_price : null,
        campaign_quote: canClaimCommerce ? trim.campaign_quote : {},
        model_slug: model?.slug || null,
        model_lifecycle: modelLifecycle,
        brand_name: detail.brand || model?.brands?.name_en || "",
        model_name: detail.model || model?.name_en || raw.model_id,
        segment: model?.segment || null,
        body_type: model?.body_type || null,
        production_type: model?.production_type || null,
        production_country: model?.production_country || null,
        model_seats: model?.seats || null,
      };
    })
    .filter((row: any) => isCatalogVisible(row.retail_lifecycle) && isCatalogVisible(row.model_lifecycle))
    .sort((a: any, b: any) => `${a.brand_name} ${a.model_name} ${a.name}`.localeCompare(`${b.brand_name} ${b.model_name} ${b.name}`));
}

export async function getCanonicalRelatedModels(model: any, limit = 8) {
  const rows = await getCanonicalModels(600);
  return rows.filter((row: any) => row.id !== model.id
      && row.brand_id === model.brand_id
      && isCatalogVisible(row.retail_lifecycle))
    .slice(0, limit);
}

export async function searchCanonicalCatalog(query: string) {
  const term = query.trim().toLocaleLowerCase();
  if (!term) return { brands: [], models: [] };
  const [brands, models] = await Promise.all([getCanonicalBrands(), getCanonicalModels()]);
  const hit = (row: any) => [row.name_en, row.name_th, row.slug, row.canonical_id]
    .some((value) => String(value || "").toLocaleLowerCase().includes(term));
  return {
    brands: brands.filter(hit).slice(0, 10),
    models: models.filter((row: any) => isCatalogVisible(row.retail_lifecycle) && hit(row)).slice(0, 20),
  };
}

export async function getModelMarketTeasers(canonicalModelId: string, limit = 4) {
  const db = publicDb();
  if (!db) return [];
  const { data, error } = await db.from("public_model_market_teaser").select("*")
    .eq("canonical_model_id", canonicalModelId).order("period", { ascending: false }).limit(limit);
  if (error) throw error;
  return data || [];
}
