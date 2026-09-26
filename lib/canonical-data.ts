import { publicDb } from "@/lib/supabase";

const BODY: Record<string, string> = {
  HATCHBACK: "HATCHBACK", SEDAN: "SEDAN", CROSSOVER: "CROSSOVER",
  PPV: "PPV", OFFROAD: "OFFROAD", COUPE: "COUPE", MPV: "MPV",
  PICKUP: "PICKUP", WAGON: "WAGON", VAN: "VAN", TRUCK: "TRUCK", OTHER: "OTHER",
};

const MEDIA_PRIORITY: Record<string, number> = {
  hero: 0,
  front_3q: 1,
  side: 2,
  rear_3q: 3,
  dashboard: 4,
  interior: 5,
  cargo: 6,
  detail: 7,
  unknown: 8,
};

type CanonicalMediaRow = {
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

type CanonicalMediaBinding = {
  entity_id: string;
  entity_type: "model" | "generation" | "trim";
  visual_key: string;
  inherited_from: string | null;
};

function compareMedia(a: CanonicalMediaRow, b: CanonicalMediaRow) {
  const priority = (MEDIA_PRIORITY[a.image_type] ?? 99) - (MEDIA_PRIORITY[b.image_type] ?? 99);
  if (priority) return priority;
  return Number(b.confidence || 0) - Number(a.confidence || 0);
}

/** Card/detail hero selection is intentionally conservative: only a canonical
 * hero or front three-quarter exterior may become the primary vehicle image.
 * Interior/cargo/detail assets stay available in the media gallery but never
 * silently become a catalogue thumbnail. */
function primaryExteriorMedia(rows: CanonicalMediaRow[]) {
  return rows
    .filter((row) => row.image_type === "hero" || row.image_type === "front_3q")
    .sort(compareMedia)[0] || null;
}

async function getCanonicalPrimaryMediaIndex() {
  const db = publicDb();
  const index = new Map<string, CanonicalMediaRow | null>();
  if (!db) return index;

  const [{ data: bindingData, error: bindingError }, { data: mediaData, error: mediaError }] = await Promise.all([
    db.from("vehicle_media_bindings")
      .select("entity_id,entity_type,visual_key,inherited_from")
      .in("entity_type", ["model", "generation"]),
    db.from("vehicle_media_assets")
      .select("vehicle_id,visual_key,public_url,image_type,confidence,width,height,source_url,source_type")
      .in("image_type", ["hero", "front_3q"])
      .order("confidence", { ascending: false }),
  ]);
  if (bindingError) throw bindingError;
  if (mediaError) throw mediaError;

  const assetsByVisualKey = new Map<string, CanonicalMediaRow[]>();
  for (const row of (mediaData || []) as CanonicalMediaRow[]) {
    const bucket = assetsByVisualKey.get(row.visual_key) || [];
    bucket.push(row);
    assetsByVisualKey.set(row.visual_key, bucket);
  }

  for (const binding of (bindingData || []) as CanonicalMediaBinding[]) {
    const chosen = primaryExteriorMedia(assetsByVisualKey.get(binding.visual_key) || []);
    // A model binding with no asset is an intentional blank override.
    if (chosen || binding.entity_type === "model") index.set(binding.entity_id, chosen);
  }

  // Backward-compatible fallback for media rows created before bindings were
  // available. New publisher writes always create the generation binding.
  const legacyByVehicle = new Map<string, CanonicalMediaRow[]>();
  for (const row of (mediaData || []) as CanonicalMediaRow[]) {
    if (index.has(row.vehicle_id)) continue;
    const bucket = legacyByVehicle.get(row.vehicle_id) || [];
    bucket.push(row);
    legacyByVehicle.set(row.vehicle_id, bucket);
  }
  for (const [vehicleId, rows] of legacyByVehicle) {
    const chosen = primaryExteriorMedia(rows);
    if (chosen && !index.has(vehicleId)) index.set(vehicleId, chosen);
  }

  return index;
}

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
    generation_id: row.generation_id || payload.generation_id || null,
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
      // Not the brand logo: the canonical model payload carries the brand's
      // identity, not its presentation, and this row has no tdr_brand_id to
      // link one through. Every page that renders a logo reads it from
      // getCanonicalBrands() instead.
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
    // SpecLedger.resolved() as of the release. The trim page and the
    // comparison both read it; without it a trim can only show the handful of
    // columns MarketTrim itself carries.
    comparable_specs: Array.isArray(detail.comparable_specs) ? detail.comparable_specs : null,
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

export async function getCanonicalVehicleMedia(entityId: string) {
  const db = publicDb();
  if (!db || !entityId) return [];

  const { data: binding, error: bindingError } = await db.from("vehicle_media_bindings")
    .select("entity_id,entity_type,visual_key,inherited_from")
    .eq("entity_id", entityId)
    .maybeSingle();
  if (bindingError) throw bindingError;

  const visualKey = (binding as CanonicalMediaBinding | null)?.visual_key || entityId;
  const { data, error } = await db.from("vehicle_media_assets")
    .select("vehicle_id,visual_key,public_url,image_type,confidence,width,height,source_url,source_type")
    .eq("visual_key", visualKey)
    .order("confidence", { ascending: false });
  if (error) throw error;
  return ((data || []) as CanonicalMediaRow[]).sort(compareMedia);
}

/** A model override is null when absent, [] when intentionally blank. */
export async function getCanonicalModelHeadOverride(modelId: string): Promise<CanonicalMediaRow[] | null> {
  const db = publicDb();
  if (!db) return null;
  const { data: binding, error } = await db.from("vehicle_media_bindings")
    .select("visual_key").eq("entity_id", modelId).eq("entity_type", "model").maybeSingle();
  if (error) throw error;
  if (!binding) return null;
  const { data: assets, error: assetError } = await db.from("vehicle_media_assets")
    .select("vehicle_id,visual_key,public_url,image_type,confidence,width,height,source_url,source_type")
    .eq("visual_key", binding.visual_key).eq("image_type", "hero");
  if (assetError) throw assetError;
  return (assets || []) as CanonicalMediaRow[];
}

export async function getCanonicalBrands(limit = 150) {
  const db = publicDb();
  if (!db) return [];
  const { data, error } = await db.from("current_vehicle_brands").select("*")
    .order("name_en").limit(limit);
  if (error) throw error;
  const rows = data || [];

  // logo_url is a TDR presentation overlay, not canonical brand identity, so
  // it is read from the editorial table and linked through the projection's
  // stable tdr_brand_id -- never through a slug, which is allowed to change.
  //
  // This used to be a hardcoded null, which meant the four pages that render
  // `logo_url ? <img> : <initials>` could only ever take the second branch.
  //
  // The read is fail-open on purpose: a logo is decoration, and losing the
  // optional editorial table must not take the catalogue down with it. A
  // failure leaves every brand on the initials fallback it was already using.
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
  const [{ data, error }, mediaIndex] = await Promise.all([
    db.from("current_vehicle_models").select("*").order("name_en").limit(limit),
    getCanonicalPrimaryMediaIndex(),
  ]);
  if (error) throw error;
  return (data || []).map((raw: any) => {
    const row: any = modelRow(raw);
    const media = mediaIndex.has(row.id)
      ? mediaIndex.get(row.id)
      : row.generation_id ? mediaIndex.get(row.generation_id) : null;
    return {
      ...row,
      image_url: media?.public_url || null,
      hero_image_url: media?.public_url || null,
      image_type: media?.image_type || null,
    };
  });
}

export async function getCanonicalModelBundle(slug: string) {
  const db = publicDb();
  if (!db) return null;
  const { data: model, error: modelError } = await db.from("current_vehicle_models")
    .select("*").eq("slug", slug).maybeSingle();
  if (modelError) throw modelError;
  if (!model) return null;
  const [{ data: rawTrims, error: trimError }, media, modelHead] = await Promise.all([
    db.from("current_market_trims").select("*").eq("model_id", model.canonical_id).order("name"),
    getCanonicalVehicleMedia(model.generation_id || model.payload?.generation_id || ""),
    getCanonicalModelHeadOverride(model.canonical_id),
  ]);
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
  const hero = primaryExteriorMedia(modelHead === null ? media as CanonicalMediaRow[] : modelHead);
  return {
    ...row,
    image_url: hero?.public_url || null,
    hero_image_url: hero?.public_url || null,
    media,
    powertrains_detail: powertrains,
    trims: trims.map(({ _powertrain, ...trim }: any) => trim),
  };
}

/** Free compare reads the same active release as the catalogue. It deliberately
 * returns exact MarketTrim grain so price/spec values are never mixed between
 * variants. Tyre/wheel fields remain canonical data but are not projected onto
 * the public compare object in this product phase. */
/** Every row of a table, not the first page of it.
 *
 *  PostgREST caps a response at a thousand rows however large a limit is
 *  asked for, so a single `.limit(n)` silently returns a prefix once a table
 *  outgrows that. The catalogue has, and the effect was not a shorter list
 *  but a wrong one: the comparison loaded the first six hundred trims by
 *  name, and a car outside that slice came back as "no longer in the
 *  database" to a reader who had just chosen it from the catalogue.
 */
async function allRows(db: any, table: string, orderBy: string, pageSize = 1000) {
  const rows: any[] = [];
  for (let from = 0; ; from += pageSize) {
    const { data, error } = await db.from(table).select("*")
      .order(orderBy).range(from, from + pageSize - 1);
    if (error) throw error;
    rows.push(...(data || []));
    if (!data || data.length < pageSize) return rows;
  }
}

export async function getCanonicalCompareTrims(limit?: number) {
  const db = publicDb();
  if (!db) return [];
  const [rawTrims, modelRows] = await Promise.all([
    limit
      ? db.from("current_market_trims").select("*").order("name").limit(limit)
          .then(({ data, error }: any) => { if (error) throw error; return data || []; })
      : allRows(db, "current_market_trims", "name"),
    getCanonicalModels(1000),
  ]);
  const models = new Map((modelRows || []).map((row: any) => [row.canonical_id, row]));
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
        image_url: model?.image_url || null,
        segment: model?.segment || null,
        body_type: model?.body_type || null,
        production_type: model?.production_type || null,
        production_country: model?.production_country || null,
        model_seats: model?.seats || null,
        // Model-layer field, only meaningful for a pickup -- see
        // lib/free-compare.ts's "cab_type" case.
        cab_type: model?.cab_type || null,
        // Same field trimRow() already put on `trim` as `status`; carried
        // under its Compare-facing name here rather than a second concept.
        retail_status: trim.status || null,
        // Year/quarter precision, already computed onto the model payload by
        // the release bridge (current_generation.launched) -- reused as-is,
        // no new query.
        launch_year: model?.launch_year || null,
        launch_quarter: model?.launch_quarter || null,
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
