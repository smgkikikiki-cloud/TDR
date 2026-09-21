"use client";

import Link from "next/link";
import { useEffect } from "react";
import { FEATURES, TIER_POLICIES, SALES_MODULES } from "@/lib/access-policy";
import { PLAN_CATALOG } from "@/lib/plans";
import styles from "./pricing.module.css";

function track(event: "upgrade_viewed" | "corporate_cta_clicked") {
  fetch("/api/telemetry", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  }).catch(() => {});
}

const FREE_POLICY = TIER_POLICIES.FREE;
const PRO_POLICY = TIER_POLICIES.PRO;
const RESEARCH_LIVE = FEATURES.research_reports.released;
const PDF_LIVE = FEATURES.pdf_export_reports.released;
const CORPORATE_CONTACT_URL = process.env.NEXT_PUBLIC_TDR_CORPORATE_CONTACT_URL || "";

const INTERVAL_LABEL: Record<string, string> = {
  monthly: "รายเดือน",
  quarterly: "3 เดือน",
  annual: "รายปี",
};

function money(value: number) {
  return value.toLocaleString("th-TH");
}

function limit(value: number | null, unit: string) {
  return value === null ? "ไม่จำกัด" : `${value} ${unit}`;
}

export default function PricingPage() {
  useEffect(() => { track("upgrade_viewed"); }, []);

  const proFrom = Math.min(...PLAN_CATALOG.map((plan) => plan.priceThbPerMonth));

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.eyebrow}>TDR AUTOMOTIVE INTELLIGENCE · แพ็กเกจ</div>
        <h1>แพ็กเกจ TDR Automotive Intelligence</h1>
        <p>ฐานข้อมูลรถ ราคา รุ่นย่อย และสเปกเปิดใช้ฟรี · Pro เพิ่มความลึกของ Market Intelligence และบทวิเคราะห์</p>
      </header>

      <div className={styles.anonymousNote}>
        <b>ยังไม่เข้าสู่ระบบ</b>
        <span>เทียบรถได้ 10 ครั้ง/วัน</span>
        <span>เปิด Market ได้ 1 ครั้ง/วัน</span>
      </div>

      <section className={styles.tierGrid} aria-label="แพ็กเกจ TDR">
        <article className={styles.tierCard}>
          <div className={styles.tierTop}>
            <div className={styles.cardName}>FREE</div>
            <div className={styles.price}>฿0</div>
            <p>บัญชีฟรีสำหรับใช้งานข้อมูลและเครื่องมือพื้นฐาน</p>
          </div>

          <div className={styles.featureGroup}>
            <h2>ข้อมูลรถ</h2>
            <ul>
              <li>แคตตาล็อก / รุ่น / รุ่นย่อย / สเปก — ไม่จำกัด</li>
              <li>Vehicle Compare — {limit(FREE_POLICY.compareDailyLimit, "ครั้ง/วัน")}</li>
            </ul>
          </div>

          <div className={styles.featureGroup}>
            <h2>Market Intelligence</h2>
            <ul>
              <li>{FREE_POLICY.salesQueryDailyLimit} queries / วัน</li>
              <li>Sales Tools — เลือก {FREE_POLICY.salesModulePickCount} จาก {SALES_MODULES.length} โมดูล</li>
              <li>เดือนเดียว + Rolling 3 เดือน</li>
              <li>ประวัติย้อนหลัง 12 เดือน</li>
              <li>เทียบกับเดือนก่อนหน้า</li>
              <li>ไม่มีตัวกรองตลาดขั้นสูง</li>
            </ul>
          </div>

          <div className={styles.featureGroup}>
            <h2>TDR Analysis</h2>
            <ul>
              <li>{RESEARCH_LIVE ? `อ่านเต็ม ${FREE_POLICY.researchFullMonthlyLimit} บทความ / เดือน` : "เร็วๆ นี้"}</li>
            </ul>
          </div>

          <Link className={`${styles.cta} ${styles.ctaGhost}`} href="/member/login">เริ่มใช้ฟรี</Link>
        </article>

        <article className={`${styles.tierCard} ${styles.proCard}`}>
          <div className={styles.proFlag}>PRO</div>
          <div className={styles.tierTop}>
            <div className={styles.cardName}>TDR PRO</div>
            <div className={styles.price}>เริ่ม ฿{money(proFrom)}<small>/เดือน</small></div>
            <p>Market Intelligence แบบเต็ม สิทธิ์เท่ากันทุกระยะการชำระ</p>
          </div>

          <div className={styles.featureGroup}>
            <h2>ทุกอย่างใน Free</h2>
            <ul>
              <li>Vehicle Compare — ไม่จำกัด</li>
              <li>Sales Tools / Market queries — ไม่จำกัด</li>
            </ul>
          </div>

          <div className={styles.featureGroup}>
            <h2>Market Intelligence</h2>
            <ul>
              <li>ครบทุกมุมมอง รวมข้อมูลระดับรายรุ่น</li>
              <li>เดือน / Rolling 3 / 6 / 12 เดือน / YTD</li>
              <li>ประวัติข้อมูลทั้งคลัง</li>
              <li>เทียบเดือนก่อนหน้า + YoY</li>
              <li>ตัวกรองตลาดขั้นสูง</li>
            </ul>
          </div>

          <div className={styles.featureGroup}>
            <h2>TDR Analysis</h2>
            <ul>
              <li>{RESEARCH_LIVE ? "อ่านบทวิเคราะห์ไม่จำกัด" : "เร็วๆ นี้"}</li>
            </ul>
          </div>

          <Link className={styles.cta} href="/member/billing">สมัคร TDR Pro</Link>
        </article>

        <article className={`${styles.tierCard} ${styles.enterpriseCard}`}>
          <div className={styles.tierTop}>
            <div className={styles.cardName}>TDR ENTERPRISE</div>
            <div className={styles.enterprisePrice}>Tailored package for your team</div>
            <p>จำนวนผู้ใช้ ขอบเขตข้อมูล วิธีเข้าถึง และราคา ปรับตาม workflow ของแต่ละองค์กร</p>
          </div>

          <div className={styles.featureGroup}>
            <h2>สิ่งที่ปรับตามทีม</h2>
            <ul>
              <li>จำนวนผู้ใช้และสิทธิ์การเข้าถึง</li>
              <li>ขอบเขตข้อมูลและตลาดที่ต้องใช้</li>
              <li>รูปแบบการส่งมอบข้อมูล</li>
              <li>ราคาและเงื่อนไขตาม scope จริง</li>
            </ul>
          </div>

          <div className={styles.featureGroup}>
            <h2>เครื่องมือสำหรับองค์กร</h2>
            <ul>
              <li>รวมสิทธิ์ TDR Pro</li>
              <li>API / Raw export</li>
              <li>Data integration</li>
              <li>Team onboarding &amp; support</li>
            </ul>
          </div>

          <p className={styles.enterpriseNote}>ไม่มีราคาแพ็กเกจตายตัว — เสนอราคาตามจำนวนผู้ใช้ ขอบเขตข้อมูล และรูปแบบการใช้งานของทีม</p>

          {CORPORATE_CONTACT_URL ? (
            <a className={`${styles.cta} ${styles.enterpriseCta}`} href={CORPORATE_CONTACT_URL} onClick={() => track("corporate_cta_clicked")}>คุยกับ TDR Enterprise →</a>
          ) : (
            <span className={`${styles.cta} ${styles.enterpriseCta} ${styles.disabledCta}`} aria-disabled="true">คุยกับ TDR Enterprise →</span>
          )}
        </article>
      </section>

      <section className={styles.billingSection} aria-labelledby="pro-billing-title">
        <div className={styles.sectionHead}>
          <div>
            <div className={styles.eyebrow}>TDR PRO · การชำระเงิน</div>
            <h2 id="pro-billing-title">เลือกการชำระสำหรับ TDR Pro</h2>
          </div>
          <p>ทุกตัวเลือกได้สิทธิ์ Pro เหมือนกัน ต่างกันเฉพาะระยะผูกมัดและรอบเรียกเก็บ</p>
        </div>

        <div className={styles.billingGrid}>
          {PLAN_CATALOG.map((plan) => (
            <Link className={styles.billingCard} href="/member/billing" key={plan.planCode}>
              <div className={styles.billingName}>{INTERVAL_LABEL[plan.interval] || plan.interval}</div>
              <div className={styles.billingPrice}>฿{money(plan.priceThbPerMonth)}<small>/เดือน</small></div>
              <div className={styles.billingInvoice}>เรียกเก็บ ฿{money(plan.priceThbPerInterval)} ต่อรอบ</div>
              <span>เลือกแพ็กเกจ →</span>
            </Link>
          ))}
        </div>
      </section>

      <section className={styles.compareSection} aria-labelledby="compare-plans-title">
        <div className={styles.sectionHead}>
          <div>
            <div className={styles.eyebrow}>สิทธิ์การใช้งาน</div>
            <h2 id="compare-plans-title">เปรียบเทียบแพ็กเกจ</h2>
          </div>
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.compareTable}>
            <thead>
              <tr><th>ฟีเจอร์ / ข้อมูล</th><th>Free</th><th>Pro</th><th>Enterprise</th></tr>
            </thead>
            <tbody>
              <tr><th>แคตตาล็อก / รุ่น / รุ่นย่อย / สเปก</th><td>ไม่จำกัด</td><td>ไม่จำกัด</td><td>ไม่จำกัด</td></tr>
              <tr><th>Vehicle Compare</th><td>ไม่จำกัด</td><td>ไม่จำกัด</td><td>ไม่จำกัด</td></tr>
              <tr><th>Sales Tools</th><td>{FREE_POLICY.salesModulePickCount} จาก {SALES_MODULES.length} โมดูล</td><td>ทั้งหมด</td><td>ทั้งหมด</td></tr>
              <tr><th>Market queries</th><td>{FREE_POLICY.salesQueryDailyLimit} / วัน</td><td>ไม่จำกัด</td><td>ไม่จำกัด</td></tr>
              <tr><th>ข้อมูลระดับรายรุ่น</th><td>—</td><td>✓</td><td>✓</td></tr>
              <tr><th>ช่วงเวลา Market</th><td>เดือน + Rolling 3</td><td>เดือน + Rolling 3 / 6 / 12 + YTD</td><td>ตาม Pro</td></tr>
              <tr><th>ประวัติย้อนหลัง</th><td>12 เดือน</td><td>ทั้งคลัง</td><td>ทั้งคลัง</td></tr>
              <tr><th>การเปรียบเทียบช่วงเวลา</th><td>เดือนก่อนหน้า</td><td>เดือนก่อนหน้า + YoY</td><td>ตาม Pro</td></tr>
              <tr><th>ตัวกรองตลาดขั้นสูง</th><td>—</td><td>✓</td><td>✓</td></tr>
              <tr><th>TDR Analysis</th><td>{RESEARCH_LIVE ? `${FREE_POLICY.researchFullMonthlyLimit} บท / เดือน` : "เร็วๆ นี้"}</td><td>{RESEARCH_LIVE ? "ไม่จำกัด" : "เร็วๆ นี้"}</td><td>{RESEARCH_LIVE ? "ไม่จำกัด" : "เร็วๆ นี้"}</td></tr>
              <tr><th>PDF export</th><td>{PDF_LIVE ? `${FREE_POLICY.pdfMonthlyLimit} / เดือน · มีลายน้ำ` : "เร็วๆ นี้"}</td><td>{PDF_LIVE ? "ไม่จำกัด · ไม่มีลายน้ำ" : "เร็วๆ นี้"}</td><td>{PDF_LIVE ? "ตามข้อตกลง" : "เร็วๆ นี้"}</td></tr>
              <tr><th>API / Raw export / Data integration</th><td>—</td><td>—</td><td>ปรับตาม scope ขององค์กร</td></tr>
            </tbody>
          </table>
        </div>
        <p className={styles.tableNote}>Enterprise เป็นแพ็กเกจแบบปรับตามการใช้งานจริงของแต่ละองค์กร ไม่มีราคาและจำนวนที่นั่งตายตัวบนหน้าเว็บ</p>
      </section>
    </main>
  );
}
