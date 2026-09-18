"use client";

import Link from "next/link";
import { useEffect } from "react";
import { FEATURES, TIER_POLICIES } from "@/lib/access-policy";
import styles from "./pricing.module.css";

function track(event: "upgrade_viewed" | "corporate_cta_clicked") {
  fetch("/api/telemetry", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  }).catch(() => {});
}

// Research/PDF are scaffolded, not live -- see lib/access-policy.ts's
// FEATURES registry (research_reports / pdf_export_reports, both
// `released: false` today). Reading the flag here means this copy updates
// itself automatically once a real implementation ships, instead of
// silently drifting out of sync with what the product actually does.
const RESEARCH_LIVE = FEATURES.research_reports.released;
const PDF_LIVE = FEATURES.pdf_export_reports.released;
function researchCopy(liveCopy: string) {
  return RESEARCH_LIVE ? liveCopy : "Research — เร็วๆ นี้ (อยู่ระหว่างพัฒนา)";
}
// Free's real, decided limit -- see lib/access-policy.ts's
// TIER_POLICIES.FREE.researchFullMonthlyLimit -- rather than a copy of the
// number that can drift from it.
const FREE_RESEARCH_LIMIT = TIER_POLICIES.FREE.researchFullMonthlyLimit;
function pdfCopy(liveCopy: string) {
  return PDF_LIVE ? liveCopy : "PDF export — เร็วๆ นี้ (อยู่ระหว่างพัฒนา)";
}

// Provincial Registration: same pattern -- reads the ladder from
// lib/access-policy.ts's FEATURES registry rather than hardcoding tier
// copy here, so this stays in sync automatically if the ladder or the
// release flag ever changes. `released` is false today, so every tier
// shows "(Coming Soon)"; the ladder LABEL still communicates where this
// is headed (Free teaser / Individual limited / Pro full / Corporate
// tailored) without pretending any of it is live. Individual's "limited"
// deliberately has no number attached -- that policy isn't decided yet
// (see FEATURES.provincial_registration.limitedAccessPolicyDefined and
// releaseSafetyViolations(), which refuses to let this feature ship
// released while that stays undefined).
const PROVINCIAL_LIVE = FEATURES.provincial_registration.released;
const PROVINCIAL_LADDER = FEATURES.provincial_registration.stateByAudience;
const PROVINCIAL_STATE_LABEL: Record<string, string> = {
  unavailable: "—",
  teaser: "Teaser",
  limited: "Limited (รายละเอียดยังไม่กำหนด)",
  full: "Full",
  tailored: "Tailored",
};
function provincialCopy(audience: keyof typeof PROVINCIAL_LADDER) {
  const label = PROVINCIAL_STATE_LABEL[PROVINCIAL_LADDER[audience]];
  return PROVINCIAL_LIVE
    ? `Provincial Registration — ${label}`
    : `Provincial Registration — ${label} (Coming Soon)`;
}

// Corporate contact is configuration-driven, never a guessed address.
// Set NEXT_PUBLIC_TDR_CORPORATE_CONTACT_URL (a mailto: link or a contact
// page URL) to enable the CTA; until it's set the button fails visibly
// (disabled, with an explanatory label) instead of silently pointing
// somewhere nobody confirmed.
const CORPORATE_CONTACT_URL = process.env.NEXT_PUBLIC_TDR_CORPORATE_CONTACT_URL || "";

export default function PricingPage() {
  useEffect(() => { track("upgrade_viewed"); }, []);

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.eyebrow}>TDR REPORT · แพ็กเกจ</div>
        <h1>เลือกแพ็กเกจที่ตรงกับการใช้งาน</h1>
        <p>ข้อมูลรถ ราคา และสเปก เปิดให้ดูฟรีเสมอ แพ็กเกจด้านล่างคือสิทธิ์ใช้เครื่องมือวิเคราะห์</p>
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
            <li>{RESEARCH_LIVE ? "✓" : "○"} {researchCopy(`Research ฉบับเต็ม — ${FREE_RESEARCH_LIMIT} ชิ้น/เดือน`)}</li>
            <li>{PDF_LIVE ? "✓" : "○"} {pdfCopy("PDF export — 1 ครั้ง/เดือน (มีลายน้ำ TDR Free)")}</li>
            <li>{PROVINCIAL_LIVE ? "✓" : "○"} {provincialCopy("FREE")}</li>
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
            <li>{RESEARCH_LIVE ? "✓" : "○"} {researchCopy("Research ฉบับเต็ม — 3 ชิ้น/เดือน")}</li>
            <li>{PDF_LIVE ? "✓" : "○"} {pdfCopy("PDF export — 10 ครั้ง/เดือน")}</li>
            <li>{PROVINCIAL_LIVE ? "✓" : "○"} {provincialCopy("INDIVIDUAL")}</li>
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
            <li>{RESEARCH_LIVE ? "✓" : "○"} {researchCopy("Research ฉบับเต็ม — ไม่จำกัด")}</li>
            <li>{PDF_LIVE ? "✓" : "○"} {pdfCopy("PDF export — ไม่จำกัด")}</li>
            <li>{PROVINCIAL_LIVE ? "✓" : "○"} {provincialCopy("PRO")}</li>
            <li>— ไม่มี API สำหรับดึงข้อมูลดิบ (สงวนไว้สำหรับ Corporate)</li>
          </ul>
          <Link className={styles.cta} href="/member/billing">สมัคร Pro</Link>
        </article>
      </section>

      <section className={styles.corporate}>
        <div>
          <div className={styles.eyebrow} style={{ color: "#bbb" }}>CORPORATE</div>
          <h2>สำหรับองค์กร</h2>
          <p>ขอบเขตและราคาปรับตามการใช้งานจริงของแต่ละทีม</p>
          <ul>
            <li>· Team access หลายที่นั่ง</li>
            <li>· Workflow ที่ปรับให้เข้ากับทีมคุณ</li>
            <li>· API/data integration แบบมีขอบเขต (ไม่ใช่ raw data ทั้งชุด)</li>
            <li>· Research support และรายงานที่ปรับแต่งได้</li>
            <li>· {provincialCopy("CORPORATE")}</li>
          </ul>
        </div>
        {CORPORATE_CONTACT_URL ? (
          <a
            className={styles.corporateCta}
            href={CORPORATE_CONTACT_URL}
            onClick={() => track("corporate_cta_clicked")}
          >
            Talk to TDR →
          </a>
        ) : (
          <span className={styles.corporateCta} style={{ opacity: 0.6, cursor: "not-allowed" }} aria-disabled="true">
            ช่องทางติดต่อ Corporate ยังไม่ได้ตั้งค่า
          </span>
        )}
      </section>
    </main>
  );
}
