import { adminDb } from "@/lib/supabase";
import { ModelFormV12 } from "@/components/admin/ModelFormV12";

export default async function NewModel(){
  const db=adminDb();
  const {data:brands}=db?await db.from("brands").select("id,name_th").order("name_th"):{data:[]};
  return <div className="adminEditor">
    <div className="adminHeader"><div><small>MODEL MASTER · V1.2</small><h1>เพิ่มรุ่นรถ</h1><p>กรอก Consumer + Powertrain + Trim + Range จากหน้าเดียว แล้วค่อยเติม Industry layer หลังบันทึกครั้งแรก</p></div></div>
    <ModelFormV12 brands={brands??[]}/>
  </div>;
}
