import { getCanonicalModels } from "@/lib/canonical-data";
import { publicDb } from "@/lib/supabase";

/**
 * Compare has two very different read shapes:
 *
 * 1. the picker needs every trim, but only six tiny fields;
 * 2. an actual comparison needs the full payload, but for at most four trims.
 *
 * Do not collapse those back into `select("*")` across current_market_trims.
 * The projection contains large JSON payload/history columns and Postgres can
 * spill a full-table ORDER BY to temporary disk.  The picker must stay narrow;
 * the rich read must stay targeted.
 */

const PICKER_COLUMNS = "canonical_id,model_id,name,powertrain,status,current_list_price";
const COMPARE_COLUMNS = "canonical_id,model_id,generation_id,variant_id,name,powertrain,status,payload,current_list_price,campaign_quote";

async function allSlimTrimRows(db: any, pageSize = 1000) {
  const rows: any[] = [];
  for (let from = 0; ; from += pageSize) {
    const { data, error } = await db.from("current_market_trims")
      .select(PICKER_COLUMNS)
      .order("canonical_id")
      .range(from, from + pageSize - 1);
    if (error) throw error;
    rows.push(...(data || []));
    if (!data || data.length < pageSize) return rows;
  }
}

function isCurrentTrim(row: any) {
  return String(row?.status || "current").toLowerCase() !== "discontinued";
}

export async function getCanonicalCompareTrimOptions() {
  const db = publicDb();
  if (!db) return [];

  // Models are only ~321 rows and are already the catalogue read path.  The
  // expensive table is the 1,500+ trim projection with its large JSON columns.
  const [rawTrims, modelRows] = await Promise.all([
    allSlimTrimRows(db),
    getCanonicalModels(1000),
  ]);
  const models = new Map((modelRows || []).map((row: any) => [row.canonical_id, row]));

  return rawTrims
    .filter(isCurrentTrim)
    .map((raw: any) => {
      const model: any = models.get(raw.model_id) || null;
      const list = raw.current_list_price || null;
      return {
        id: raw.canonical_id,
        model_id: raw.model_id,
        brand_name: model?.brands?.name_en || model?.brands?.name_th || "",
        model_name: model?.name_en || model?.name_th || raw.model_id,
        name: raw.name,
        powertrain: raw.powertrain ?? null,
        price_baht: list?.amount_thb ?? null,
      };
    })
    .sort((a: any, b: any) =>
      `${a.brand_name} ${a.model_name} ${a.name}`.localeCompare(
        `${b.brand_name} ${b.model_name} ${b.name}`,
        "th",
      ));
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
