import { publicDb } from "@/lib/supabase";

const BODY: Record<string, string> = {
  HATCHBACK: "HATCHBACK", SEDAN: "SEDAN", CROSSOVER: "CROSSOVER",
  PPV: "PPV", OFFROAD: "OFFROAD", COUPE: "COUPE", MPV: "MPV",
  PICKUP: "PICKUP", WAGON: "WAGON", VAN: "VAN", TRUCK: "TRUCK", OTHER: "OTHER",
};

function modelRow(row: any) {
  const payload = row.payload || {};
  const brand = payload.brand || {};
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
    status: row.status,
    retail_price_min: row.retail_price_min,
    retail_price_max: row.retail_price_max,
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
  const list = row.current_list_price || detail.current_list_price;
  const powertrainId = `canonical-pt:${row.canonical_id}`;
  return {
    ...specs,
    id: row.canonical_id,
    canonical_id: row.canonical_id,
    name: row.name,
    model_id: row.model_id,
    generation_id: row.generation_id,
    variant_id: row.variant_id,
    status: row.status || "current",
    powertrain: row.powertrain || specs.powertrain || null,
    price_baht: list?.amount_thb ?? null,
    current_list_price: list || null,
    campaign_quote: row.campaign_quote || {},
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
  const rows = data || [];

  // logo_url is an optional TDR presentation overlay. Link it through the
  // canonical projection's stable tdr_brand_id foreign key, not a mutable slug.
  // Failure to read optional presentation metadata must never take the canonical
  // catalogue down; the UI already falls back to text initials when logo_url is null.
  const editorialIds = [...new Set(rows.map((row: any) => row.tdr_brand_id).filter(Boolean))];
  const logoByEditorialId = new Map<string, string>();
  if (editorialIds.length) {
    const { data: editorial, error: editorialError } = await db.from("brands")
      .select("id,logo_url").in("id", editorialIds);
    if (!editorialError) {
      for (const row of editorial || []) {
        if (row.logo_url) logoByEditorialId.set(row.id, row.logo_url);
      }
    }
  }

  return rows.map((row: any) => ({
    ...(row.payload || {}),
    id: row.canonical_id,
    canonical_id: row.canonical_id,
    editorial_id: row.tdr_brand_id,
    slug: row.slug,
    name_en: row.name_en,
    name_th: row.name_th,
    country_origin: row.origin_country,
    logo_url: row.tdr_brand_id ? (logoByEditorialId.get(row.tdr_brand_id) || null) : null,
  }));
}

export async function getCanonicalBrand(slug: string) {
  const rows = await getCanonicalBrands(250);
  return rows.find((row: any) => row.slug === slug) || null;
}

export async function getCanonicalModelsByBrand(brandId: string) {
  const rows = await getCanonicalModels(600);
  return rows.filter((row: any) => row.brand_id === brandId);
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
  const trims = (rawTrims || []).map(trimRow);
  const powertrains = trims.map((trim: any) => trim._powertrain);
  const row: any = modelRow(model);
  const numeric = (key: string) => trims.map((trim: any) => Number(trim[key]))
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

/** Free compare reads the same active release as the catalogue. It deliberately
 * returns exact MarketTrim grain so price/spec values are never mixed between
 * variants. Tyre/wheel fields remain canonical data but are not projected onto
 * the public compare object in this product phase. */
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
      return {
        ...trim,
        model_slug: model?.slug || null,
        brand_name: detail.brand || model?.brands?.name_en || "",
        model_name: detail.model || model?.name_en || raw.model_id,
        segment: model?.segment || null,
        body_type: model?.body_type || null,
        production_type: model?.production_type || null,
        production_country: model?.production_country || null,
        model_seats: model?.seats || null,
      };
    })
    .filter((row: any) => String(row.status || "current").toLowerCase() !== "discontinued")
    .sort((a: any, b: any) => `${a.brand_name} ${a.model_name} ${a.name}`.localeCompare(`${b.brand_name} ${b.model_name} ${b.name}`));
}

export async function getCanonicalRelatedModels(model: any, limit = 8) {
  const rows = await getCanonicalModels(600);
  return rows.filter((row: any) => row.id !== model.id && row.brand_id === model.brand_id)
    .slice(0, limit);
}

export async function searchCanonicalCatalog(query: string) {
  const term = query.trim().toLocaleLowerCase();
  if (!term) return { brands: [], models: [] };
  const [brands, models] = await Promise.all([getCanonicalBrands(), getCanonicalModels()]);
  const hit = (row: any) => [row.name_en, row.name_th, row.slug, row.canonical_id]
    .some((value) => String(value || "").toLocaleLowerCase().includes(term));
  return { brands: brands.filter(hit).slice(0, 10), models: models.filter(hit).slice(0, 20) };
}

export async function getModelMarketTeasers(canonicalModelId: string, limit = 4) {
  const db = publicDb();
  if (!db) return [];
  const { data, error } = await db.from("public_model_market_teaser").select("*")
    .eq("canonical_model_id", canonicalModelId).order("period", { ascending: false }).limit(limit);
  if (error) throw error;
  return data || [];
}
