import { randomUUID } from "node:crypto";
import { enqueueBulkModelRetailLifecycleReview } from "@/app/admin/retail-lifecycle-actions";
import { oemTargetsForModel } from "@/lib/price-evidence-registry";
import type { PriceCoverageWorkItem } from "@/lib/price-coverage-worklist";

function n(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("th-TH") : "—";
}

export default function BulkRetailLifecycleReview({
  rows,
  submittedAt,
  today,
}: {
  rows: PriceCoverageWorkItem[];
  submittedAt: string;
  today: string;
}) {
  const candidates = rows
    .filter((row) => row.blocker === "UNRESOLVED_MODEL_LIFECYCLE")
    .map((row) => {
      const targets = oemTargetsForModel(row.canonicalModelId)
        .filter((target) => target.role === "CURRENT_MODEL_PAGE");
      return { row, targets };
    })
    .filter(({ targets }) => targets.length > 0)
    .slice(0, 20);

  if (!candidates.length) return null;

  return <>
    <div className="adminHeader"><div>
      <small>BULK HUMAN REVIEW · REGISTERED CURRENT MODEL PAGES ONLY</small>
      <h2>ปิด lifecycle debt หลายรุ่นใน batch เดียว</h2>
      <p>ไม่มี auto-approve: ต้องติ๊กแต่ละ model เอง. Bulk mode รับเฉพาะ registered OEM target ที่ role = CURRENT_MODEL_PAGE; server re-resolve target/model และ reject ทั้ง batch ถ้า model ใดถูก review ไปแล้วจาก stale page.</p>
    </div></div>
    <form action={enqueueBulkModelRetailLifecycleReview} className="adminForm">
      <input type="hidden" name="submission_id" value={randomUUID()} />
      <input type="hidden" name="submitted_at" value={submittedAt} />
      <label className="adminField"><span>Checked at</span><input name="reviewed_at" type="date" defaultValue={today} required /></label>
      <div className="libraryTable adminFieldWide"><table>
        <thead><tr><th>Pick</th><th>Model / impact</th><th>HUMAN decision</th><th>Registered current-model evidence</th></tr></thead>
        <tbody>{candidates.map(({ row, targets }) => <tr key={row.canonicalModelId}>
          <td><input type="checkbox" name="bulk_model_id" value={row.canonicalModelId} aria-label={`Select ${row.brand} ${row.model}`} /></td>
          <td><b>{row.brand} {row.model}</b><br/><small>{row.canonicalModelId} · {n(row.registrations3m)} regs / 3M</small></td>
          <td><select name={`bulk_status:${row.canonicalModelId}`} defaultValue="CURRENT">
            <option value="CURRENT">CURRENT — ยังขาย/สั่งซื้อได้</option>
            <option value="HISTORICAL">HISTORICAL — ไม่อยู่ current lineup</option>
          </select></td>
          <td><select name={`bulk_target:${row.canonicalModelId}`} defaultValue={targets[0].id}>
            {targets.map((target) => <option key={target.id} value={target.id}>{target.sourceId} · {target.id}</option>)}
          </select><br/>
          <a href={targets[0].url} target="_blank" rel="noreferrer">เปิด default official source ↗</a><br/>
          <small>{targets[0].notes || targets[0].url}</small></td>
        </tr>)}</tbody>
      </table></div>
      <div className="adminNotice adminFieldWide"><b>Atomic batch</b><span>ถ้า model/target ใดไม่ตรง registry, ไม่อยู่ active release, หรือถูก HUMAN คนอื่น resolve ไปแล้ว ระบบจะ reject ทั้งชุดแทนการเขียนบางส่วน.</span></div>
      <div className="adminFormActions"><button>Queue selected HUMAN lifecycle reviews</button></div>
    </form>
  </>;
}
