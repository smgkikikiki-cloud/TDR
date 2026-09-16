"use client";

import Link from "next/link";
import { useEffect } from "react";
import styles from "./pricing.module.css";

function track(event: "upgrade_viewed" | "corporate_cta_clicked") {
  fetch("/api/telemetry", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  }).catch(() => {});
}

export default function PricingPage() {
  useEffect(() => { track("upgrade_viewed"); }, []);

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.eyebrow}>TDR REPORT · แพ็กเกจ</div>
        <h1>เลือกแพ็กเกจที่ตรงกับการใช้งาน</h1>
        <p>ข้อมูลรถ ราคา และสเปกยังเปิดสาธารณะเสมอ — แพ็กเกจด้านล่างคือสิทธิ์การใช้เครื่องมือวิเคราะห์ (Compare, Sales Tools, Research, Export)</p>
      </header>

      <section className={styles.grid}>
        <article className={styles.card}>
          <div>
            <div className={styles.cardName}>Free</div>
            <div className={styles.price}>฿0</div>
          </div>
          <ul className={styles.features}>
            <li>✓ Vehicle Compare — 3 ครั้ง/วัน</li>
            <li>✓ Sales Tools — เลือก 4 จาก 6 โมดูล, 10 คำขอ/วัน</li>
            <li>✓ ประวัติข้อมูล — ปีปฏิทินปัจจุบัน</li>
            <li>✓ Research — preview เท่านั้น</li>
            <li>✓ PDF export — 1 ครั้ง/เดือน (มีลายน้ำ TDR Free)</li>
            <li>— ไม่มี API, ไม่มี CSV/XLSX/raw export</li>
          </ul>
          <Link className={`${styles.cta} ${styles.ctaGhost}`} href="/member/login">เริ่มใช้ฟรี</Link>
        </article>

        <article className={styles.card}>
          <div>
            <div className={styles.cardName}>Individual</div>
            <div className={styles.price}>฿399<small>/เดือน</small></div>
          </div>
          <ul className={styles.features}>
            <li>✓ Vehicle Compare — ไม่จำกัด ทุกรุ่น</li>
            <li>✓ Sales Tools — ทุกโมดูล ไม่จำกัดคำขอ</li>
            <li>✓ ประวัติข้อมูล — ย้อนหลัง 24 เดือน</li>
            <li>✓ Research ฉบับเต็ม — 3 ชิ้น/เดือน</li>
            <li>✓ PDF export — 10 ครั้ง/เดือน</li>
            <li>— ไม่มี API, ไม่มี CSV/XLSX/raw export</li>
          </ul>
          <Link className={styles.cta} href="/member/billing">สมัคร Individual</Link>
        </article>

        <article className={styles.card}>
          <div>
            <div className={styles.cardName}>Pro</div>
            <div className={styles.price}>฿990<small>/เดือน</small></div>
          </div>
          <ul className={styles.features}>
            <li>✓ ทุกอย่างใน Individual</li>
            <li>✓ ประวัติข้อมูล — เต็มรูปแบบเท่าที่มี</li>
            <li>✓ Research ฉบับเต็ม — ไม่จำกัด</li>
            <li>✓ PDF export — ไม่จำกัด</li>
            <li>— ไม่มี API สำหรับดึงข้อมูลดิบ (สงวนไว้สำหรับ Corporate)</li>
          </ul>
          <Link className={styles.cta} href="/member/billing">สมัคร Pro</Link>
        </article>
      </section>

      <section className={styles.corporate}>
        <div>
          <div className={styles.eyebrow} style={{ color: "#bbb" }}>CORPORATE</div>
          <h2>Solutions tailored for your team</h2>
          <p>แพ็กเกจสำหรับทีม/องค์กร ไม่ใช่แค่ Pro ที่แพงขึ้น — ขอบเขตและราคาปรับตามการใช้งานจริง อาจถูกหรือแพงกว่า Pro คูณจำนวนที่นั่งก็ได้ ขึ้นกับ scope ที่ตกลงกัน</p>
          <ul>
            <li>· Team access หลายที่นั่ง</li>
            <li>· Workflow ที่ปรับให้เข้ากับทีมคุณ</li>
            <li>· API/data integration แบบมีขอบเขต (ไม่ใช่ raw data ทั้งชุด)</li>
            <li>· Research support และรายงานที่ปรับแต่งได้</li>
          </ul>
        </div>
        <a
          className={styles.corporateCta}
          href="mailto:sales@thailanddevelopmentreport.com?subject=TDR%20Corporate"
          onClick={() => track("corporate_cta_clicked")}
        >
          Talk to TDR →
        </a>
      </section>
    </main>
  );
}
