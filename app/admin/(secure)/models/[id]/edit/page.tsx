import { notFound } from "next/navigation";
import { adminDb } from "@/lib/supabase";
import { ModelForm } from "@/components/admin/ModelForm";
import { ProductionProgramForm } from "@/components/admin/ProductionProgramForm";
import { DeleteButton } from "@/components/admin/DeleteButton";

export default async function EditModel({params,searchParams}:{params:Promise<{id:string}>;searchParams:Promise<Record<string,string|undefined>>}){
  const {id}=await params;const sp=await searchParams;const db=adminDb();if(!db)notFound();
  const [{data:model},{data:brands},{data:plants},{data:programs},{data:powertrains},{data:trims}]=await Promise.all([
    db.from("models").select("*, brands(name_th)").eq("id",id).maybeSingle(),
    db.from("brands").select("id,name_th").order("name_th"),
    db.from("plants").select("id,name_th,province,maker_group").order("maker_group").order("name_th"),
    db.from("production_programs").select("*").eq("model_id",id).order("created_at"),
    db.from("model_powertrains").select("*").eq("model_id",id).order("created_at"),
    db.from("trims").select("*, trim_powertrains(powertrain_id)").eq("model_id",id).order("sort_order").order("created_at")
  ]);if(!model)notFound();
  const enriched=[] as any[];for(const p of programs??[]){const [{data:lc},{data:mit}]=await Promise.all([db.from("local_content_declarations").select("*").eq("production_program_id",p.id).order("created_at",{ascending:false}).limit(1).maybeSingle(),db.from("mit_approvals").select("*").eq("production_program_id",p.id).order("created_at",{ascending:false}).limit(1).maybeSingle()]);enriched.push({program:p,localContent:lc,mit});}
  return <div className="adminEditor">
    <div className="adminHeader adminHeaderActions"><div><small>MODEL MASTER · V1.1</small><h1>{model.brands?.name_th?`${model.brands.name_th} `:""}{model.name_th}</h1><p>Master record เดียว → Consumer catalog + Trim + Sales + Thailand Production</p></div><DeleteButton kind="model" id={id} label="ลบ Model"/></div>
    {sp.saved?<div className="adminSaved">บันทึก Model / Powertrain / Trim แล้ว</div>:null}
    <ModelForm brands={brands??[]} model={model} brandName={model.brands?.name_th} powertrains={powertrains??[]} trims={trims??[]}/>
    <section className="adminDeepLayer"><div className="adminDeepLayerHead"><small>THAILAND PRODUCTION · OPTIONAL</small><h2>ข้อมูลรถในฐานะอุตสาหกรรม</h2><p>ถ้ารถเป็น CBU และไม่มี story การผลิตไทย ปล่อยส่วนนี้ว่างได้เลย ถ้ามี record ระบบจะสร้างลิงก์ “ข้อมูลการผลิตในประเทศไทย” บนหน้ารถอัตโนมัติ</p></div>
      <div className="adminSubSection"><h3>Production Programs</h3>{enriched.map(({program,localContent,mit})=><ProductionProgramForm key={program.id} modelId={id} plants={plants??[]} program={program} localContent={localContent} mit={mit}/>)}<ProductionProgramForm modelId={id} plants={plants??[]}/></div>
    </section>
  </div>;
}
