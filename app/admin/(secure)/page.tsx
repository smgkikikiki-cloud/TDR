import Link from "next/link";
import { adminDb } from "@/lib/supabase";

async function count(table: string) {
  const db = adminDb();
  if (!db) return null;
  const { count } = await db.from(table).select("*", { count: "exact", head: true });
  return count || 0;
}

export default async function AdminHome({ searchParams }: { searchParams: Promise<{ canonical?: string }> }) {
  const { canonical } = await searchParams;
  // Cars, not machinery: release counts, plants and events were a picture
  // of subsystems rather than of the catalogue somebody came here to work on.
  const [models, trims, brands] = await Promise.all([
    count("current_vehicle_models"), count("current_market_trims"), count("current_vehicle_brands"),
  ]);
  return <>
    <div className="adminHeader">
      <div><small>TDR AUTO · CANONICAL</small><h1>ภาพรวมฐานข้อมูล</h1><p>แก้ vehicle facts ครั้งเดียวใน automotive/vehicle_master/ แล้ว release เดียวจะอัปเดตทุก public projection; Supabase เก็บ editorial, industry และ registration แยกกัน</p></div>
      <Link className="adminPrimaryLink" href="/admin/vehicles">แก้ข้อมูลรถ</Link>
    </div>
    {canonical ? <div className="adminNotice">
      <b>สร้างรถ/แบรนด์ใหม่ที่หน้านั้นไม่ได้แล้ว</b>
      <span>
        รุ่นและแบรนด์เป็น canonical identity — สร้าง/แก้ผ่าน <Link href="/admin/vehicles">Canonical Vehicle Editor</Link> หรือ
        automotive/vehicle_master แล้ว publish หนึ่ง release เท่านั้น จึงเด้งกลับมาหน้านี้
      </span>
    </div> : null}
    <div className="adminStatGrid">{[["Canonical models", models], ["MarketTrims", trims], ["Canonical brands", brands]].map(([label, value]) => <div className="adminStat" key={String(label)}><span>{label}</span><strong>{value ?? "—"}</strong><small>records</small></div>)}</div>
    {/* The three places work actually starts. Release counts, coverage
        reports and review queues were views onto machinery that now runs
        behind a save, so they are not offered as somewhere to begin. */}
    <div className="adminQuickGrid">
      <Link href="/admin/vehicles"><b>แก้ข้อมูลรถ</b><span>เปิดรถหนึ่งคัน แก้ได้ครบในหน้าเดียว</span></Link>
      <Link href="/admin/import"><b>นำเข้าข้อมูล</b><span>อัปไฟล์ ระบบจับคู่และเขียนให้เอง</span></Link>
      <Link href="/admin/exceptions"><b>รายการที่ต้องตัดสิน</b><span>เฉพาะที่ระบบตัดสินแทนไม่ได้</span></Link>
    </div>
  </>;
}
