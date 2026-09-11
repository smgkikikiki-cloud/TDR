import { randomUUID } from "node:crypto";
import Link from "next/link";
import { enqueueModelRetailLifecycleReview } from "@/app/admin/retail-lifecycle-actions";
import { oemTargetsForModel } from "@/lib/price-evidence-registry";
import { getPriceCoverageWorklist } from "@/lib/price-coverage-worklist";
import { adminDb } from "@/lib/supabase";

function n(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("th-TH") : "—";
}

export default async function RetailLifecyclePage({
  searchParams,
}: {
  searchParams: Promise<{ model?: string; queued?: string }>;
}) {
  const query = await searchParams;
  const db = adminDb();
  if (!db) return <div className="adminEditor"><div className="adminNotice">Admin database is not configured.</div></div>;

  const work = await getPriceCoverageWorklist(db, 321);
  const unresolved = work.items.filter((row) => row.blocker === "UNRESOLVED_MODEL_LIFECYCLE");
  const requested = String(query.model || "").trim();
  const focused = unresolved.find((row) => row.canonicalModelId === requested) || unresolved[0] || null;
  const targets = focused ? oemTargetsForModel(focused.canonicalModelId) : [];
  const submittedAt = new Date().toISOString();
  const today = submittedAt.slice(0, 10);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · RETAIL LIFECYCLE REVIEW</small>
        <h1>พิสูจน์ก่อนว่า model ยังขายอยู่หรือเลิกขายแล้ว</h1>
        <p>Identity, ECO record, registration และ legacy editorial status ไม่ใช่ retail evidence. Review นี้เขียนกลับ canonical Model.retail_status/source/checked_at ผ่าน input queue เท่านั้น.</p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/prices/coverage">กลับ Price Coverage ↗</Link>
    </div>

    {query.queued ? <div className="adminSaved">รับ retail lifecycle review เข้าคิว canonical แล้ว</div> : null}

    <div className="adminStatGrid">
      <div className="adminStat"><span>Unverified models</span><strong>{n(work.unverifiedModels)}</strong><small>ยังบล็อก current-retail denominator</small></div>
      <div className="adminStat"><span>Current models</span><strong>{n(work.currentModels)}</strong><small>canonical retail evidence ผ่านแล้ว</small></div>
      <div className="adminStat"><span>Historical models</span><strong>{n(work.historicalModels)}</strong><small>ไม่อยู่ current-price denominator</small></div>
      <div className="adminStat"><span>Priority queue</span><strong>{n(unresolved.length)}</strong><small>เรียงตาม 3M registrations</small></div>
    </div>

    <div className="adminNotice">
      <b>Review rule</b>
      <span><b>CURRENT</b> ต้องมีหน้า official Thai OEM/distributor ที่แสดง model/line-up หรือหลักฐาน first-party ว่ายังสั่งซื้อได้. <b>HISTORICAL</b> ต้องมี first-party evidence ว่าถูกแทนที่/เลิกขาย หรือหลักฐานที่ตรวจสอบได้ชัดเจน. ทุก review เก็บ reviewer จาก session ฝั่ง server; browser ปลอม actor ไม่ได้.</span>
    </div>

    <div className="libraryTable"><table>
      <thead><tr><th>#</th><th>Model</th><th>3M regs</th><th>Trim state</th><th>OEM targets</th><th>Review</th></tr></thead>
      <tbody>{unresolved.map((row, index) => <tr key={row.canonicalModelId}>
        <td>{index + 1}</td>
        <td><b>{row.brand} {row.model}</b><br/><small>{row.canonicalModelId}</small></td>
        <td>{n(row.registrations3m)}<br/><small>{row.registrationSharePct.toFixed(2)}% mapped share</small></td>
        <td>{row.totalTrims ? <><b>{row.currentTrims} current</b><br/><small>{row.unverifiedTrims} unverified · {row.historicalTrims} historical</small></> : "no MarketTrim"}</td>
        <td>{row.oemTargetCount ? row.oemTargetCount : "0"}</td>
        <td><Link href={`/admin/retail-lifecycle?model=${encodeURIComponent(row.canonicalModelId)}`}>{focused?.canonicalModelId === row.canonicalModelId ? "Reviewing" : "Review"} ↗</Link></td>
      </tr>)}</tbody>
    </table></div>

    {focused ? <>
      <div className="adminHeader"><div><small>FOCUSED MODEL</small><h2>{focused.brand} {focused.model}</h2><p>{focused.canonicalModelId} · {n(focused.registrations3m)} registrations ใน priority window</p></div></div>

      {targets.length ? <div className="adminQuickGrid">{targets.map((target) => <a key={target.id} href={target.url} target="_blank" rel="noreferrer">
        <b>{target.sourceId}</b><span>{target.role} ↗</span><small>{target.notes || target.url}</small>
      </a>)}</div> : <div className="adminNotice"><span>Registry ยังไม่มี official OEM target สำหรับ model นี้ — ต้องหา first-party evidence เองก่อน review.</span></div>}

      <form action={enqueueModelRetailLifecycleReview} className="adminForm">
        <input type="hidden" name="submission_id" value={randomUUID()} />
        <input type="hidden" name="submitted_at" value={submittedAt} />
        <input type="hidden" name="model_id" value={focused.canonicalModelId} />
        <label className="adminField"><span>Retail status</span><select name="retail_status" required defaultValue="CURRENT">
          <option value="CURRENT">CURRENT — ยังขาย/สั่งซื้อได้</option>
          <option value="HISTORICAL">HISTORICAL — ไม่ใช่ current retail model แล้ว</option>
        </select></label>
        <label className="adminField"><span>Checked at</span><input name="reviewed_at" type="date" defaultValue={today} required /></label>
        <label className="adminField adminFieldWide"><span>Official evidence URL</span><input name="source_ref" type="url" placeholder="https://www.oem.co.th/model/..." required /></label>
        <label className="adminField adminFieldWide"><span>Review note</span><input name="reason" type="text" placeholder="Official Thailand model page lists this model in current line-up…" required /></label>
        <div className="adminFormActions"><button>Queue canonical lifecycle review</button></div>
      </form>
    </> : <div className="adminNotice"><span>ไม่มี model lifecycle debt ใน current worklist.</span></div>}
  </div>;
}
