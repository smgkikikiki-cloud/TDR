import Link from "next/link";
import { notFound } from "next/navigation";
import { groupedNumber } from "@/components/charts/format";
import { adminDb } from "@/lib/supabase";
import { fetchIceRegTrend, latestIcePeriod } from "@/lib/ice-market-data";
import { sliceIceByModel } from "@/lib/ice-market-engine";
import { resolveMarketWindow } from "@/lib/registration-market";

export const dynamic = "force-dynamic";

/**
 * R6/R8 Preview-only smoke test: real Ice model-group labels and exact
 * registrations on a rendered web page, with no crosswalk dependency.
 *
 * This is intentionally NOT the TDR-paid model comparison product.
 * Do not enable on production or imply owner-approved canonical mapping.
 */
export default async function IceModelPreviewPage() {
  if (process.env.VERCEL_ENV !== "preview") notFound();
  const db = adminDb();
  if (!db) throw new Error("Ice model preview requires server DB credentials");
  const period = await latestIcePeriod(db);
  if (!period) return <main className="marketPage"><h1>ไม่มีงวดทะเบียน Ice ที่พร้อมแสดง</h1></main>;

  const facts = await fetchIceRegTrend(db, resolveMarketWindow(period, "month"));
  // Ice is authoritative for the group labels: model data does not depend
  // on the still-unapproved TDR canonical Crosswalk. Empty Crosswalk by design.
  const ranked = sliceIceByModel(facts, [], {}, 100);
  const total = facts.reduce((sum, fact) => sum + Number(fact.reg_count), 0);
  if (!ranked.length || ranked[0].market_total !== total) {
    throw new Error("Ice model preview failed source registration total QA");
  }
  const rawGroups = new Set(facts.map(f => f.model_group_id)).size;
  const visibleSum = ranked.reduce((sum, row) => sum + Number(row.registrations), 0);

  return <main className="marketPage">
    <section className="sfPageHead">
      <div>
        <div className="sfEyebrow">Ice · ตรวจสอบรายรุ่นบน Preview เท่านั้น</div>
        <h1>ยอดจดทะเบียนตามชื่อรุ่นจาก Ice</h1>
      </div>
      <div className="sfPageHeadAside">
        <div className="sfEyebrow ink">งวดล่าสุด {period}</div>
        <b className="sfNum">{groupedNumber(total)}</b>
        <span>คัน · {groupedNumber(rawGroups)} กลุ่มรุ่น</span>
      </div>
    </section>
    <section className="marketTableWrap" aria-label="อันดับรุ่นรถจากไฟล์ทะเบียน Ice">
      <table className="marketTable">
        <thead><tr><th>#</th><th>ชื่อรุ่นรถจาก Ice</th><th>ยอดจดทะเบียน</th><th>ส่วนแบ่ง</th></tr></thead>
        <tbody>
          {ranked.map((r, i) => <tr key={r.entity_key}>
            <td>{i + 1}</td>
            <td><b>{r.entity_label}</b></td>
            <td>{groupedNumber(Number(r.registrations))}</td>
            <td>{groupedNumber(Number(r.market_share_pct), 2)}%</td>
          </tr>)}
        </tbody>
      </table>
    </section>
    <p className="marketNote">
      แสดง {ranked.length} กลุ่มรุ่นจาก {rawGroups} กลุ่ม รวม {groupedNumber(visibleSum)} คันในตาราง
      จากยอดทั้งหมด {groupedNumber(total)} คัน — ไม่ตัดหรือคูณทะเบียนซ้ำ
      ชื่อรุ่นเป็นกลุ่มรุ่นตามข้อมูล Ice ไม่ใช่การจับคู่ที่ TDR อนุมัติแล้ว
      หน้านี้สำหรับ QA ใน Vercel Preview เท่านั้น ไม่ใช่หน้า Pro หรือ Production
    </p>
    <section className="marketMore"><Link className="sfBtn" href="/market">กลับสรุปยอดแบรนด์</Link></section>
  </main>;
}
