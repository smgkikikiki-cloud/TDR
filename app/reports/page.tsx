import Link from "next/link";
import { getBrands, getEvents, getModels } from "@/lib/data";
import { publicDb } from "@/lib/supabase";

export const dynamic = "force-dynamic";

/** Point this at the member site once it is live. While it is empty the
 *  buttons fall back to the contact block instead of inventing a URL. */
const MEMBER_SITE = "";

/** The pitch. Every label on this page is real — model names come out of the
 *  catalog, counts are computed from it. Only values a subscriber pays for are
 *  hidden, and what sits behind the blur is "••" and abstract shapes, never a
 *  fabricated number: the blur is a curtain, not a security boundary. */
const QUESTIONS: { scope: string; question: string; pick: (r: any) => boolean }[] = [
  { scope: "กระบะ · Double Cab", question: "เดือนที่แล้วกระบะรุ่นไหนขายนำ และทิ้งห่างรุ่นรองเท่าไหร่", pick: (r) => r.body_type === "Pickup truck" },
  { scope: "SUV โครงกระบะ (PPV)", question: "PPV รุ่นไหนกำลังกินส่วนแบ่งของรุ่นอื่นอยู่", pick: (r) => r.body_type === "SUV (Ladder frame)" },
  { scope: "รถไฟฟ้า BEV", question: "รถไฟฟ้ารุ่นไหนขายได้จริง รุ่นไหนแค่เปิดตัวแล้วเงียบ", pick: (r) => (r.powertrains || []).includes("BEV") },
  { scope: "ไฮบริด HEV", question: "ไฮบริดแซงเครื่องยนต์สันดาปในเซกเมนต์ไหนไปแล้วบ้าง", pick: (r) => (r.powertrains || []).includes("HEV") },
  { scope: "ครอสโอเวอร์", question: "ครอสโอเวอร์รุ่นไหนโตเร็วที่สุดใน 6 เดือนล่าสุด", pick: (r) => r.body_type === "Crossover" },
  { scope: "ประกอบไทย เทียบ นำเข้า", question: "รุ่นที่ประกอบในไทยเสียส่วนแบ่งให้รถนำเข้าไปเท่าไหร่", pick: (r) => r.production_type === "CKD" || r.production_type === "SKD" },
];

/** A chart-shaped texture. No label is attached to any bar, so it states
 *  nothing — it only shows that a chart lives here. */
function BlurChart({ tall }: { tall?: boolean }) {
  const bars = tall ? [92, 74, 61, 48, 39, 27, 19] : [88, 66, 51, 34, 22];
  return (
    <div className={tall ? "sfBlurChart tall" : "sfBlurChart"} aria-hidden="true">
      {bars.map((w, i) => <span key={i}><i style={{ width: `${w}%` }} /><em>••</em></span>)}
    </div>
  );
}

export default async function ReportsPage() {
  const [brands, events, models] = await Promise.all([getBrands(250), getEvents(6), getModels(600)]);
  const current = (models as any[]).filter((r) => r.status !== "discontinued");
  const assembled = current.filter((r) => r.production_type === "CKD" || r.production_type === "SKD").length;

  // Registration coverage, read straight from the table so the page never
  // claims history it does not hold.
  const db = publicDb();
  const [firstReg, lastReg] = db ? await Promise.all([
    db.from("registrations").select("period").order("period", { ascending: true }).limit(1),
    db.from("registrations").select("period").order("period", { ascending: false }).limit(1),
  ]) : [null, null];
  const regFrom = firstReg?.data?.[0]?.period ?? null;
  const regTo = lastReg?.data?.[0]?.period ?? null;

  const cta = MEMBER_SITE || "#tdr-contact";
  const ctaLabel = MEMBER_SITE ? "เข้าสู่ TDR Report ↗" : "ขอเข้าถึงข้อมูลชุดเต็ม";

  const cards = QUESTIONS.map((q) => {
    const hits = current.filter(q.pick);
    return { ...q, names: hits.slice(0, 5).map((r: any) => [r.brands?.name_th, r.name_th].filter(Boolean).join(" ")), total: hits.length };
  }).filter((c) => c.total >= 2); // "เทียบ 1 รุ่น" is not a question worth pitching

  return <>
    <section className="sfPitchHero">
      <div>
        <div className="sfEyebrow">TDR REPORT · สำหรับสมาชิก</div>
        <h1>ยอดจดทะเบียนรถไทย ลึกถึงระดับรุ่นย่อย</h1>
        <p>ข้อมูลรถ โรงงาน และการผลิตบนเว็บนี้เปิดให้ดูฟรีทั้งหมด ส่วนตัวเลขตลาด — ใครขายได้เท่าไหร่ รุ่นย่อยไหนขายดี ส่วนแบ่งเปลี่ยนไปทางไหน — อยู่ใน TDR Report</p>
        <div className="sfPitchActions">
          <Link className="sfBtn" href={cta}>{ctaLabel}</Link>
          <Link className="sfBtnGhost" href="#tdr-compare">ฟรีกับสมาชิกต่างกันยังไง</Link>
        </div>
      </div>
      <div className="sfPitchPanel">
        <div className="sfPanelHead">
          <div>
            <div className="sfEyebrow">ตัวอย่างมุมมอง</div>
            <h2>ส่วนแบ่งตลาดรายรุ่น · รายเดือน</h2>
          </div>
          <span className="sfLockBadge">
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2.5" y="6" width="9" height="6" /><path d="M4.5 6V4a2.5 2.5 0 0 1 5 0v2" /></svg>
            สมาชิก
          </span>
        </div>
        <div className="sfPanelFade">
          <BlurChart tall />
          <div className="sfPanelOverlay">
            <strong>ตัวเลขจริงอยู่ใน TDR Report</strong>
            <Link className="sfBtn" href={cta}>{ctaLabel}</Link>
          </div>
        </div>
      </div>
    </section>

    <div className="sfStrip sfBleed">
      <div className="sfStripItem"><b className="sfNum">{current.length.toLocaleString()}</b><span>รุ่นในฐานข้อมูล</span></div>
      <div className="sfStripItem"><b className="sfNum">{brands.length.toLocaleString()}</b><span>แบรนด์</span></div>
      <div className="sfStripItem"><b className="sfNum">{assembled.toLocaleString()}</b><span>ประกอบในไทย</span></div>
      <div className="sfStripItem">
        {regFrom && regTo ? <><b className="sfNum">{regFrom} – {regTo}</b><span>ช่วงข้อมูลจดทะเบียน</span></>
          : <><b className="sfNum">กำลังนำเข้า</b><span>ข้อมูลจดทะเบียน</span></>}
      </div>
      <div className="sfStripNote">ตัวเลขชุดนี้นับจากฐานข้อมูล TDR โดยตรง ไม่ใช่ค่าประมาณ</div>
    </div>

    <section className="sfBlock">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow">อ่านได้ฟรี</div><h2>ข่าวอุตสาหกรรม</h2></div>
        <Link href="/news">ข่าวทั้งหมด →</Link>
      </div>
      {events.length ? (
        <div className="sfNewsList">
          {(events as any[]).slice(0, 5).map((e: any) => (
            <article key={e.id}>
              <time>{e.event_date}</time>
              <div><b>{e.title_th}</b>{e.summary_th || e.source_name ? <p>{e.summary_th || e.source_name}</p> : null}</div>
            </article>
          ))}
        </div>
      ) : <div className="sfEmpty"><b>ยังไม่มีข่าวในฐานข้อมูล</b><span>ข่าวที่เผยแพร่แล้วจะแสดงที่นี่</span></div>}
    </section>

    <section className="sfBlock">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow">คำถามที่ตอบได้เฉพาะสมาชิก</div><h2>คำถามที่ฐานข้อมูลนี้ตอบได้</h2></div>
        <span>{cards.length} มุมมอง</span>
      </div>
      <div className="sfQGrid">
        {cards.map((c) => (
          <article className="sfQCard" key={c.scope}>
            <div className="sfQTop">
              <span className="sfEyebrow">{c.scope}</span>
              <span className="sfLockBadge">
                <svg width="11" height="11" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2.5" y="6" width="9" height="6" /><path d="M4.5 6V4a2.5 2.5 0 0 1 5 0v2" /></svg>
                สมาชิก
              </span>
            </div>
            <h3>{c.question}</h3>
            <BlurChart />
            <p className="sfQScope">
              เทียบ <b className="sfNum">{c.total}</b> รุ่นในฐานข้อมูล · {c.names.join(", ")}{c.total > c.names.length ? ` +${c.total - c.names.length}` : ""}
            </p>
          </article>
        ))}
      </div>
      <p className="sfQFoot">ชื่อรุ่นและจำนวนด้านบนเป็นข้อมูลจริงจากแคตตาล็อก TDR ส่วนที่เบลอคือตัวเลขยอดจดทะเบียนและส่วนแบ่ง ซึ่งอยู่ในชุดข้อมูลสำหรับสมาชิก</p>
    </section>

    <section className="sfBlock" id="tdr-compare">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow ink">แพ็กเกจ</div><h2>ฟรี กับ สมาชิก ต่างกันยังไง</h2></div>
      </div>
      <table className="sfCompare">
        <thead>
          <tr><th>สิ่งที่ได้</th><th>ฟรี</th><th>สมาชิก</th></tr>
        </thead>
        <tbody>
          {[
            [`แคตตาล็อกรถ ${current.length.toLocaleString()} รุ่น · สเปก ราคา รุ่นย่อย`, true, true],
            ["โรงงานและรุ่นที่ผลิตในไทย", true, true],
            ["ข่าวอุตสาหกรรม", true, true],
            ["ยอดจดทะเบียนรายรุ่น รายเดือน", false, true],
            ["แยกถึงระดับรุ่นย่อย (trim)", false, true],
            ["ส่วนแบ่งตลาดและเทรนด์ย้อนหลัง", false, true],
            ["กราฟ interactive และ export ข้อมูล", false, true],
          ].map(([label, free, paid]) => (
            <tr key={label as string}>
              <td>{label as string}</td>
              <td>{free ? <span className="sfYes">✓</span> : <span className="sfNo">—</span>}</td>
              <td>{paid ? <span className="sfYes">✓</span> : <span className="sfNo">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>

    <section className="sfPitchFoot sfBleed" id="tdr-contact">
      <div>
        <div className="sfEyebrow">TDR REPORT</div>
        <h2>อยากเห็นตัวเลขจริง</h2>
        <p>{MEMBER_SITE ? "เข้าใช้งานได้ที่ TDR Report" : "ระบบสมาชิกกำลังเปิด ติดต่อทีม TDR เพื่อขอดูตัวอย่างข้อมูลชุดเต็มหรือสอบถามแพ็กเกจ"}</p>
      </div>
      <div className="sfPitchFootActions">
        {MEMBER_SITE ? <Link className="sfBtn" href={MEMBER_SITE}>เข้าสู่ TDR Report ↗</Link> : <span className="sfBtn sfBtnDisabled">ระบบสมาชิกกำลังเปิด</span>}
        <Link className="sfBtnGhost" href="/models">ดูข้อมูลที่เปิดฟรีก่อน</Link>
      </div>
    </section>
  </>;
}
