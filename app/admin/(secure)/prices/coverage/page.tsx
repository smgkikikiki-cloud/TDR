import Link from "next/link";
import { getEcoTrimCandidateGroups } from "@/lib/eco-trim-snapshot";
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
  const ecoGroupsByModel = new Map<string, number>();
  for (const group of getEcoTrimCandidateGroups()) {
    ecoGroupsByModel.set(group.modelId, (ecoGroupsByModel.get(group.modelId) || 0) + 1);
  }

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>ADMIN BENCH · PRICE COVERAGE WORKLIST</small>
        <h1>เติม MarketTrim + Verified LIST_PRICE ตาม Market Impact</h1>
        <p>เรียง canonical models ที่ยังเข้า Price Range ไม่ได้ด้วยยอดจดทะเบียน 3 เดือนล่าสุดที่ settle แล้ว. แยก identity blocker, actionable price gap และ price gap ที่ HUMAN review แล้วแต่หลักฐานตลาดยังไม่ publishable.</p>
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
      <b>Two blockers, three work states</b>
      <span><b>NO_MARKET_TRIM</b> = review ECO identity ก่อนเมื่อ snapshot มี candidate. <b>MISSING_LIST_PRICE</b> = เติม verified price เมื่อมี evidence. ถ้า reviewer ตรวจแล้วแต่ OEM ยังไม่ประกาศ final LIST_PRICE หรือ evidence ขัดกัน ให้ <b>defer</b> trim นั้นเพื่อเอาออกจากกอง actionable โดยไม่เปลี่ยน canonical fact.</span>
    </div>

    <div className="adminNotice">
      <b>Deferred ≠ ready</b>
      <span>Deferred trim ยังถูกนับเป็น missing LIST_PRICE เต็ม ๆ และยังบล็อก model readiness / Paid Price Range เหมือนเดิม. มันมีผลแค่ไม่ให้ reviewer วนทำงานซ้ำกับตลาดที่ยังไม่มีคำตอบจริง. Paid Price Range ยัง fail-closed จน verified model coverage ถึง 80%.</span>
    </div>

    <div className="adminNotice">
      <b>Source + seed boundary</b>
      <span>OEM target มาจาก Price Intelligence target registry. ECO candidate ใช้ยืนยัน identity เท่านั้น. Seed price ใน catalog เป็น <b>UNVERIFIED HINT</b> สำหรับช่วย reviewer หาเอกสาร — ทั้งหมดนี้ไม่ใช่ price authority จนกว่าจะเข้า canonical PriceLedger เป็น verified LIST_PRICE.</span>
    </div>

    <div className="libraryTable"><table>
      <thead><tr><th>#</th><th>Brand / Model</th><th>Blocker</th><th>3M regs</th><th>Market share</th><th>Verified trims</th><th>Missing / deferred</th><th>UNVERIFIED seed hint</th><th>OEM target</th><th>Action</th></tr></thead>
      <tbody>{work.items.map((row, index) => {
        const ecoCandidateGroups = ecoGroupsByModel.get(row.canonicalModelId) || 0;
        return <tr key={row.canonicalModelId}>
          <td>{index + 1}</td>
          <td><b>{row.brand} {row.model}</b><br/><small>{row.canonicalModelId}</small></td>
          <td><b>{row.blocker}</b></td>
          <td>{n(row.registrations3m)}</td>
          <td>{pct(row.registrationSharePct)}</td>
          <td>{row.totalTrims ? `${row.pricedTrims} / ${row.totalTrims}` : "—"}</td>
          <td>{row.totalTrims ? <><b>{row.missingTrims}</b><br/><small>{row.deferredTrims ? `${row.deferredTrims} deferred · ${row.actionableMissingTrims} actionable` : `${row.actionableMissingTrims} actionable`}</small></> : "—"}</td>
          <td>{money(row.seedMinThb, row.seedMaxThb)}<br/><small>{row.seedHintCount ? `${row.seedHintCount} seed values · HINT ONLY` : "no seed hint"}</small></td>
          <td>{row.oemTargetCount ? <b>{row.oemTargetCount}</b> : <span>0</span>}</td>
          <td>{row.blocker === "NO_MARKET_TRIM"
            ? ecoCandidateGroups
              ? <><Link href={`/admin/eco-trims?model=${encodeURIComponent(row.canonicalModelId)}`}>Review ECO ({ecoCandidateGroups}) ↗</Link><br/><small><Link href="/admin/vehicle-input">Manual fallback</Link></small></>
              : <Link href="/admin/vehicle-input">Manual MarketTrim ↗</Link>
            : row.actionableMissingTrims > 0
              ? <Link href={`/admin/vehicle-input?model=${encodeURIComponent(row.canonicalModelId)}`}>เติม LIST_PRICE ({row.actionableMissingTrims}) ↗</Link>
              : <Link href={`/admin/vehicle-input?model=${encodeURIComponent(row.canonicalModelId)}`}>Review deferred ({row.deferredTrims}) ↗</Link>}</td>
        </tr>;
      })}</tbody>
    </table></div>

    {!work.items.length ? <div className="adminNotice"><span>ทุก canonical model พร้อมสำหรับ Price Range แล้ว.</span></div> : null}
  </div>;
}
