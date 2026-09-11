import Link from "next/link";
import { getPriceCoverageWorklist } from "@/lib/price-coverage-worklist";
import { adminDb } from "@/lib/supabase";

function n(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("th-TH") : "—";
}
function pct(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : "—";
}
function money(min: number | null, max: number | null) {
  if (min == null || max == null) return "—";
  return min === max ? `${n(min)} ฿` : `${n(min)}–${n(max)} ฿`;
}

export default async function PriceCoveragePage() {
  const db = adminDb();
  if (!db) {
    return <div className="adminEditor"><div className="adminNotice">Admin database is not configured.</div></div>;
  }
  const work = await getPriceCoverageWorklist(db, 100);
  const periodLabel = work.periods.length ? work.periods.join(" · ") : "no settled registration window";

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>ADMIN BENCH · PRICE COVERAGE WORKLIST</small>
        <h1>เติม Verified LIST_PRICE ตาม Market Impact</h1>
        <p>เรียงรุ่นที่ยังขาด canonical LIST_PRICE ด้วยยอดจดทะเบียน 3 เดือนล่าสุดที่ settle แล้ว. Seed price ใช้เป็น hint สำหรับตรวจ source เท่านั้น — ไม่ใช่ authority และไม่ถูกเอาไปทำ paid cohort.</p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/prices">เปิด Price Ledger ↗</Link>
    </div>

    <div className="adminStatGrid">
      <div className="adminStat"><span>Model coverage</span><strong>{pct(work.modelCoveragePct)}</strong><small>{n(work.readyModels)} / {n(work.canonicalModels)} canonical models ready</small></div>
      <div className="adminStat"><span>3M registration coverage</span><strong>{pct(work.registrationCoveragePct3m)}</strong><small>{n(work.readyRegistrations3m)} / {n(work.mappedRegistrations3m)} mapped units</small></div>
      <div className="adminStat"><span>Models with MarketTrim</span><strong>{n(work.modelsWithTrims)}</strong><small>price cohort requires every active trim priced</small></div>
      <div className="adminStat"><span>Priority window</span><strong>{work.periods.length} เดือน</strong><small>{periodLabel}</small></div>
    </div>

    <div className="adminNotice">
      <b>Definition of ready</b>
      <span>รุ่นหนึ่งจะนับว่าพร้อมต่อเมื่อ active MarketTrim ทุกตัวมี verified current LIST_PRICE. รุ่นที่มีราคาเพียงบาง trim ยังเป็น UNKNOWN; รุ่นที่ครบแต่ข้ามหลาย price band จะเป็น MIXED. Paid Price Range ยัง fail-closed จน verified model coverage ถึง 80%.</span>
    </div>

    <div className="adminNotice">
      <b>Source bottleneck</b>
      <span>คอลัมน์ OEM target มาจาก Price Intelligence target registry ปัจจุบัน. 0 หมายถึงยังไม่มี model-specific first-party target ที่ harvester รู้จัก; ไม่ได้แปลว่าเว็บ OEM ไม่มีข้อมูล. เพิ่ม target/source ก่อนพยายาม automate promotion.</span>
    </div>

    <div className="libraryTable"><table>
      <thead><tr><th>#</th><th>Brand / Model</th><th>3M regs</th><th>Market share</th><th>Verified trims</th><th>Missing</th><th>UNVERIFIED seed hint</th><th>OEM target</th><th>Action</th></tr></thead>
      <tbody>{work.items.map((row, index) => <tr key={row.canonicalModelId}>
        <td>{index + 1}</td>
        <td><b>{row.brand} {row.model}</b><br/><small>{row.canonicalModelId}</small></td>
        <td>{n(row.registrations3m)}</td>
        <td>{pct(row.registrationSharePct)}</td>
        <td>{row.pricedTrims} / {row.totalTrims}</td>
        <td><b>{row.missingTrims}</b></td>
        <td>{money(row.seedMinThb, row.seedMaxThb)}<br/><small>{row.seedHintCount ? `${row.seedHintCount} seed values · HINT ONLY` : "no seed hint"}</small></td>
        <td>{row.oemTargetCount ? <b>{row.oemTargetCount}</b> : <span>0</span>}</td>
        <td><Link href={`/admin/prices?q=${encodeURIComponent(`${row.brand} ${row.model}`)}`}>เปิด trims ↗</Link></td>
      </tr>)}</tbody>
    </table></div>

    {!work.items.length ? <div className="adminNotice"><span>ไม่มีรุ่นที่ขาดราคาใน current MarketTrim set.</span></div> : null}
  </div>;
}
