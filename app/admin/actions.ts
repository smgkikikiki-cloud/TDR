"use server";

import { adminDb } from "@/lib/supabase";
import { authenticate, clearAdminCookie, hasSessionSecret, isAdmin, setAdminCookie } from "@/lib/admin-auth";
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

export async function loginAction(formData: FormData) {
  const editor = authenticate(val(formData, "name"), val(formData, "password"));
  if (!editor) redirect("/admin/login?error=1");
  // A missing session secret is a deployment fault, not a wrong password.
  if (!hasSessionSecret()) redirect("/admin/login?error=config");
  await setAdminCookie(editor);
  redirect("/admin");
}
export async function logoutAction() { await clearAdminCookie(); redirect("/admin/login"); }

function slugify(value: string) {
  return value.normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "record";
}
async function uniqueSlug(db:any, table:string, base:string, currentId?:string|null) {
  let candidate = slugify(base);
  const { data } = await db.from(table).select("id").eq("slug", candidate).maybeSingle();
  if (data && data.id !== currentId) candidate = `${candidate}-${Date.now().toString(36).slice(-5)}`;
  return candidate;
}

async function resolveBrand(db:any, brandName:string|null) {
  if (!brandName) return null;
  const clean = brandName.trim();
  const { data: existing } = await db.from("brands").select("id,name_th").ilike("name_th", clean).limit(1).maybeSingle();
  if (existing) return existing.id;
  const slug = await uniqueSlug(db, "brands", clean);
  const { data, error } = await db.from("brands").insert({ slug, name_th: clean, status: "active" }).select("id").single();
  if (error) throw error;
  return data.id;
}

export async function saveBrand(formData: FormData) {
  await requireAdmin(); const db = dbOrThrow();
  const id = val(formData, "id"); const name = val(formData, "name_th");
  if (!name) throw new Error("กรุณาใส่ชื่อแบรนด์");
  const slug = await uniqueSlug(db, "brands", name, id);
  const payload = { slug, name_th:name, name_en:val(formData,"name_en"), country_origin:val(formData,"country_origin"), status:val(formData,"status")||"active", logo_url:val(formData,"logo_url"), notes:val(formData,"notes") };
  const r = id ? await db.from("brands").update(payload).eq("id",id) : await db.from("brands").insert(payload);
  if (r.error) throw r.error; redirect("/admin/library?table=brands&saved=1");
}

export async function savePlant(formData: FormData) {
  await requireAdmin(); const db=dbOrThrow(); const id=val(formData,"id"); const name=val(formData,"name_th");
  if(!name) throw new Error("กรุณาใส่ชื่อโรงงาน");
  const slug=await uniqueSlug(db,"plants",name,id);
  const payload={slug,name_th:name,name_en:val(formData,"name_en"),maker_group:val(formData,"maker_group"),province:val(formData,"province"),district:val(formData,"district"),address_text:val(formData,"address_text"),capacity_annual:num(formData,"capacity_annual"),estimated_production_annual:num(formData,"estimated_production_annual"),utilization_estimate_year:num(formData,"utilization_estimate_year"),opened_year:num(formData,"opened_year"),status:val(formData,"status")||"active",capacity_note:val(formData,"capacity_note"),notes:val(formData,"notes")};
  const r=id?await db.from("plants").update(payload).eq("id",id):await db.from("plants").insert(payload); if(r.error)throw r.error; redirect("/admin/library?table=plants&saved=1");
}

export async function saveCompany(formData: FormData) {
  await requireAdmin(); const db=dbOrThrow(); const id=val(formData,"id"); const name=val(formData,"name_th"); if(!name)throw new Error("กรุณาใส่ชื่อบริษัท");
  const slug=await uniqueSlug(db,"companies",name,id);
  const payload={slug,name_th:name,name_en:val(formData,"name_en"),company_type:val(formData,"company_type")||"supplier",parent_company:val(formData,"parent_company"),province:val(formData,"province"),products_services:val(formData,"products_services"),notes:val(formData,"notes")};
  const r=id?await db.from("companies").update(payload).eq("id",id):await db.from("companies").insert(payload);if(r.error)throw r.error;redirect("/admin/library?table=companies&saved=1");
}

type PowertrainInput = {
  id?: string; clientKey: string; label?: string|null; powertrainType?: string|null; engineCode?: string|null;
  displacementCc?: number|null; batteryCapacityKwh?: number|null; batteryChemistry?: string|null; motorOutputKw?: number|null;
  horsepowerPs?: number|null; torqueNm?: number|null; transmission?: string|null; drivetrain?: string|null; notes?: string|null;
  unconfirmedFields?: string[];
};
type TrimInput = {
  id?: string; clientKey: string; name: string; priceBaht?: number|null; status?: string|null; description?: string|null;
  seatsOverride?: number|null; payloadCapacityKgOverride?: number|null; powertrainKeys?: string[]; sortOrder?: number; unconfirmedFields?: string[];
};

export async function saveModel(formData: FormData) {
  await requireAdmin(); const db=dbOrThrow();
  const id=val(formData,"id"); const modelName=val(formData,"name_th"); if(!modelName)throw new Error("กรุณาใส่ชื่อรุ่น");
  const brandId=await resolveBrand(db,val(formData,"brand_name"));
  let brandSlug=""; if(brandId){const {data:b}=await db.from("brands").select("slug").eq("id",brandId).maybeSingle();brandSlug=b?.slug||"";}
  let slug:string;
  if(id){const {data:old}=await db.from("models").select("slug").eq("id",id).maybeSingle();slug=old?.slug||await uniqueSlug(db,"models",`${brandSlug}-${modelName}`);}
  else slug=await uniqueSlug(db,"models",[brandSlug,modelName,val(formData,"generation")].filter(Boolean).join("-"));

  const unconfirmedFields=formData.getAll("unconfirmed_fields").filter((x):x is string=>typeof x==="string");
  const payload={
    slug,brand_id:brandId,name_th:modelName,generation:val(formData,"generation"),segment:val(formData,"segment"),body_type:val(formData,"body_type"),market_position:val(formData,"market_position"),
    production_type:val(formData,"production_type"),production_country:val(formData,"production_country"),launch_quarter:val(formData,"launch_quarter"),launch_month:null,launch_year:num(formData,"launch_year"),
    status:val(formData,"status")||"current",upcoming_status:null,seats:num(formData,"seats"),payload_capacity_kg:num(formData,"payload_capacity_kg"),image_url:val(formData,"image_url"),consumer_description:val(formData,"consumer_description"),featured:formData.get("featured")==="on",unconfirmed_fields:unconfirmedFields,notes:val(formData,"notes")
  };
  let modelId=id;
  if(id){const r=await db.from("models").update(payload).eq("id",id);if(r.error)throw r.error;}
  else {const r=await db.from("models").insert(payload).select("id").single();if(r.error)throw r.error;modelId=r.data.id;}
  if(!modelId)throw new Error("Missing model id");

  const powertrains=json<PowertrainInput[]>(formData,"powertrains_json",[]);
  const trims=json<TrimInput[]>(formData,"trims_json",[]);
  const {data:existingPts}=await db.from("model_powertrains").select("id").eq("model_id",modelId);
  const keepPtIds:string[]=[]; const ptMap=new Map<string,string>();
  for(const p of powertrains){
    const ptPayload={model_id:modelId,label:p.label||null,powertrain_type:p.powertrainType||null,engine_code:p.engineCode||null,displacement_cc:p.displacementCc??null,battery_capacity_kwh:p.batteryCapacityKwh??null,battery_chemistry:p.batteryChemistry||null,motor_output_kw:p.motorOutputKw??null,horsepower_ps:p.horsepowerPs??null,torque_nm:p.torqueNm??null,system_output_ps:p.horsepowerPs??null,transmission:p.transmission||null,drivetrain:p.drivetrain||null,notes:p.notes||null,unconfirmed_fields:p.unconfirmedFields||[]};
    let actualId=p.id;
    if(actualId){const r=await db.from("model_powertrains").update(ptPayload).eq("id",actualId).eq("model_id",modelId);if(r.error)throw r.error;}
    else {const r=await db.from("model_powertrains").insert(ptPayload).select("id").single();if(r.error)throw r.error;actualId=r.data.id;}
    keepPtIds.push(actualId!);ptMap.set(p.clientKey,actualId!);if(p.id)ptMap.set(p.id,actualId!);
  }
  for(const old of existingPts??[]){if(!keepPtIds.includes(old.id)){const r=await db.from("model_powertrains").delete().eq("id",old.id);if(r.error)throw r.error;}}

  const {data:existingTrims}=await db.from("trims").select("id").eq("model_id",modelId);
  const keepTrimIds:string[]=[]; const currentPrices:number[]=[];
  for(let i=0;i<trims.length;i++){
    const t=trims[i]; if(!t.name?.trim())continue;
    const trimPayload={model_id:modelId,name:t.name.trim(),price_baht:t.priceBaht??null,status:t.status||"current",description:t.description||null,seats_override:t.seatsOverride??null,payload_capacity_kg_override:t.payloadCapacityKgOverride??null,sort_order:t.sortOrder??i,unconfirmed_fields:t.unconfirmedFields||[]};
    let trimId=t.id;
    if(trimId){const r=await db.from("trims").update(trimPayload).eq("id",trimId).eq("model_id",modelId);if(r.error)throw r.error;}
    else {const r=await db.from("trims").insert(trimPayload).select("id").single();if(r.error)throw r.error;trimId=r.data.id;}
    keepTrimIds.push(trimId!); if(trimPayload.status==="current"&&trimPayload.price_baht)currentPrices.push(trimPayload.price_baht);
    const del=await db.from("trim_powertrains").delete().eq("trim_id",trimId);if(del.error)throw del.error;
    const ids=(t.powertrainKeys||[]).map(k=>ptMap.get(k)||k).filter((x):x is string=>!!x&&keepPtIds.includes(x));
    if(ids.length){const r=await db.from("trim_powertrains").insert(ids.map(powertrain_id=>({trim_id:trimId,powertrain_id})));if(r.error)throw r.error;}
  }
  for(const old of existingTrims??[]){if(!keepTrimIds.includes(old.id)){const r=await db.from("trims").delete().eq("id",old.id);if(r.error)throw r.error;}}

  const ptTypes=[...new Set(powertrains.map(p=>p.powertrainType).filter((x):x is string=>!!x))];
  const retailMin=currentPrices.length?Math.min(...currentPrices):null; const retailMax=currentPrices.length?Math.max(...currentPrices):null;
  const r2=await db.from("models").update({powertrains:ptTypes,retail_price_min:retailMin,retail_price_max:retailMax}).eq("id",modelId);if(r2.error)throw r2.error;
  redirect(`/admin/models/${modelId}/edit?saved=1`);
}

export async function saveEvent(formData: FormData) {
  await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");const payload={title_th:val(formData,"title_th"),title_en:val(formData,"title_en"),event_date:val(formData,"event_date"),event_type:val(formData,"event_type")||"news",summary_th:val(formData,"summary_th"),source_name:val(formData,"source_name"),source_url:val(formData,"source_url"),related_brand_id:val(formData,"related_brand_id"),related_model_id:val(formData,"related_model_id"),related_plant_id:val(formData,"related_plant_id"),related_company_id:val(formData,"related_company_id"),published:formData.get("published")==="on"};const r=id?await db.from("events").update(payload).eq("id",id):await db.from("events").insert(payload);if(r.error)throw r.error;redirect("/admin/library?table=events&saved=1");
}

export async function saveProductionProgram(formData: FormData) {
  await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");const modelId=val(formData,"model_id");if(!modelId)throw new Error("Missing model_id");
  const payload={model_id:modelId,plant_id:val(formData,"plant_id"),production_type:val(formData,"production_type"),status:val(formData,"status"),platform:val(formData,"platform"),story_th:val(formData,"story_th"),annual_production_estimate:num(formData,"annual_production_estimate"),production_volume_year:num(formData,"production_volume_year"),export_volume_estimate:num(formData,"export_volume_estimate"),export_volume_year:num(formData,"export_volume_year"),export_markets:val(formData,"export_markets"),source_name:val(formData,"source_name"),source_url:val(formData,"source_url"),unconfirmed_fields:formData.getAll("program_unconfirmed_fields").filter((v):v is string=>typeof v==="string")};
  let programId=id;if(id){const r=await db.from("production_programs").update(payload).eq("id",id);if(r.error)throw r.error;}else{const r=await db.from("production_programs").insert(payload).select("id").single();if(r.error)throw r.error;programId=r.data.id;}
  if(programId){const lcPayload={production_program_id:programId,percentage:num(formData,"local_content_percentage"),announced_by:val(formData,"local_content_announced_by"),announcement_year:num(formData,"local_content_year"),source_url:val(formData,"local_content_source_url"),unconfirmed:formData.get("local_content_unconfirmed")==="on"};const {data:lc}=await db.from("local_content_declarations").select("id").eq("production_program_id",programId).order("created_at",{ascending:false}).limit(1).maybeSingle();if(lcPayload.percentage!==null||lcPayload.announced_by||lcPayload.announcement_year||lcPayload.source_url){const rr=lc?await db.from("local_content_declarations").update(lcPayload).eq("id",lc.id):await db.from("local_content_declarations").insert(lcPayload);if(rr.error)throw rr.error;}
    const mitPayload={production_program_id:programId,approved:formData.get("mit_approved")==="on",valid_from_year:num(formData,"mit_valid_from_year"),valid_to_year:num(formData,"mit_valid_to_year"),source_url:val(formData,"mit_source_url"),unconfirmed:formData.get("mit_unconfirmed")==="on"};const {data:mit}=await db.from("mit_approvals").select("id").eq("production_program_id",programId).order("created_at",{ascending:false}).limit(1).maybeSingle();if(mitPayload.approved||mitPayload.valid_from_year||mitPayload.valid_to_year||mitPayload.source_url){const rr=mit?await db.from("mit_approvals").update(mitPayload).eq("id",mit.id):await db.from("mit_approvals").insert(mitPayload);if(rr.error)throw rr.error;}}
  redirect(`/admin/models/${modelId}/edit?production_saved=1`);
}

// Legacy standalone powertrain action retained for compatibility with older pages.
export async function savePowertrainDetail(formData: FormData) {
  await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");const modelId=val(formData,"model_id");if(!modelId)throw new Error("Missing model_id");const payload={model_id:modelId,label:val(formData,"label"),powertrain_type:val(formData,"powertrain_type"),engine_code:val(formData,"engine_code"),displacement_cc:num(formData,"displacement_cc"),battery_capacity_kwh:num(formData,"battery_capacity_kwh"),battery_chemistry:val(formData,"battery_chemistry"),motor_output_kw:num(formData,"motor_output_kw"),horsepower_ps:num(formData,"horsepower_ps"),torque_nm:num(formData,"torque_nm"),notes:val(formData,"notes")};const r=id?await db.from("model_powertrains").update(payload).eq("id",id):await db.from("model_powertrains").insert(payload);if(r.error)throw r.error;redirect(`/admin/models/${modelId}/edit?powertrain_saved=1`);
}

export async function deleteModel(formData:FormData){await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");if(id){const r=await db.from("models").delete().eq("id",id);if(r.error)throw r.error;}redirect("/admin/library?table=models&deleted=1");}
export async function deleteBrand(formData:FormData){await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");if(id){const {count}=await db.from("models").select("*",{count:"exact",head:true}).eq("brand_id",id);if((count||0)>0)redirect(`/admin/brands/${id}/edit?inuse=1`);const r=await db.from("brands").delete().eq("id",id);if(r.error)throw r.error;}redirect("/admin/library?table=brands&deleted=1");}
export async function deletePlant(formData:FormData){await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");if(id){const r=await db.from("plants").delete().eq("id",id);if(r.error)throw r.error;}redirect("/admin/library?table=plants&deleted=1");}
export async function deleteCompany(formData:FormData){await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");if(id){const r=await db.from("companies").delete().eq("id",id);if(r.error)throw r.error;}redirect("/admin/library?table=companies&deleted=1");}
export async function deleteEvent(formData:FormData){await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");if(id){const r=await db.from("events").delete().eq("id",id);if(r.error)throw r.error;}redirect("/admin/library?table=events&deleted=1");}
export async function deleteProductionProgram(formData:FormData){await requireAdmin();const db=dbOrThrow();const id=val(formData,"id");const modelId=val(formData,"model_id");if(id){const r=await db.from("production_programs").delete().eq("id",id);if(r.error)throw r.error;}redirect(modelId?`/admin/models/${modelId}/edit?production_deleted=1`:"/admin/library?table=production_programs&deleted=1");}
