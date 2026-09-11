import Link from "next/link";
import type { Metadata } from "next";
import { bodyLabel } from "@/lib/body-labels";
import {
  UPCOMING_STATUSES,
  launchWindowLabel,
  launchYear,
  upcomingStatusLabel,
  type UpcomingStatus,
} from "@/lib/upcoming-schema";
import {
  getPublicUpcomingVehicles,
  upcomingBodyTypes,
  upcomingBrands,
  upcomingPowertrains,
  upcomingYears,
} from "@/lib/upcoming-vehicles";
import styles from "./upcoming.module.css";

export const metadata: Metadata = {
  title: "รถที่กำลังจะมา | TDR Automotive Intelligence",
  description: "ติดตามรถที่มีข่าวว่าจะเข้าตลาดไทย ช่วงเวลาเปิดตัว และข้อมูลที่ยืนยันได้จากแหล่งสาธารณะ",
};

type Sp = Record<string, string | undefined>;

type PublicUpcomingVehicle = ReturnType<typeof getPublicUpcomingVehicles>[number];

function matches(vehicle: PublicUpcomingVehicle, sp: Sp) {
  const q = (sp.q || "").trim().toLocaleLowerCase();
  const year = Number(sp.year || 0);
  return (!q || [vehicle.brand, vehicle.working_name, vehicle.summary, vehicle.slug]
      .some((value) => String(value || "").toLocaleLowerCase().includes(q)))
    && (!sp.brand || vehicle.brand === sp.brand)
    && (!sp.status || vehicle.status === sp.status)
    && (!year || launchYear(vehicle) === year)
    && (!sp.body || vehicle.body_type === sp.body)
    && (!sp.powertrain || (vehicle.powertrains || []).includes(sp.powertrain));
}

function sortUpcoming(a: PublicUpcomingVehicle, b: PublicUpcomingVehicle) {
  const ad = a.launch_window.start || "9999-12-31";
  const bd = b.launch_window.start || "9999-12-31";
  return ad.localeCompare(bd) || a.brand.localeCompare(b.brand) || a.working_name.localeCompare(b.working_name);
}

function queryHasFilters(sp: Sp) {
  return Boolean(sp.q || sp.brand || sp.status || sp.year || sp.body || sp.powertrain);
}

export default async function UpcomingPage({ searchParams }: { searchParams: Promise<Sp> }) {
  const sp = await searchParams;
  const all = getPublicUpcomingVehicles();
  const terminal = new Set<UpcomingStatus>(["LAUNCHED", "CANCELLED"]);
  const base = sp.status ? all : all.filter((vehicle) => !terminal.has(vehicle.status));
  const vehicles = base.filter((vehicle) => matches(vehicle, sp)).sort(sortUpcoming);
  const brands = upcomingBrands(all);
  const years = upcomingYears(all);
  const bodies = upcomingBodyTypes(all);
  const powertrains = upcomingPowertrains(all);
  const confirmed = all.filter((vehicle) => vehicle.status === "CONFIRMED" || vehicle.status === "SCHEDULED").length;
  const dated = all.filter((vehicle) => vehicle.launch_window.precision !== "UNKNOWN").length;

  return <div className={styles.page}>
    <nav className={styles.scopeNav} aria-label="ขอบเขตแคตตาล็อก">
      <Link href="/models">รถที่จำหน่ายอยู่</Link>
      <Link href="/upcoming" className={styles.scopeOn} aria-current="page">รถที่กำลังจะมา</Link>
    </nav>

    <section className={styles.hero}>
      <div>
        <div className={styles.eyebrow}>THAILAND LAUNCH ROADMAP</div>
        <h1>รถที่กำลังจะมา</h1>
        <p>ฐานข้อมูล forward-looking สำหรับรถที่มีข่าวว่าจะเข้าตลาดไทยในช่วงหลายปีข้างหน้า ข้อมูลอาจยังไม่ครบโดยธรรมชาติ จึงแยกสถานะ ช่วงเวลา และหลักฐานออกจากแคตตาล็อกรถที่จำหน่ายอยู่</p>
      </div>
      <div className={styles.heroStats} aria-label="สรุปรายการ">
        <div><b>{all.length.toLocaleString("th-TH")}</b><span>รายการที่ติดตาม</span></div>
        <div><b>{confirmed.toLocaleString("th-TH")}</b><span>ยืนยัน / มีกำหนด</span></div>
        <div><b>{dated.toLocaleString("th-TH")}</b><span>มี launch window</span></div>
      </div>
    </section>

    <form className={styles.filterBar} method="get">
      <input name="q" defaultValue={sp.q || ""} placeholder="ค้นหาแบรนด์หรือรุ่นรถ" aria-label="ค้นหารถที่กำลังจะมา" />
      <select name="brand" defaultValue={sp.brand || ""} aria-label="แบรนด์"><option value="">ทุกแบรนด์</option>{brands.map((value) => <option key={value} value={value}>{value}</option>)}</select>
      <select name="year" defaultValue={sp.year || ""} aria-label="ปีที่คาดว่าจะเปิดตัว"><option value="">ทุกปี</option>{years.map((value) => <option key={value} value={value}>{value}</option>)}</select>
      <select name="status" defaultValue={sp.status || ""} aria-label="สถานะ"><option value="">สถานะที่ยังติดตาม</option>{UPCOMING_STATUSES.map((value) => <option key={value} value={value}>{upcomingStatusLabel(value)}</option>)}</select>
      <select name="body" defaultValue={sp.body || ""} aria-label="ตัวถัง"><option value="">ทุกตัวถัง</option>{bodies.map((value) => <option key={value} value={value}>{bodyLabel(value) || value}</option>)}</select>
      <select name="powertrain" defaultValue={sp.powertrain || ""} aria-label="Powertrain"><option value="">ทุก Powertrain</option>{powertrains.map((value) => <option key={value} value={value}>{value}</option>)}</select>
      <button type="submit">กรอง</button>
      {queryHasFilters(sp) ? <Link href="/upcoming">ล้าง</Link> : <span />}
    </form>

    <div className={styles.summaryRow}>
      <span>พบ <b>{vehicles.length.toLocaleString("th-TH")}</b> รายการ</span>
      <div className={styles.legend}><span>RUMORED = ยังเป็นข่าวลือ</span><span>EXPECTED = มีเหตุผลคาดว่าจะมา</span><span>CONFIRMED = ยืนยันตลาดไทย</span></div>
    </div>

    {vehicles.length ? <div className={styles.grid}>
      {vehicles.map((vehicle) => <article className={styles.card} key={vehicle.id}>
        <Link href={`/upcoming/${vehicle.slug}`} className={styles.visual}>
          {vehicle.image_url ? <img src={vehicle.image_url} alt="" /> : <span className={styles.placeholder}>UPCOMING VEHICLE</span>}
          <span className={styles.status} data-status={vehicle.status}>{upcomingStatusLabel(vehicle.status)}</span>
        </Link>
        <div className={styles.body}>
          <span className={styles.brand}>{vehicle.brand}</span>
          <Link href={`/upcoming/${vehicle.slug}`}><h2>{vehicle.working_name}</h2></Link>
          <div className={styles.launch}>{launchWindowLabel(vehicle.launch_window)}</div>
          <div className={styles.meta}>
            {vehicle.body_type ? <span>{bodyLabel(vehicle.body_type) || vehicle.body_type}</span> : null}
            {vehicle.segment ? <span>Segment {vehicle.segment}</span> : null}
            {(vehicle.powertrains || []).map((value) => <span key={value}>{value}</span>)}
          </div>
          {vehicle.summary ? <p className={styles.summary}>{vehicle.summary}</p> : null}
          <div className={styles.cardFoot}><small>อัปเดต {vehicle.updated_at}</small><Link href={`/upcoming/${vehicle.slug}`}>ดูรายละเอียด →</Link></div>
        </div>
      </article>)}
    </div> : <div className={styles.empty}>
      <b>{all.length ? "ไม่พบรายการที่ตรงกับตัวกรอง" : "ยังไม่มีรายการ Upcoming ที่เผยแพร่"}</b>
      <p>{all.length ? "ลองล้างตัวกรองหรือเลือกช่วงเวลาที่กว้างขึ้น" : "โครงสร้าง Launch Roadmap พร้อมแล้ว แต่ยังไม่ใส่ชื่อรถหรือข่าวลือใดๆ จนกว่าจะมีข้อมูลที่ TDR เลือกบันทึกพร้อมแหล่งอ้างอิง"}</p>
      <Link href={all.length ? "/upcoming" : "/models"}>{all.length ? "ล้างตัวกรอง" : "กลับไปแคตตาล็อกรถยนต์"}</Link>
    </div>}
  </div>;
}
