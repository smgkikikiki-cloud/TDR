import { adminDb } from "@/lib/supabase";
import { ModelForm } from "@/components/admin/ModelForm";
export default async function NewModel(){const db=adminDb();const {data:brands}=db?await db.from("brands").select("id,name_th").order("name_th"):{data:[]};return <div className="adminEditor"><div className="adminHeader"><div><small>MODEL MASTER · V1.1</small><h1>เพิ่มรุ่นรถ</h1><p>กรอก Consumer + Powertrain + Trim จากหน้าเดียว ระบบจะใช้ข้อมูลชุดเดียวกันสร้าง Catalog และเชื่อม Industry layer</p></div></div><ModelForm brands={brands??[]}/></div>}
