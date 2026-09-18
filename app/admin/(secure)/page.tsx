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
  const [models, trims, brands, releases, plants, events] = await Promise.all([
    count("current_vehicle_models"), count("current_market_trims"), count("current_vehicle_brands"),
    count("canonical_vehicle_releases"), count("plants"), count("events"),
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
    <div className="adminStatGrid">{[["Canonical models", models], ["MarketTrims", trims], ["Canonical brands", brands], ["Releases", releases], ["โรงงาน", plants], ["ข่าว", events]].map(([label, value]) => <div className="adminStat" key={String(label)}><span>{label}</span><strong>{value ?? "—"}</strong><small>records</small></div>)}</div>
    {/* Editing a car has one home. The tiles below are the queues somebody
        works through on a given day, not five alternative ways in. */}
    <div className="adminQuickGrid">
      <Link href="/admin/prices/coverage"><b>Price coverage</b><span>รุ่นที่ยังไม่มีราคาที่ตรวจสอบได้</span></Link>
      <Link href="/admin/eco-trims"><b>ECO → MarketTrim review</b><span>คิวยืนยัน trim identity จาก ECO Sticker</span></Link>
      <Link href="/admin/retail-lifecycle"><b>Retail lifecycle</b><span>รุ่นที่ยังแยกไม่ได้ว่าขายอยู่หรือเลิกแล้ว</span></Link>
      <Link href="/admin/data-quality"><b>Data quality</b><span>ช่องว่างที่ต้องปิดก่อนเลิกใช้ระบบเก่า</span></Link>
      <Link href="/admin/registrations"><b>Registration ops</b><span>ingest และ alias ที่รีวิวแล้ว</span></Link>
      <Link href="/admin/library?table=canonical_vehicle_releases"><b>Vehicle releases</b><span>ดู release ที่ publish ไปแล้ว</span></Link>
    </div>
  </>;
}
