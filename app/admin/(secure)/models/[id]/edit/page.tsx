import { notFound } from "next/navigation";
import { adminDb } from "@/lib/supabase";
import { saveModelEditorial } from "@/app/admin/catalog-actions";
import { ProductionProgramForm } from "@/components/admin/ProductionProgramForm";

export default async function EditModel({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const db = adminDb();
  if (!db) notFound();
  const [{ data: model }, { data: plants }, { data: programs }] = await Promise.all([
    db.from("models").select("*, brands(name_th)").eq("id", id).maybeSingle(),
    db.from("plants").select("id,name_th,province,maker_group").order("maker_group").order("name_th"),
    db.from("production_programs").select("*").eq("model_id", id).order("created_at"),
  ]);
  if (!model) notFound();

  const enriched = [] as any[];
  for (const program of programs || []) {
    const [{ data: localContent }, { data: mit }] = await Promise.all([
      db.from("local_content_declarations").select("*").eq("production_program_id", program.id).order("created_at", { ascending: false }).limit(1).maybeSingle(),
      db.from("mit_approvals").select("*").eq("production_program_id", program.id).order("created_at", { ascending: false }).limit(1).maybeSingle(),
    ]);
    enriched.push({ program, localContent, mit });
  }

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>CANONICAL BOUNDARY</small>
        <h1>{model.brands?.name_th ? `${model.brands.name_th} ` : ""}{model.name_th}</h1>
        <p>Identity, generation, trim, powertrain, spec และราคาแก้ที่ automotive/vehicle_master/ เท่านั้น หน้านี้รับเฉพาะ editorial กับ industry context ของ TDR</p>
      </div>
    </div>
    {sp.saved ? <div className="adminSaved">บันทึก editorial fields แล้ว</div> : null}
    <form action={saveModelEditorial} className="adminModelMasterForm">
      <input type="hidden" name="id" value={id} />
      <div className="adminForm">
        <label>ตำแหน่งตลาด<input name="market_position" defaultValue={model.market_position || ""} /></label>
        <label>URL รูปภาพ<input name="image_url" defaultValue={model.image_url || ""} /></label>
        <label>คำอธิบายสำหรับผู้อ่าน<textarea name="consumer_description" defaultValue={model.consumer_description || ""} /></label>
        <label>หมายเหตุภายใน<textarea name="notes" defaultValue={model.notes || ""} /></label>
        <label><input type="checkbox" name="featured" defaultChecked={Boolean(model.featured)} /> รุ่นเด่น</label>
        <div className="adminFormActions"><button className="adminPrimary">บันทึก Editorial</button></div>
      </div>
    </form>
    <section className="adminDeepLayer">
      <div className="adminDeepLayerHead"><small>THAILAND PRODUCTION · OPTIONAL</small><h2>ข้อมูลรถในฐานะอุตสาหกรรม</h2><p>ข้อมูลนี้อ้าง TDR UUID ผ่าน crosswalk และไม่ถูกนำไปรวมเป็น MarketTrim</p></div>
      <div className="adminSubSection"><h3>Production Programs</h3>{enriched.map(({ program, localContent, mit }) => <ProductionProgramForm key={program.id} modelId={id} plants={plants || []} program={program} localContent={localContent} mit={mit} />)}<ProductionProgramForm modelId={id} plants={plants || []} /></div>
    </section>
  </div>;
}
