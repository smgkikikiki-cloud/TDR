import { publicDb } from "@/lib/supabase";

export async function getConsumerModelBundle(slug:string){
  const db=publicDb();
  if(!db) return null;

  const {data:model,error:modelError}=await db
    .from("models")
    .select("*, brands(name_th,slug,logo_url), model_plants(plant_id,plants(name_th,slug,province,maker_group))")
    .eq("slug",slug)
    .maybeSingle();

  if(modelError) throw modelError;
  if(!model) return null;

  const [{data:powertrains,error:ptError},{data:trims,error:trimError}]=await Promise.all([
    db.from("model_powertrains").select("*").eq("model_id",model.id).order("created_at"),
    db.from("trims").select("*").eq("model_id",model.id).order("sort_order").order("created_at")
  ]);
  if(ptError) throw ptError;
  if(trimError) throw trimError;

  const trimIds=(trims??[]).map((t:any)=>t.id);
  let links:any[]=[];
  if(trimIds.length){
    const {data,error}=await db.from("trim_powertrains").select("trim_id,powertrain_id").in("trim_id",trimIds);
    if(error) throw error;
    links=data??[];
  }

  const linkedTrims=(trims??[]).map((t:any)=>({
    ...t,
    trim_powertrains:links.filter((x:any)=>x.trim_id===t.id)
  }));

  return {...model,powertrains_detail:powertrains??[],trims:linkedTrims};
}
