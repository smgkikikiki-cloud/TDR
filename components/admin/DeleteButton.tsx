"use client";
import { deleteModel, deleteBrand, deletePlant, deleteCompany, deleteEvent, deleteProductionProgram } from "@/app/admin/actions";

const actions={model:deleteModel,brand:deleteBrand,plant:deletePlant,company:deleteCompany,event:deleteEvent,production:deleteProductionProgram};
export function DeleteButton({kind,id,label="ลบ record",modelId}:{kind:keyof typeof actions;id:string;label?:string;modelId?:string}){
  const action=actions[kind];
  return <form action={action} onSubmit={e=>{if(!window.confirm("ยืนยันลบ record นี้จริง? ใช้ Delete สำหรับข้อมูลผิด/ซ้ำ ส่วนรถที่เลิกขายควรใช้ Discontinued"))e.preventDefault();}}><input type="hidden" name="id" value={id}/>{modelId?<input type="hidden" name="model_id" value={modelId}/>:null}<button type="submit" className="adminDangerButton">{label}</button></form>;
}
