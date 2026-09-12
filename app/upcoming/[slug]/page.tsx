import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { bodyLabel } from "@/lib/body-labels";
import { getCanonicalModels } from "@/lib/canonical-data";
import {
  launchWindowLabel,
  upcomingFactScopeLabel,
  upcomingStatusLabel,
  type UpcomingFactScope,
} from "@/lib/upcoming-schema";
import { getPublicUpcomingVehicleBySlug, getPublicUpcomingVehicles } from "@/lib/upcoming-vehicles";
import styles from "../upcoming.module.css";

export function generateStaticParams() {
  return getPublicUpcomingVehicles().map((vehicle) => ({ slug: vehicle.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const vehicle = getPublicUpcomingVehicleBySlug(slug);
  if (!vehicle) return { title: "Upcoming Vehicle | TDR Automotive Intelligence" };
  return {
    title: `${vehicle.brand} ${vehicle.working_name} — รถที่กำลังจะมา | TDR`,
    description: vehicle.summary || `${vehicle.brand} ${vehicle.working_name}: สถานะและช่วงเวลาเปิดตัวที่ TDR กำลังติดตามสำหรับตลาดไทย`,
  };
}

function displayDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  const months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
  return `${day} ${months[month]} ${year}`;
}

export default async function UpcomingDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const vehicle = getPublicUpcomingVehicleBySlug(slug);
  if (!vehicle) notFound();

  let catalogHref: string | null = null;
  if (vehicle.linked_model_id) {
    const models = await getCanonicalModels(600);
    const linked = (models as any[]).find((row) => row.id === vehicle.linked_model_id || row.canonical_id === vehicle.linked_model_id);
    if (linked?.slug) catalogHref = `/models/${linked.slug}`;
  }

  const factScopes: UpcomingFactScope[] = ["THAI_MARKET", "GLOBAL_SPEC", "EXPECTED"];
  const factGroups = factScopes
    .map((scope) => ({ scope, facts: (vehicle.facts || []).filter((fact) => fact.scope === scope) }))
    .filter((group) => group.facts.length);
  const timeline = [...vehicle.timeline].sort((a, b) => a.date.localeCompare(b.date));

  return <div className={styles.page}>
    <Link className={styles.back} href="/upcoming">← รถที่กำลังจะมา</Link>

    <section className={styles.detailHero}>
      <div>
        <div className={styles.eyebrow}>THAILAND LAUNCH ROADMAP</div>
        <span className={styles.status} data-status={vehicle.status} style={{ position: "static", display: "inline-block" }}>{upcomingStatusLabel(vehicle.status)}</span>
        <h1>{vehicle.brand} {vehicle.working_name}</h1>
        <p className={styles.detailLead}>{vehicle.summary || "TDR กำลังติดตามสถานะของรถรุ่นนี้สำหรับตลาดไทย รายละเอียดที่ยังไม่ยืนยันจะไม่ถูกเติมแทนด้วยสเปกจากตลาดอื่นโดยอัตโนมัติ"}</p>
        <div className={styles.launchBox}><small>ช่วงเวลาเปิดตัวที่ติดตาม</small><b>{launchWindowLabel(vehicle.launch_window)}</b></div>
        <div className={styles.headlineMeta}>
          {vehicle.body_type ? <span>{bodyLabel(vehicle.body_type) || vehicle.body_type}</span> : null}
          {vehicle.segment ? <span>Segment {vehicle.segment}</span> : null}
          {(vehicle.powertrains || []).map((value) => <span key={value}>{value}</span>)}
          <span>อัปเดต {vehicle.updated_at}</span>
        </div>
      </div>
      <div className={styles.detailVisual}>
        {vehicle.image_url ? <img src={vehicle.image_url} alt="" /> : <span>ยังไม่มีภาพในฐานข้อมูล</span>}
      </div>
    </section>

    <div className={styles.detailGrid}>
      <main>
        <section className={styles.section}>
          <div className={styles.sectionHead}><small>KNOWN SO FAR</small><h2>ข้อมูลที่มีอยู่ตอนนี้</h2></div>
          {factGroups.length ? factGroups.map((group) => <div className={styles.factGroup} key={group.scope}>
            <h3>{upcomingFactScopeLabel(group.scope)}</h3>
            {group.facts.map((fact) => <div className={styles.factRow} key={`${group.scope}:${fact.field_key}`}>
              <span>{fact.label}</span><b>{fact.value}</b><em>{fact.certainty}</em>
            </div>)}
          </div>) : <div className={styles.asideCard}><b>ยังไม่มี fact ที่เผยแพร่</b><p>ชื่อรถและ launch status สามารถถูกติดตามได้แม้สเปกไทยยังไม่ประกาศ ระบบจะไม่สร้าง Trim หรือเติมค่าจากรุ่นต่างประเทศให้เอง</p></div>}
        </section>

        <section className={styles.section}>
          <div className={styles.sectionHead}><small>SOURCE TIMELINE</small><h2>เส้นทางของข้อมูล</h2></div>
          {timeline.length ? <div className={styles.timeline}>{timeline.map((event, index) => <article className={styles.event} key={`${event.date}:${index}`}>
            <time dateTime={event.date}>{displayDate(event.date)} · {event.kind}</time>
            <h3>{event.title}</h3>
            {event.note ? <p>{event.note}</p> : null}
            {event.source_url ? <a href={event.source_url} target="_blank" rel="noreferrer">{event.source_label || "เปิดแหล่งข้อมูล"} ↗</a> : event.source_label ? <p>{event.source_label}</p> : null}
          </article>)}</div> : <div className={styles.asideCard}><b>ยังไม่มี timeline ที่เผยแพร่</b><p>เมื่อมีการยืนยัน เลื่อนกำหนด หรือมีหลักฐานใหม่ รายการจะถูกเพิ่มเป็นเหตุการณ์ใหม่แทนการเขียนทับประวัติเดิม</p></div>}
        </section>
      </main>

      <aside>
        <div className={styles.asideCard}><b>สถานะนี้ไม่ใช่ Current Catalog</b><p>รถก่อนเปิดตัวอยู่ใน Launch Roadmap แยกจาก Model / Generation / MarketTrim เพื่อไม่ให้ข้อมูลที่ยังไม่ครบถูกตีความว่าเป็นรถที่จำหน่ายอยู่แล้ว</p><Link href="/models">ดูแคตตาล็อกรถปัจจุบัน →</Link></div>
        <div className={styles.asideCard}><b>ความหมายของ “—”</b><p>ข้อมูลที่ไม่มีอยู่ในหน้านี้คือยังไม่มี fact ที่ TDR เลือกเผยแพร่ ไม่ได้แปลว่ารถไม่มีอุปกรณ์หรือคุณสมบัตินั้น</p></div>
        {catalogHref ? <div className={styles.asideCard}><b>เปิดตัวแล้ว</b><p>รายการนี้เชื่อมกับ canonical Vehicle Catalog แล้ว ประวัติใน Launch Roadmap ยังเก็บไว้เป็น timeline</p><Link href={catalogHref}>ไปหน้ารถในแคตตาล็อก →</Link></div> : null}
        <div className={styles.asideCard}><b>ติดตามตั้งแต่</b><p>{displayDate(vehicle.first_seen)} · อัปเดตล่าสุด {displayDate(vehicle.updated_at)}</p></div>
      </aside>
    </div>
  </div>;
}
