import type { ReactNode } from "react";
import { saveProductionProgram } from "@/app/admin/actions";
import { DeleteButton } from "@/components/admin/DeleteButton";
import { Field, Select, TextArea } from "@/components/admin/Fields";

type Row = Record<string, any>;

function PUnconfirmed({ field, checked = false }: { field: string; checked?: boolean }) {
  return <label className="adminUnconfirmed"><input type="checkbox" name="program_unconfirmed_fields" value={field} defaultChecked={checked}/><span>Unconfirmed</span></label>;
}
function PF({ field, checked, children }: { field: string; checked: boolean; children: ReactNode }) {
  return <div className="adminConfidenceField">{children}<PUnconfirmed field={field} checked={checked}/></div>;
}

export function ProductionProgramForm({modelId, plants, program, localContent, mit}:{modelId:string;plants:Row[];program?:Row|null;localContent?:Row|null;mit?:Row|null}) {
  const uncertain = new Set<string>(program?.unconfirmed_fields || []);
  return <div className="adminSubFormWrap"><form action={saveProductionProgram} className="adminSubForm">
    <input type="hidden" name="model_id" value={modelId}/>{program?.id?<input type="hidden" name="id" value={program.id}/>:null}
    <div className="adminSubFormHead"><div><small>THAILAND PRODUCTION</small><h3>{program?.id ? "แก้ข้อมูลการผลิตไทย" : "เพิ่มข้อมูลการผลิตไทย"}</h3></div>{program?.id?<span>PROGRAM RECORD</span>:<span>NEW</span>}</div>
    <div className="adminForm adminEmbeddedGrid">
      <PF field="plant_id" checked={uncertain.has("plant_id")}><Select label="โรงงาน" name="plant_id" defaultValue={program?.plant_id}><option value="">— ว่าง —</option>{plants.map(p=><option key={p.id} value={p.id}>{p.name_th}{p.province?` · ${p.province}`:""}</option>)}</Select></PF>
      <PF field="production_type" checked={uncertain.has("production_type")}><Select label="รูปแบบการผลิต" name="production_type" defaultValue={program?.production_type}><option value="">— ว่าง —</option><option value="CBU">CBU</option><option value="CKD">CKD</option><option value="SKD">SKD</option></Select></PF>
      <PF field="status" checked={uncertain.has("status")}><Select label="สถานะการผลิต" name="status" defaultValue={program?.status}><option value="">— ว่าง —</option><option value="planned">Planned</option><option value="active">Active</option><option value="ended">Ended</option></Select></PF>
      <PF field="platform" checked={uncertain.has("platform")}><Field label="Platform" name="platform" defaultValue={program?.platform} placeholder="เช่น TNGA-C"/></PF>
      <PF field="annual_production_estimate" checked={uncertain.has("annual_production_estimate")}><Field label="ปริมาณผลิต/ปี (ถ้าหาได้)" name="annual_production_estimate" type="number" defaultValue={program?.annual_production_estimate}/></PF>
      <PF field="production_volume_year" checked={uncertain.has("production_volume_year")}><Field label="ปีของตัวเลขผลิต" name="production_volume_year" type="number" defaultValue={program?.production_volume_year}/></PF>
      <PF field="export_volume_estimate" checked={uncertain.has("export_volume_estimate")}><Field label="ส่งออก/ปี (ถ้าหาได้)" name="export_volume_estimate" type="number" defaultValue={program?.export_volume_estimate}/></PF>
      <PF field="export_volume_year" checked={uncertain.has("export_volume_year")}><Field label="ปีของตัวเลขส่งออก" name="export_volume_year" type="number" defaultValue={program?.export_volume_year}/></PF>
      <PF field="export_markets" checked={uncertain.has("export_markets")}><Field label="ตลาดส่งออก" name="export_markets" defaultValue={program?.export_markets} placeholder="เช่น ASEAN, Australia, Japan"/></PF>
      <PF field="story_th" checked={uncertain.has("story_th")}><TextArea label="สตอรี่ / บริบทการผลิตในไทย" name="story_th" defaultValue={program?.story_th}/></PF>

      <div className="adminMiniPanel adminFieldWide"><b>Local content — ตามที่ผู้ผลิตประกาศ</b><div className="adminMiniGrid"><Field label="Local content (%)" name="local_content_percentage" type="number" defaultValue={localContent?.percentage}/><Field label="ประกาศโดย" name="local_content_announced_by" defaultValue={localContent?.announced_by} placeholder="เช่น Toyota Motor Thailand"/><Field label="ปีที่ประกาศ" name="local_content_year" type="number" defaultValue={localContent?.announcement_year}/><Field label="Source URL" name="local_content_source_url" defaultValue={localContent?.source_url}/></div><label className="adminUnconfirmed"><input type="checkbox" name="local_content_unconfirmed" defaultChecked={!!localContent?.unconfirmed}/><span>Unconfirmed</span></label></div>

      <div className="adminMiniPanel adminFieldWide"><b>Made in Thailand (MiT)</b><div className="adminMiniGrid"><label className="adminCheckItem simpleCheck"><input type="checkbox" name="mit_approved" defaultChecked={!!mit?.approved}/><span><b>MiT approved</b></span></label><Field label="ตั้งแต่ปี" name="mit_valid_from_year" type="number" defaultValue={mit?.valid_from_year}/><Field label="ถึงปี" name="mit_valid_to_year" type="number" defaultValue={mit?.valid_to_year}/><Field label="Reference / Source" name="mit_source_url" defaultValue={mit?.source_url}/></div><label className="adminUnconfirmed"><input type="checkbox" name="mit_unconfirmed" defaultChecked={!!mit?.unconfirmed}/><span>Unconfirmed</span></label></div>

      <Field label="Source name" name="source_name" defaultValue={program?.source_name}/><Field label="Source URL" name="source_url" defaultValue={program?.source_url}/>
      <div className="adminFormActions"><button className="adminPrimary">{program?.id ? "บันทึกข้อมูลการผลิต" : "เพิ่มข้อมูลการผลิต"}</button></div>
    </div>
  </form>{program?.id?<div className="adminSubDelete"><DeleteButton kind="production" id={program.id} modelId={modelId} label="ลบ Production Program"/></div>:null}</div>;
}
