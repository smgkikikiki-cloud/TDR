import Link from "next/link";
import { adminDb } from "@/lib/supabase";

async function count(table: string) {
  const db = adminDb();
  if (!db) return null;
  const { count } = await db.from(table).select("*", { count: "exact", head: true });
  return count || 0;
}

export default async function AdminHome() {
  const [models, trims, brands, releases, plants, events] = await Promise.all([
    count("current_vehicle_models"), count("current_market_trims"), count("current_vehicle_brands"),
    count("canonical_vehicle_releases"), count("plants"), count("events"),
  ]);
  return <>
    <div className="adminHeader">
      <div><small>TDR AUTO · CANONICAL</small><h1>ภาพรวมฐานข้อมูล</h1><p>แก้ vehicle facts ครั้งเดียวใน automotive/ แล้ว release เดียวจะอัปเดตทุก public projection; Supabase เก็บ editorial, industry และ registration แยกกัน</p></div>
      <Link className="adminPrimaryLink" href="/admin/library?table=canonical_vehicle_releases">เปิด Vehicle releases</Link>
    </div>
    <div className="adminStatGrid">{[["Canonical models", models], ["MarketTrims", trims], ["Canonical brands", brands], ["Releases", releases], ["โรงงาน", plants], ["ข่าว", events]].map(([label, value]) => <div className="adminStat" key={String(label)}><span>{label}</span><strong>{value ?? "—"}</strong><small>records</small></div>)}</div>
    <div className="adminQuickGrid">
      <Link href="/admin/library?table=models"><b>Editorial model links</b><span>รูป คำอธิบาย รุ่นเด่น และ industry link เท่านั้น</span></Link>
      <Link href="/admin/plants/new"><b>+ เพิ่มโรงงาน</b><span>Capacity / production / utilization</span></Link>
      <Link href="/admin/events/new"><b>+ เพิ่มข่าว / Event</b><span>ผูกกับ TDR editorial UUID ผ่าน crosswalk</span></Link>
      <Link href="/admin/library?table=registrations"><b>Registration library</b><span>แยกจาก MarketTrim และเปิดเฉพาะ analytics entitlement</span></Link>
    </div>
  </>;
}
