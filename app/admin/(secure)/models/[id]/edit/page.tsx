import { notFound } from "next/navigation";
import { adminDb } from "@/lib/supabase";
import { ModelFormV12 } from "@/components/admin/ModelFormV12";
import { ProductionProgramForm } from "@/components/admin/ProductionProgramForm";
import { DeleteButton } from "@/components/admin/DeleteButton";

export default async function EditModel({params,searchParams}:{params:Promise<{id:string}>;searchParams:Promise<Record<string,string|undefined>>}){
  const {id}=await params;
  const sp=await searchParams;
  const db=adminDb();
  if(!db)notFound();

  const [{data:model},{data:brands},{data:plants},{data:programs},{data:powertrains},{data:trims}]=await Promise.all([
    db.from("models").select("*, brands(name_th)").eq("id",id).maybeSingle(),
    db.from("brands").select("id,name_th").order("name_th"),
    db.from("plants").select("id,name_th,province,maker_group").order("maker_group").order("name_th"),
    db.from("production_programs").select("*").eq("model_id",id).order("created_at"),
    db.from("model_powertrains").select("*").eq("model_id",id).order("created_at"),
    db.from("trims").select("*").eq("model_id",id).order("sort_order").order("created_at")
  ]);
  if(!model)notFound();

  const trimIds=(trims??[]).map((t:any)=>t.id);
  let links:any[]=[];
  if(trimIds.length){
    const {data,error}=await db.from("trim_powertrains").select("trim_id,powertrain_id").in("trim_id",trimIds);
    if(error) throw error;
    links=data??[];
  }
  const linkedTrims=(trims??[]).map((t:any)=>({...t,trim_powertrains:links.filter((x:any)=>x.trim_id===t.id)}));

  const enriched=[] as any[];
  for(const p of programs??[]){
    const [{data:lc},{data:mit}]=await Promise.all([
      db.from("local_content_declarations").select("*").eq("production_program_id",p.id).order("created_at",{ascending:false}).limit(1).maybeSingle(),
      db.from("mit_approvals").select("*").eq("production_program_id",p.id).order("created_at",{ascending:false}).limit(1).maybeSingle()
    ]);
    enriched.push({program:p,localContent:lc,mit});
  }

  return <div className="adminEditor">
    <div className="adminHeader adminHeaderActions">
      <div><small>MODEL MASTER · V1.2</small><h1>{model.brands?.name_th?`${model.brands.name_th} `:""}{model.name_th}</h1><p>Consumer Catalog + Trim + Range + Thailand Production จาก master record เดียว</p></div>
      <DeleteButton kind="model" id={id} label="ลบ Model"/>
    </div>
    {sp.saved?<div className="adminSaved">บันทึก Model / Powertrain / Trim แล้ว</div>:null}
    <ModelFormV12 brands={brands??[]} model={model} brandName={model.brands?.name_th} powertrains={powertrains??[]} trims={linkedTrims}/>
    <section className="adminDeepLayer">
      <div className="adminDeepLayerHead"><small>THAILAND PRODUCTION · OPTIONAL</small><h2>ข้อมูลรถในฐานะอุตสาหกรรม</h2><p>ถ้าไม่มีการผลิตไทย ปล่อยส่วนนี้ว่างได้เลย ถ้ามี record ระบบจะสร้างลิงก์จากหน้า Consumer อัตโนมัติ</p></div>
      <div className="adminSubSection"><h3>Production Programs</h3>{enriched.map(({program,localContent,mit})=><ProductionProgramForm key={program.id} modelId={id} plants={plants??[]} program={program} localContent={localContent} mit={mit}/>)}<ProductionProgramForm modelId={id} plants={plants??[]}/></div>
    </section>
  </div>;
}
