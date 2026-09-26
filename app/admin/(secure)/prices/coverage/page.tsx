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
        <small>ADMIN BENCH · RETAIL + PRICE COVERAGE WORKLIST</small>
        <h1>ไล่หา Verified LIST_PRICE ตาม retail lifecycle ปัจจุบัน</h1>
        <p>เรียง canonical models ตามยอดจดทะเบียน 3 เดือนล่าสุด. Model/trim ทุกตัวถือว่าขายอยู่ (CURRENT) โดย default จนกว่าเจ้าของจะกด "เลิกขาย" เอง — ราคาที่ยังไม่มีคือ price debt ที่ต้องไล่หาต่อ ไม่ใช่ lifecycle ที่ต้องรอ verify ก่อน.</p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/prices">เปิด Price Ledger ↗</Link>
    </div>

    <div className="adminStatGrid">
      <div className="adminStat"><span>Price-ready retail models</span><strong>{pct(work.modelCoveragePct)}</strong><small>{n(work.readyModels)} / {n(work.retailRelevantModels)} CURRENT + UNVERIFIED models</small></div>
      <div className="adminStat"><span>3M registration coverage</span><strong>{pct(work.registrationCoveragePct3m)}</strong><small>{n(work.readyRegistrations3m)} / {n(work.mappedRegistrations3m)} retail-relevant mapped units</small></div>
      <div className="adminStat"><span>Model lifecycle</span><strong>{n(work.currentModels)} / {n(work.unverifiedModels)}</strong><small>CURRENT / UNVERIFIED · {n(work.historicalModels)} HISTORICAL</small></div>
      <div className="adminStat"><span>Models with MarketTrim</span><strong>{n(work.modelsWithTrims)}</strong><small>{n(work.modelsWithoutTrims)} models still have no trim identity</small></div>
      <div className="adminStat"><span>Priority window</span><strong>{work.periods.length} เดือน</strong><small>{periodLabel}</small></div>
    </div>

    <div className="adminNotice">
      <b>Four blockers in order</b>
      <span><b>UNRESOLVED_MODEL_LIFECYCLE</b> = serving release ผิด policy หรือยังไม่ publish. <b>NO_MARKET_TRIM</b> = model CURRENT แล้วแต่ยังไม่มี retail grade identity. <b>UNRESOLVED_TRIM_LIFECYCLE</b> = serving release ผิด policy หรือมี lifecycle state เก่าค้าง. <b>MISSING_LIST_PRICE</b> = current lineup ชัดแล้วและยังต้องเติม verified price.</span>
    </div>

    <div className="adminNotice">
      <b>CURRENT-by-default denominator</b>
      <span>HISTORICAL model/trim ถูกตัดออกจาก denominator เพราะเจ้าของกด "เลิกขาย" เองแล้ว (หรือ generation จบแล้ว). ทุก model/trim อื่นถือเป็น CURRENT โดย default แม้ยังไม่มีราคา — ราคาที่ยังหาไม่เจอนับเป็น price debt (MISSING_LIST_PRICE) ไม่ใช่ lifecycle block. HISTORICAL trim ไม่ต้องมี current LIST_PRICE.</span>
    </div>

    <div className="adminNotice">
      <b>Deferred ≠ ready</b>
      <span>Price defer จาก evidence conflict/รอ MSRP final ยังทำงานเหมือนเดิม แต่ใช้ได้เฉพาะ current trim เท่านั้น. Deferred trim ยังเป็น missing LIST_PRICE และยังบล็อก Paid Price Range.</span>
    </div>

    <div className="adminNotice">
      <b>Source boundary</b>
      <span>Identity จาก ECO/homologation evidence ก็เพียงพอให้ trim เป็น CURRENT โดย default แล้ว — ไม่ต้องรอ canonical LIST_PRICE หรือ evidence เพิ่มเติมมายืนยัน currentness อีก. สิ่งเดียวที่เปลี่ยนสถานะได้คือเจ้าของกด "เลิกขาย" เอง, generation ที่ ended แล้ว, หรือ HUMAN trim lifecycle review ที่บันทึกไว้ก่อนหน้า.</span>
    </div>

    <div className="libraryTable"><table>
      <thead><tr><th>#</th><th>Brand / Model</th><th>Blocker</th><th>3M regs</th><th>Market share</th><th>Trim lifecycle</th><th>Price coverage</th><th>UNVERIFIED seed hint</th><th>OEM target</th><th>Action</th></tr></thead>
      <tbody>{work.items.map((row, index) => {
        const ecoCandidateGroups = ecoGroupsByModel.get(row.canonicalModelId) || 0;
        return <tr key={row.canonicalModelId}>
          <td>{index + 1}</td>
          <td><b>{row.brand} {row.model}</b><br/><small>{row.canonicalModelId} · model {row.modelStatus}</small></td>
          <td><b>{row.blocker}</b></td>
          <td>{n(row.registrations3m)}</td>
          <td>{pct(row.registrationSharePct)}</td>
          <td>{row.totalTrims
            ? <><b>{row.currentTrims} current</b><br/><small>{row.unverifiedTrims} unverified · {row.historicalTrims} historical</small></>
            : "—"}</td>
          <td>{row.currentTrims
            ? <><b>{row.pricedTrims} / {row.currentTrims} current trims priced</b><br/><small>{row.missingTrims} missing · {row.deferredTrims} deferred · {row.actionableMissingTrims} actionable</small></>
            : "—"}</td>
          <td>{money(row.seedMinThb, row.seedMaxThb)}<br/><small>{row.seedHintCount ? `${row.seedHintCount} seed values · HINT ONLY` : "no seed hint"}</small></td>
          <td>{row.oemTargetCount ? <b>{row.oemTargetCount}</b> : <span>0</span>}</td>
          <td>{row.blocker === "UNRESOLVED_MODEL_LIFECYCLE"
            ? <Link href={`/admin/vehicles/${encodeURIComponent(row.canonicalModelId)}`}>Open Vehicle Editor ↗</Link>
            : row.blocker === "UNRESOLVED_TRIM_LIFECYCLE"
              ? <Link href={`/admin/vehicles/${encodeURIComponent(row.canonicalModelId)}`}>Open Vehicle Editor ↗</Link>
              : row.blocker === "NO_MARKET_TRIM"
                ? ecoCandidateGroups
                  ? <><Link href={`/admin/eco-trims?model=${encodeURIComponent(row.canonicalModelId)}`}>Review ECO ({ecoCandidateGroups}) ↗</Link><br/><small><Link href="/admin/vehicle-input">Manual fallback</Link></small></>
                  : <Link href="/admin/vehicle-input">Manual MarketTrim ↗</Link>
                : row.actionableMissingTrims > 0
                  ? <Link href={`/admin/vehicle-input?model=${encodeURIComponent(row.canonicalModelId)}`}>เติม LIST_PRICE ({row.actionableMissingTrims}) ↗</Link>
                  : <Link href={`/admin/vehicle-input?model=${encodeURIComponent(row.canonicalModelId)}`}>Review deferred ({row.deferredTrims}) ↗</Link>}</td>
        </tr>;
      })}</tbody>
    </table></div>

    {!work.items.length ? <div className="adminNotice"><span>ทุก retail-relevant canonical model พร้อมสำหรับ Price Range แล้ว.</span></div> : null}
  </div>;
}
