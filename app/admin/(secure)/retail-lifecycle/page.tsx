import { randomUUID } from "node:crypto";
import Link from "next/link";
import { enqueueModelRetailLifecycleReview } from "@/app/admin/retail-lifecycle-actions";
import { enqueueTrimRetailLifecycleReview } from "@/app/admin/trim-retail-lifecycle-actions";
import { oemTargetsForModel } from "@/lib/price-evidence-registry";
import { getPriceCoverageWorklist } from "@/lib/price-coverage-worklist";
import { adminDb } from "@/lib/supabase";
import { trimRetailLifecycleDecisions } from "@/lib/trim-retail-lifecycle-review";

function n(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("th-TH") : "—";
}

export default async function RetailLifecyclePage({
  searchParams,
}: {
  searchParams: Promise<{ model?: string; evidence?: string; queued?: string; trimQueued?: string }>;
}) {
  const query = await searchParams;
  const db = adminDb();
  if (!db) return <div className="adminEditor"><div className="adminNotice">Admin database is not configured.</div></div>;

  const work = await getPriceCoverageWorklist(db, 321);
  const lifecycleDebt = work.items.filter((row) =>
    row.blocker === "UNRESOLVED_MODEL_LIFECYCLE" || row.blocker === "UNRESOLVED_TRIM_LIFECYCLE");
  const requested = String(query.model || "").trim();
  const focused = lifecycleDebt.find((row) => row.canonicalModelId === requested) || lifecycleDebt[0] || null;
  const targets = focused ? oemTargetsForModel(focused.canonicalModelId) : [];
  const selectedEvidenceId = String(query.evidence || "").trim();
  const selectedTarget = targets.find((target) => target.id === selectedEvidenceId) || null;
  const submittedAt = new Date().toISOString();
  const today = submittedAt.slice(0, 10);
  const trimReviews = trimRetailLifecycleDecisions();

  let focusedTrims: any[] = [];
  if (focused?.blocker === "UNRESOLVED_TRIM_LIFECYCLE") {
    const { data, error } = await db.from("current_market_trims")
      .select("canonical_id,model_id,name,status,current_list_price")
      .eq("model_id", focused.canonicalModelId)
      .order("name", { ascending: true }).limit(200);
    if (error) throw new Error(`trim lifecycle query failed: ${error.message}`);
    focusedTrims = data || [];
  }
  const unresolvedTrims = focusedTrims.filter((trim) => String(trim.status || "").toUpperCase() === "UNVERIFIED");

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · RETAIL LIFECYCLE REVIEW</small>
        <h1>พิสูจน์ current retail lineup ก่อนเปิด price work</h1>
        <p>Identity, ECO record, registration และ legacy editorial status ไม่ใช่ retail evidence. Model review เขียน canonical Model fields; trim review เป็น HUMAN sidecar ที่ release enrichment ใช้แยก CURRENT/HISTORICAL โดยไม่ปนกับ MarketTrim identity.</p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/prices/coverage">กลับ Price Coverage ↗</Link>
    </div>

    {query.queued ? <div className="adminSaved">รับ model lifecycle review เข้าคิว canonical แล้ว</div> : null}
    {query.trimQueued ? <div className="adminSaved">รับ trim lifecycle review เข้าคิว canonical แล้ว</div> : null}

    <div className="adminStatGrid">
      <div className="adminStat"><span>Unverified models</span><strong>{n(work.unverifiedModels)}</strong><small>ต้อง resolve ก่อน trim review</small></div>
      <div className="adminStat"><span>Current models</span><strong>{n(work.currentModels)}</strong><small>canonical retail evidence ผ่านแล้ว</small></div>
      <div className="adminStat"><span>Historical models</span><strong>{n(work.historicalModels)}</strong><small>ไม่อยู่ current-price denominator</small></div>
      <div className="adminStat"><span>Lifecycle debt</span><strong>{n(lifecycleDebt.length)}</strong><small>เรียงตาม 3M registrations</small></div>
    </div>

    <div className="adminNotice">
      <b>Review order</b>
      <span>1) resolve parent model เป็น CURRENT/HISTORICAL ก่อน 2) ถ้า model CURRENT จึง review grade identity ที่ยัง UNVERIFIED 3) เมื่อ current lineup ชัดแล้วจึงเปิด LIST_PRICE coverage. HUMAN trim review ชนะ open-ended price inference; parent model/generation HISTORICAL ชนะทุกอย่าง.</span>
    </div>

    <div className="libraryTable"><table>
      <thead><tr><th>#</th><th>Model</th><th>Blocker</th><th>3M regs</th><th>Trim state</th><th>OEM targets</th><th>Review</th></tr></thead>
      <tbody>{lifecycleDebt.map((row, index) => <tr key={row.canonicalModelId}>
        <td>{index + 1}</td>
        <td><b>{row.brand} {row.model}</b><br/><small>{row.canonicalModelId}</small></td>
        <td><b>{row.blocker}</b></td>
        <td>{n(row.registrations3m)}<br/><small>{row.registrationSharePct.toFixed(2)}% mapped share</small></td>
        <td>{row.totalTrims ? <><b>{row.currentTrims} current</b><br/><small>{row.unverifiedTrims} unverified · {row.historicalTrims} historical</small></> : "no MarketTrim"}</td>
        <td>{row.oemTargetCount ? row.oemTargetCount : "0"}</td>
        <td><Link href={`/admin/retail-lifecycle?model=${encodeURIComponent(row.canonicalModelId)}`}>{focused?.canonicalModelId === row.canonicalModelId ? "Reviewing" : "Review"} ↗</Link></td>
      </tr>)}</tbody>
    </table></div>

    {focused ? <>
      <div className="adminHeader"><div><small>FOCUSED MODEL</small><h2>{focused.brand} {focused.model}</h2><p>{focused.canonicalModelId} · {n(focused.registrations3m)} registrations ใน priority window</p></div></div>

      {targets.length ? <div className="adminQuickGrid">{targets.map((target) => <div key={target.id}>
        <b>{target.sourceId}</b><span>{target.role}</span><small>{target.notes || target.url}</small>
        <a href={target.url} target="_blank" rel="noreferrer">เปิด official source ↗</a>
        {focused.blocker === "UNRESOLVED_MODEL_LIFECYCLE" ? <Link href={`/admin/retail-lifecycle?model=${encodeURIComponent(focused.canonicalModelId)}&evidence=${encodeURIComponent(target.id)}`}>Use evidence →</Link> : null}
      </div>)}</div> : <div className="adminNotice"><span>Registry ยังไม่มี official OEM target สำหรับ model นี้ — ต้องหา first-party evidence เองก่อน review.</span></div>}

      {focused.blocker === "UNRESOLVED_MODEL_LIFECYCLE" ? <form action={enqueueModelRetailLifecycleReview} className="adminForm">
        <input type="hidden" name="submission_id" value={randomUUID()} />
        <input type="hidden" name="submitted_at" value={submittedAt} />
        <input type="hidden" name="model_id" value={focused.canonicalModelId} />
        {selectedTarget ? <input type="hidden" name="target_id" value={selectedTarget.id} /> : null}
        <label className="adminField"><span>Retail status</span><select name="retail_status" required defaultValue="CURRENT">
          <option value="CURRENT">CURRENT — ยังขาย/สั่งซื้อได้</option>
          <option value="HISTORICAL">HISTORICAL — ไม่ใช่ current retail model แล้ว</option>
        </select></label>
        <label className="adminField"><span>Checked at</span><input name="reviewed_at" type="date" defaultValue={today} required /></label>
        <label className="adminField adminFieldWide"><span>Official evidence URL</span><input name="source_ref" type="url" placeholder="https://www.oem.co.th/model/..." defaultValue={selectedTarget?.url || ""} readOnly={Boolean(selectedTarget)} required /></label>
        <label className="adminField adminFieldWide"><span>Review note</span><input name="reason" type="text" defaultValue={selectedTarget ? `Reviewed registered OEM target ${selectedTarget.sourceId} (${selectedTarget.role}). ${selectedTarget.notes}`.trim() : ""} placeholder="Official Thailand model page lists this model in current line-up…" required /></label>
        {selectedTarget ? <div className="adminNotice"><b>Registry-bound evidence</b><span>{selectedTarget.id} · server จะ resolve target นี้กับ {focused.canonicalModelId} ซ้ำและใช้ URL จาก registry แทน browser value.</span></div> : null}
        <div className="adminFormActions"><button>Queue canonical model lifecycle review</button></div>
      </form> : null}

      {focused.blocker === "UNRESOLVED_TRIM_LIFECYCLE" ? <>
        <div className="adminNotice"><b>Trim review</b><span>{n(unresolvedTrims.length)} grade identities ยัง UNVERIFIED. เลือกเฉพาะ grade ที่ evidence ชี้ว่าอยู่/ไม่อยู่ current Thai retail lineup; อย่าใช้ ECO existence เป็น CURRENT evidence.</span></div>
        <div className="libraryTable"><table>
          <thead><tr><th>MarketTrim</th><th>Serving status</th><th>Price evidence</th><th>Stored HUMAN review</th></tr></thead>
          <tbody>{focusedTrims.map((trim) => {
            const decision = trimReviews.get(String(trim.canonical_id || ""));
            const amount = Number(trim?.current_list_price?.amount_thb || 0);
            return <tr key={trim.canonical_id}>
              <td><b>{trim.name || trim.canonical_id}</b><br/><small>{trim.canonical_id}</small></td>
              <td>{String(trim.status || "UNVERIFIED").toUpperCase()}</td>
              <td>{amount > 0 ? `${n(amount)} ฿` : "—"}</td>
              <td>{decision ? <><b>{decision.status}</b><br/><small>{decision.reviewer} · {decision.reviewedAt}</small></> : "—"}</td>
            </tr>;
          })}</tbody>
        </table></div>

        {unresolvedTrims.length ? <form action={enqueueTrimRetailLifecycleReview} className="adminForm">
          <input type="hidden" name="submission_id" value={randomUUID()} />
          <input type="hidden" name="submitted_at" value={submittedAt} />
          <input type="hidden" name="model_id" value={focused.canonicalModelId} />
          <label className="adminField adminFieldWide"><span>MarketTrim</span><select name="trim_id" required defaultValue="">
            <option value="" disabled>เลือก grade identity</option>
            {unresolvedTrims.map((trim) => <option key={trim.canonical_id} value={trim.canonical_id}>{trim.name || trim.canonical_id}</option>)}
          </select></label>
          <label className="adminField"><span>Lifecycle</span><select name="action" required defaultValue="current">
            <option value="current">CURRENT — grade นี้ยังอยู่ใน line-up</option>
            <option value="historical">HISTORICAL — grade นี้ไม่อยู่ current line-up</option>
          </select></label>
          <label className="adminField adminFieldWide"><span>Official evidence URL</span><input name="source_ref" type="url" required /></label>
          <label className="adminField adminFieldWide"><span>Review note</span><input name="notes" type="text" placeholder="Official grade/price sheet confirms…" required /></label>
          <div className="adminFormActions"><button>Queue trim lifecycle review</button></div>
        </form> : null}

        {[...trimReviews.values()].some((decision) => focusedTrims.some((trim) => trim.canonical_id === decision.trimId)) ? <div className="adminNotice">
          <b>Reopen HUMAN decision</b><span>ถ้า evidence เปลี่ยน ให้ reopen ก่อนแล้ว review ใหม่; อย่า overwrite provenance เงียบ ๆ.</span>
          {[...trimReviews.values()].filter((decision) => focusedTrims.some((trim) => trim.canonical_id === decision.trimId)).map((decision) => <form key={decision.trimId} action={enqueueTrimRetailLifecycleReview} className="adminForm">
            <input type="hidden" name="submission_id" value={randomUUID()} />
            <input type="hidden" name="submitted_at" value={submittedAt} />
            <input type="hidden" name="model_id" value={focused.canonicalModelId} />
            <input type="hidden" name="trim_id" value={decision.trimId} />
            <input type="hidden" name="action" value="reopen" />
            <input type="hidden" name="notes" value="Reopen trim lifecycle decision for new evidence" />
            <div className="adminFormActions"><span>{decision.trimId} · {decision.status}</span><button>Reopen</button></div>
          </form>)}</div> : null}
      </> : null}
    </> : <div className="adminNotice"><span>ไม่มี retail lifecycle debt ใน current worklist.</span></div>}
  </div>;
}
