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
  const work = await getPriceCoverageWorklist(db, 150);
  const periodLabel = work.periods.length ? work.periods.join(" · ") : "no settled registration window";

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>ADMIN BENCH · PRICE COVERAGE WORKLIST</small>
        <h1>เติม MarketTrim + Verified LIST_PRICE ตาม Market Impact</h1>
        <p>เรียง canonical models ที่ยังเข้า Price Range ไม่ได้ด้วยยอดจดทะเบียน 3 เดือนล่าสุดที่ settle แล้ว. แยกชัดว่าตันที่ยังไม่มี MarketTrim identity หรือมี trims แล้วแต่ขาด verified LIST_PRICE.</p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/prices">เปิด Price Ledger ↗</Link>
    </div>

    <div className="adminStatGrid">
      <div className="adminStat"><span>Price-ready models</span><strong>{pct(work.modelCoveragePct)}</strong><small>{n(work.readyModels)} / {n(work.canonicalModels)} canonical models</small></div>
      <div className="adminStat"><span>3M registration coverage</span><strong>{pct(work.registrationCoveragePct3m)}</strong><small>{n(work.readyRegistrations3m)} / {n(work.mappedRegistrations3m)} mapped units</small></div>
      <div className="adminStat"><span>Models with MarketTrim</span><strong>{n(work.modelsWithTrims)}</strong><small>{n(work.modelsWithoutTrims)} models still have no trim identity</small></div>
      <div className="adminStat"><span>Priority window</span><strong>{work.periods.length} เดือน</strong><small>{periodLabel}</small></div>
    </div>

    <div className="adminNotice">
      <b>Two blockers, two fixes</b>
      <span><b>NO_MARKET_TRIM</b> = ต้องสร้าง canonical MarketTrim identity ก่อน จึงยังเพิ่ม trim-level PriceLedger ไม่ได้. <b>MISSING_LIST_PRICE</b> = identity พร้อมแล้ว ให้หา first-party/independent evidence และ append verified LIST_PRICE. ห้ามสร้าง trim หรือราคาเดาจากชื่อรุ่นเพื่อให้ coverage ดูดี.</span>
    </div>

    <div className="adminNotice">
      <b>Definition of ready</b>
      <span>รุ่นหนึ่งจะนับว่าพร้อมต่อเมื่อ active MarketTrim ทุกตัวมี verified current LIST_PRICE. รุ่นที่มีราคาเพียงบาง trim ยังเป็น UNKNOWN; รุ่นที่ครบแต่ข้ามหลาย price band จะเป็น MIXED. Paid Price Range ยัง fail-closed จน verified model coverage ถึง 80%.</span>
    </div>

    <div className="adminNotice">
      <b>Source + seed boundary</b>
      <span>OEM target มาจาก Price Intelligence target registry. Seed price ใน catalog เป็น <b>UNVERIFIED HINT</b> สำหรับช่วย reviewer หาเอกสารเท่านั้น — ไม่ใช่ authority, ไม่สร้าง MarketTrim และไม่ถูกเอาไปทำ paid cohort.</span>
    </div>

    <div className="libraryTable"><table>
      <thead><tr><th>#</th><th>Brand / Model</th><th>Blocker</th><th>3M regs</th><th>Market share</th><th>Verified trims</th><th>Missing price</th><th>UNVERIFIED seed hint</th><th>OEM target</th><th>Action</th></tr></thead>
      <tbody>{work.items.map((row, index) => <tr key={row.canonicalModelId}>
        <td>{index + 1}</td>
        <td><b>{row.brand} {row.model}</b><br/><small>{row.canonicalModelId}</small></td>
        <td><b>{row.blocker}</b></td>
        <td>{n(row.registrations3m)}</td>
        <td>{pct(row.registrationSharePct)}</td>
        <td>{row.totalTrims ? `${row.pricedTrims} / ${row.totalTrims}` : "—"}</td>
        <td><b>{row.totalTrims ? row.missingTrims : "—"}</b></td>
        <td>{money(row.seedMinThb, row.seedMaxThb)}<br/><small>{row.seedHintCount ? `${row.seedHintCount} seed values · HINT ONLY` : "no seed hint"}</small></td>
        <td>{row.oemTargetCount ? <b>{row.oemTargetCount}</b> : <span>0</span>}</td>
        <td>{row.blocker === "NO_MARKET_TRIM"
          ? <Link href="/admin/vehicle-input">เปิด Vehicle input ↗</Link>
          : <Link href={`/admin/prices?q=${encodeURIComponent(`${row.brand} ${row.model}`)}`}>เปิด trims ↗</Link>}</td>
      </tr>)}</tbody>
    </table></div>

    {!work.items.length ? <div className="adminNotice"><span>ทุก canonical model พร้อมสำหรับ Price Range แล้ว.</span></div> : null}
  </div>;
}
