import Link from "next/link";
import { getEvents } from "@/lib/data";
import { getCanonicalBrands, getCanonicalModels } from "@/lib/canonical-data";
import { displayName } from "@/lib/display-name";

export const dynamic = "force-dynamic";

/** Point this at the member site once it is live. While it is empty the
 *  buttons fall back to the contact block instead of inventing a URL. */
const MEMBER_SITE = "";

/** Every label on this page is real: model names come out of the catalog and
 *  counts are computed from it. Nothing is mocked up — where a number is for
 *  subscribers, the page says so in words rather than showing a fake of it. */
const QUESTIONS: { scope: string; question: string; pick: (r: any) => boolean }[] = [
  { scope: "กระบะ · Double Cab", question: "ยอดจดทะเบียนกระบะรายรุ่นและส่วนแบ่งตลาด", pick: (r) => r.body_type === "PICKUP" },
  { scope: "PPV พื้นฐานกระบะ", question: "การเปลี่ยนแปลงส่วนแบ่งตลาดกลุ่ม PPV", pick: (r) => r.body_type === "PPV" },
  { scope: "รถไฟฟ้า BEV", question: "ยอดจดทะเบียนรถไฟฟ้ารายรุ่น", pick: (r) => (r.powertrains || []).includes("BEV") },
  { scope: "ไฮบริด HEV", question: "สัดส่วนไฮบริดเทียบเครื่องยนต์สันดาป แยกตามเซกเมนต์", pick: (r) => (r.powertrains || []).includes("HEV") },
  { scope: "ครอสโอเวอร์", question: "อัตราการเติบโตของครอสโอเวอร์รายรุ่น", pick: (r) => r.body_type === "CROSSOVER" },
  { scope: "ประกอบไทย เทียบ นำเข้า", question: "สัดส่วนรถประกอบในไทยเทียบรถนำเข้า", pick: (r) => r.production_type === "CKD" || r.production_type === "SKD" },
];

/** What the member view actually contains, stated plainly.
 *
 *  This used to be a blurred bar-chart texture. A blurred chart says "there is
 *  nothing here" far more loudly than it says "there is something worth paying
 *  for", and it is a picture of data we do not have on this page. A list of the
 *  cuts that exist is both honest and more persuasive. */
function MemberScope({ items }: { items: readonly string[] }) {
  return (
    <ul className="sfScopeList">
      {items.map((item) => <li key={item}>{item}</li>)}
    </ul>
  );
}

const MONTHLY_CUTS = [
  "ยอดจดทะเบียนรายเดือน ย้อนหลังถึง 2565",
  "ส่วนแบ่งตลาดรายแบรนด์และรายรุ่น",
  "แยกตามเซกเมนต์ ช่วงราคา และประเทศที่ผลิต",
  "เปรียบเทียบเดือนต่อเดือนและปีต่อปี",
] as const;

export default async function ReportsPage() {
  const [brands, events, models] = await Promise.all([getCanonicalBrands(250), getEvents(6), getCanonicalModels(600)]);
  const current = (models as any[]).filter((r) => r.status !== "discontinued");
  const assembled = current.filter((r) => r.production_type === "CKD" || r.production_type === "SKD").length;

  const cta = MEMBER_SITE || "#tdr-contact";
  const ctaLabel = MEMBER_SITE ? "เข้าสู่ TDR Report ↗" : "ดูรายละเอียดแพ็กเกจ";

  const cards = QUESTIONS.map((q) => {
    const hits = current.filter(q.pick);
    return { ...q, names: hits.slice(0, 5).map((r: any) => [displayName(r.brands), displayName(r)].filter(Boolean).join(" ")), total: hits.length };
  }).filter((c) => c.total >= 2); // "เทียบ 1 รุ่น" is not a question worth pitching

  return <>
    <section className="sfPitchHero">
      <div>
        <div className="sfEyebrow">TDR REPORT · สำหรับสมาชิก</div>
        <h1>ยอดจดทะเบียนรถยนต์ในประเทศไทย</h1>
        <p>ข้อมูลรถ โรงงาน และการผลิตบนเว็บนี้เปิดให้ดูฟรีทั้งหมด ส่วนข้อมูลยอดจดทะเบียนและส่วนแบ่งตลาดอยู่ใน TDR Report</p>
        <div className="sfPitchActions">
          <Link className="sfBtn" href={cta}>{ctaLabel}</Link>
          <Link className="sfBtnGhost" href="#tdr-compare">เปรียบเทียบแพ็กเกจ</Link>
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
          <MemberScope items={MONTHLY_CUTS} />
          <div className="sfPanelOverlay">
            <strong>ดูตัวเลขได้เมื่อเข้าสู่ระบบ</strong>
            <Link className="sfBtn" href={cta}>{ctaLabel}</Link>
          </div>
        </div>
      </div>
    </section>

    <div className="sfStrip sfBleed">
      <div className="sfStripItem"><b className="sfNum">{current.length.toLocaleString()}</b><span>รุ่นในฐานข้อมูล</span></div>
      <div className="sfStripItem"><b className="sfNum">{brands.length.toLocaleString()}</b><span>แบรนด์</span></div>
      <div className="sfStripItem"><b className="sfNum">{assembled.toLocaleString()}</b><span>ประกอบในไทย</span></div>
      <div className="sfStripItem"><b className="sfNum">สมาชิก</b><span>ข้อมูลจดทะเบียน</span></div>
      <div className="sfStripNote">ข้อมูลยอดจดทะเบียนเข้าถึงได้ผ่านสิทธิ์สมาชิกเท่านั้น</div>
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
        <div><div className="sfEyebrow">ขอบเขตข้อมูล</div><h2>คำถามที่ฐานข้อมูลนี้ตอบได้</h2></div>
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
            <p className="sfQScope">
              เทียบ <b className="sfNum">{c.total}</b> รุ่นในฐานข้อมูล · {c.names.join(", ")}{c.total > c.names.length ? ` +${c.total - c.names.length}` : ""}
            </p>
          </article>
        ))}
      </div>
      <p className="sfQFoot">ชื่อรุ่นและจำนวนด้านบนเป็นข้อมูลจริงจากแคตตาล็อก TDR ส่วนตัวเลขยอดจดทะเบียนและส่วนแบ่งตลาดอยู่ในชุดข้อมูลสำหรับสมาชิก</p>
    </section>

    <section className="sfBlock" id="tdr-compare">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow ink">แพ็กเกจ</div><h2>ขอบเขตของแต่ละแพ็กเกจ</h2></div>
      </div>
      <table className="sfCompare">
        <thead>
          <tr><th>สิ่งที่ได้</th><th>ฟรี</th><th>สมาชิก</th></tr>
        </thead>
        <tbody>
          {[
            [`แคตตาล็อกรถ ${current.length.toLocaleString()} รุ่น · สเปก ราคา รุ่นย่อย`, true, true],
            ["บริบทการผลิตไทยที่ผูกกับหน้ารถ", true, true],
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
        <h2>เข้าถึงข้อมูล</h2>
        <p>{MEMBER_SITE ? "เข้าใช้งานได้ที่ TDR Report" : "ระบบสมาชิกยังไม่เปิดให้บริการ"}</p>
      </div>
      <div className="sfPitchFootActions">
        {MEMBER_SITE ? <Link className="sfBtn" href={MEMBER_SITE}>เข้าสู่ TDR Report ↗</Link> : <span className="sfBtn sfBtnDisabled">ยังไม่เปิดให้บริการ</span>}
        <Link className="sfBtnGhost" href="/models">ดูข้อมูลที่เปิดฟรีก่อน</Link>
      </div>
    </section>
  </>;
}
