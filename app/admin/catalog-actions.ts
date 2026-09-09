"use server";

import { adminDb } from "@/lib/supabase";
import { isAdmin } from "@/lib/admin-auth";
import { enqueueCanonicalModelShadow } from "@/lib/canonical-write-shadow";
import { redirect } from "next/navigation";

const val = (form: FormData, key: string) => {
  const v = form.get(key);
  return typeof v === "string" && v.trim() ? v.trim() : null;
};
const num = (form: FormData, key: string) => {
  const v = val(form, key);
  if (!v) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const json = <T,>(form: FormData, key: string, fallback: T): T => {
  const raw = val(form, key);
  if (!raw) return fallback;
  try { return JSON.parse(raw) as T; } catch { return fallback; }
};

async function requireAdmin() {
  if (!(await isAdmin())) redirect("/admin/login");
}
function dbOrThrow() {
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase ใน .env.local");
  return db;
}
function slugify(value:string) {
  return value.normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,80) || "record";
}
async function uniqueSlug(db:any, table:string, base:string, currentId?:string|null) {
  let candidate=slugify(base);
  const {data}=await db.from(table).select("id").eq("slug",candidate).maybeSingle();
  if(data && data.id!==currentId) candidate=`${candidate}-${Date.now().toString(36).slice(-5)}`;
  return candidate;
}
async function resolveBrand(db:any, brandName:string|null) {
  if(!brandName) return null;
  const clean=brandName.trim();
  const {data:existing}=await db.from("brands").select("id,name_th").ilike("name_th",clean).limit(1).maybeSingle();
  if(existing) return existing.id;
  const slug=await uniqueSlug(db,"brands",clean);
  const {data,error}=await db.from("brands").insert({slug,name_th:clean,status:"active"}).select("id").single();
  if(error) throw error;
  return data.id;
}

type PowertrainInput = {
  id?:string; clientKey:string; label?:string|null; powertrainType?:string|null; engineCode?:string|null;
  displacementCc?:number|null; batteryCapacityKwh?:number|null; batteryChemistry?:string|null; motorOutputKw?:number|null;
  horsepowerPs?:number|null; torqueNm?:number|null; transmission?:string|null; drivetrain?:string|null; notes?:string|null;
  unconfirmedFields?:string[];
};
type TrimInput = {
  id?:string; clientKey:string; name:string; priceBaht?:number|null; status?:string|null; description?:string|null;
  seatsOverride?:number|null; payloadCapacityKgOverride?:number|null; powertrainKeys?:string[];
  tireSizeFront?:string|null; tireSizeRear?:string|null; wheelSizeFront?:string|null; wheelSizeRear?:string|null;
  publishedRangeKm?:number|null; publishedRangeCycle?:string|null; standardizedWltpKm?:number|null; standardizedEpaKm?:number|null;
  rangeSourceUrl?:string|null; sortOrder?:number; unconfirmedFields?:string[];
};

export async function saveModelV12(formData:FormData) {
  await requireAdmin();
  const db=dbOrThrow();
  const id=val(formData,"id");
  const modelName=val(formData,"name_th");
  if(!modelName) throw new Error("กรุณาใส่ชื่อรุ่น");

  const brandId=await resolveBrand(db,val(formData,"brand_name"));
  let brandSlug="";
  if(brandId){
    const {data:b}=await db.from("brands").select("slug").eq("id",brandId).maybeSingle();
    brandSlug=b?.slug||"";
  }

  let slug:string;
  if(id){
    const {data:old}=await db.from("models").select("slug").eq("id",id).maybeSingle();
    slug=old?.slug||await uniqueSlug(db,"models",`${brandSlug}-${modelName}`,id);
  }else{
    slug=await uniqueSlug(db,"models",[brandSlug,modelName,val(formData,"generation")].filter(Boolean).join("-"));
  }

  const unconfirmedFields=formData.getAll("unconfirmed_fields").filter((x):x is string=>typeof x==="string");
  const modelPayload={
    slug,
    brand_id:brandId,
    name_th:modelName,
    generation:val(formData,"generation"),
    segment:val(formData,"segment"),
    body_type:val(formData,"body_type"),
    market_position:val(formData,"market_position"),
    production_type:val(formData,"production_type"),
    production_country:val(formData,"production_country"),
    launch_quarter:val(formData,"launch_quarter"),
    launch_month:null,
    launch_year:num(formData,"launch_year"),
    seats:num(formData,"seats"),
    payload_capacity_kg:num(formData,"payload_capacity_kg"),
    length_mm:num(formData,"length_mm"),
    width_mm:num(formData,"width_mm"),
    wheelbase_mm:num(formData,"wheelbase_mm"),
    status:val(formData,"status")||"current",
    upcoming_status:null,
    image_url:val(formData,"image_url"),
    consumer_description:val(formData,"consumer_description"),
    featured:formData.get("featured")==="on",
    unconfirmed_fields:unconfirmedFields,
    notes:val(formData,"notes")
  };

  let modelId=id;
  if(id){
    const r=await db.from("models").update(modelPayload).eq("id",id);
    if(r.error) throw r.error;
  }else{
    const r=await db.from("models").insert(modelPayload).select("id").single();
    if(r.error) throw r.error;
    modelId=r.data.id;
  }
  if(!modelId) throw new Error("Missing model id");

  const powertrains=json<PowertrainInput[]>(formData,"powertrains_json",[]);
  const trims=json<TrimInput[]>(formData,"trims_json",[]);

  const {data:existingPts,error:existingPtsError}=await db.from("model_powertrains").select("id").eq("model_id",modelId);
  if(existingPtsError) throw existingPtsError;

  const keepPtIds:string[]=[];
  const ptMap=new Map<string,string>();
  for(const p of powertrains){
    const ptPayload={
      model_id:modelId,
      label:p.label||null,
      powertrain_type:p.powertrainType||null,
      engine_code:p.engineCode||null,
      displacement_cc:p.displacementCc??null,
      battery_capacity_kwh:p.batteryCapacityKwh??null,
      battery_chemistry:p.batteryChemistry||null,
      motor_output_kw:p.motorOutputKw??null,
      horsepower_ps:p.horsepowerPs??null,
      torque_nm:p.torqueNm??null,
      system_output_ps:p.horsepowerPs??null,
      transmission:p.transmission||null,
      drivetrain:p.drivetrain||null,
      notes:p.notes||null,
      unconfirmed_fields:p.unconfirmedFields||[]
    };
    let actualId=p.id;
    if(actualId){
      const r=await db.from("model_powertrains").update(ptPayload).eq("id",actualId).eq("model_id",modelId);
      if(r.error) throw r.error;
    }else{
      const r=await db.from("model_powertrains").insert(ptPayload).select("id").single();
      if(r.error) throw r.error;
      actualId=r.data.id;
    }
    keepPtIds.push(actualId!);
    ptMap.set(p.clientKey,actualId!);
    if(p.id) ptMap.set(p.id,actualId!);
  }
  for(const old of existingPts??[]){
    if(!keepPtIds.includes(old.id)){
      const r=await db.from("model_powertrains").delete().eq("id",old.id);
      if(r.error) throw r.error;
    }
  }

  const {data:existingTrims,error:existingTrimsError}=await db.from("trims").select("id").eq("model_id",modelId);
  if(existingTrimsError) throw existingTrimsError;

  const keepTrimIds:string[]=[];
  for(let i=0;i<trims.length;i++){
    const t=trims[i];
    if(!t.name?.trim()) continue;

    // price_baht is deliberately absent. It is a serving cache projected from
    // canonical PriceLedger; the legacy model editor is no longer a second
    // price writer. priceBaht remains in TrimInput temporarily so the old form
    // can post without breaking while the Price Workbench replaces that UI.
    const trimPayload={
      model_id:modelId,
      name:t.name.trim(),
      status:t.status||"current",
      description:t.description||null,
      seats_override:t.seatsOverride??null,
      payload_capacity_kg_override:t.payloadCapacityKgOverride??null,
      tire_size_front:t.tireSizeFront||null,
      tire_size_rear:t.tireSizeRear||null,
      wheel_size_front:t.wheelSizeFront||null,
      wheel_size_rear:t.wheelSizeRear||null,
      published_range_km:t.publishedRangeKm??null,
      published_range_cycle:t.publishedRangeCycle||null,
      standardized_wltp_km:t.standardizedWltpKm??null,
      standardized_epa_km:t.standardizedEpaKm??null,
      range_source_url:t.rangeSourceUrl||null,
      sort_order:t.sortOrder??i,
      unconfirmed_fields:t.unconfirmedFields||[]
    };

    let trimId=t.id;
    if(trimId){
      const r=await db.from("trims").update(trimPayload).eq("id",trimId).eq("model_id",modelId);
      if(r.error) throw r.error;
    }else{
      const r=await db.from("trims").insert(trimPayload).select("id").single();
      if(r.error) throw r.error;
      trimId=r.data.id;
    }
    keepTrimIds.push(trimId!);

    const del=await db.from("trim_powertrains").delete().eq("trim_id",trimId);
    if(del.error) throw del.error;
    const ids=(t.powertrainKeys||[]).map(k=>ptMap.get(k)||k).filter((x):x is string=>!!x&&keepPtIds.includes(x));
    if(ids.length){
      const r=await db.from("trim_powertrains").insert(ids.map(powertrain_id=>({trim_id:trimId,powertrain_id})));
      if(r.error) throw r.error;
    }
  }

  for(const old of existingTrims??[]){
    if(!keepTrimIds.includes(old.id)){
      const r=await db.from("trims").delete().eq("id",old.id);
      if(r.error) throw r.error;
    }
  }

  const ptTypes=[...new Set(powertrains.map(p=>p.powertrainType).filter((x):x is string=>!!x))];
  // retail_price_min/max are serving projections from PriceLedger too. Preserve
  // their current values here instead of recomputing them from ignored legacy
  // form prices; Phase-E publication owns those fields.
  const r2=await db.from("models").update({powertrains:ptTypes}).eq("id",modelId);
  if(r2.error) throw r2.error;

  // Phase C shadow write.  This intentionally does not make legacy trim prices
  // canonical: priceBaht is omitted here because PriceLedger owns money.
  // Editorial-only fields (image/featured/consumer_description) also remain
  // TDR-owned and are not included in the canonical command payload.
  try {
    await enqueueCanonicalModelShadow({
      sourceModelId:modelId,
      payload:{
        model:{
          slug:modelPayload.slug,
          brand_id:modelPayload.brand_id,
          name_th:modelPayload.name_th,
          generation:modelPayload.generation,
          segment:modelPayload.segment,
          body_type:modelPayload.body_type,
          production_type:modelPayload.production_type,
          production_country:modelPayload.production_country,
          launch_quarter:modelPayload.launch_quarter,
          launch_year:modelPayload.launch_year,
          seats:modelPayload.seats,
          payload_capacity_kg:modelPayload.payload_capacity_kg,
          length_mm:modelPayload.length_mm,
          width_mm:modelPayload.width_mm,
          wheelbase_mm:modelPayload.wheelbase_mm,
          status:modelPayload.status,
          unconfirmed_fields:modelPayload.unconfirmed_fields,
          notes:modelPayload.notes
        },
        powertrains:powertrains.map(p=>({
          id:p.id||null,
          clientKey:p.clientKey,
          label:p.label||null,
          powertrainType:p.powertrainType||null,
          engineCode:p.engineCode||null,
          displacementCc:p.displacementCc??null,
          batteryCapacityKwh:p.batteryCapacityKwh??null,
          batteryChemistry:p.batteryChemistry||null,
          motorOutputKw:p.motorOutputKw??null,
          horsepowerPs:p.horsepowerPs??null,
          torqueNm:p.torqueNm??null,
          transmission:p.transmission||null,
          drivetrain:p.drivetrain||null,
          notes:p.notes||null,
          unconfirmedFields:p.unconfirmedFields||[]
        })),
        trims:trims.map(t=>({
          id:t.id||null,
          clientKey:t.clientKey,
          name:t.name,
          status:t.status||"current",
          description:t.description||null,
          seatsOverride:t.seatsOverride??null,
          payloadCapacityKgOverride:t.payloadCapacityKgOverride??null,
          powertrainKeys:t.powertrainKeys||[],
          tireSizeFront:t.tireSizeFront||null,
          tireSizeRear:t.tireSizeRear||null,
          wheelSizeFront:t.wheelSizeFront||null,
          wheelSizeRear:t.wheelSizeRear||null,
          publishedRangeKm:t.publishedRangeKm??null,
          publishedRangeCycle:t.publishedRangeCycle||null,
          standardizedWltpKm:t.standardizedWltpKm??null,
          standardizedEpaKm:t.standardizedEpaKm??null,
          rangeSourceUrl:t.rangeSourceUrl||null,
          sortOrder:t.sortOrder??null,
          unconfirmedFields:t.unconfirmedFields||[]
        }))
      },
      reason:"legacy TDR model editor shadow write during Phase C"
    });
  } catch(error) {
    // Shadow mode is observability, not the active write path yet.  Do not make
    // a migration/queue outage destroy the old editor before cutover.
    console.error("canonical shadow enqueue failed",error);
  }

  redirect(`/admin/models/${modelId}/edit?saved=1`);
}
