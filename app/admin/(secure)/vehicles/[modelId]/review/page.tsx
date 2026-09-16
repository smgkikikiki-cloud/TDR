import Link from "next/link";
import { notFound } from "next/navigation";
import { verifyEditProposal } from "@/lib/edit-proposal-token";
import { confirmEditProposal } from "@/app/admin/vehicle-editor-actions";

const KIND_LABEL: Record<string, string> = {
  MODEL_GENERATION: "Model / Generation edit",
  MARKET_TRIM: "MarketTrim create/edit",
  SPEC_FACT: "Spec field edit",
};

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

export default async function ReviewEditProposalPage({
  params, searchParams,
}: {
  params: Promise<{ modelId: string }>;
  searchParams: Promise<{ token?: string }>;
}) {
  const { modelId } = await params;
  const { token } = await searchParams;
  const proposal = verifyEditProposal(token);
  if (!proposal || proposal.modelId !== modelId) notFound();

  const changedRows = proposal.diff.filter((row) => row.changed);
  const unchangedRows = proposal.diff.filter((row) => !row.changed);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>REVIEW BEFORE QUEUE</small>
        <h1>{KIND_LABEL[proposal.kind] || proposal.kind}</h1>
        <p>ตรวจ Current vs Proposed ก่อนเข้าคิว canonical — ยังไม่มีอะไรถูกเขียนจนกว่าจะกด Confirm</p>
      </div>
      <Link className="adminPrimaryLink" href={`/admin/vehicles/${encodeURIComponent(modelId)}`}>← กลับไปแก้ไข (ยกเลิก)</Link>
    </div>

    <div className="adminNotice">
      <b>Session นี้หมดอายุใน ~20 นาที และเช็ค release ซ้ำตอน confirm</b>
      <span>
        ถ้า active canonical release เปลี่ยนระหว่างที่คุณเปิดหน้านี้ (มี revision ใหม่ publish ไปแล้ว) ระบบจะ reject ตอนกด
        Confirm แทนที่จะเขียนทับของใหม่แบบเงียบ ๆ — ต้องกลับไปเปิด editor แล้ว preview ใหม่
      </span>
      <code>submitted by {proposal.actor} · page release {proposal.pageReleaseId}</code>
    </div>

    <div className="adminHeader"><div><small>DIFF</small><h2>Changed fields ({changedRows.length})</h2></div></div>
    {changedRows.length ? <div className="libraryTable"><table><thead><tr>
      <th>Field</th><th>Current</th><th></th><th>Proposed</th>
    </tr></thead><tbody>
      {changedRows.map((row) => <tr key={row.field}>
        <td><b>{row.label}</b></td>
        <td>{formatValue(row.current)}</td>
        <td>→</td>
        <td><b>{formatValue(row.proposed)}</b></td>
      </tr>)}
    </tbody></table></div> : <div className="adminNotice"><span>ไม่มี field ที่ค่าจริงเปลี่ยน (อาจเป็นการสร้างใหม่ หรือ resubmit ค่าเดิม)</span></div>}

    {unchangedRows.length ? <details className="adminNotice">
      <summary>Fields ที่ส่งซ้ำแต่ค่าไม่เปลี่ยน ({unchangedRows.length})</summary>
      <ul>{unchangedRows.map((row) => <li key={row.field}>{row.label}: {formatValue(row.current)}</li>)}</ul>
    </details> : null}

    <div className="adminHeader"><div><small>EVIDENCE &amp; REASON</small><h2>สิ่งที่จะถูกบันทึกไว้ในคิว</h2></div></div>
    <div className="adminStatGrid">
      <div className="adminStat"><span>Evidence kind</span><strong>{proposal.evidence.sourceKind}</strong><small>{proposal.evidence.reviewedAt}</small></div>
      <div className="adminStat"><span>Evidence ref</span><strong>{proposal.evidence.sourceRef ? "มี URL" : "ไม่มี"}</strong>
        <small>{proposal.evidence.sourceRef ? <a href={proposal.evidence.sourceRef} target="_blank" rel="noreferrer">เปิด ↗</a> : "—"}</small></div>
      <div className="adminStat"><span>Reason</span><strong style={{ fontSize: "0.85rem" }}>{proposal.reason}</strong><small>บันทึกลง canonical revision</small></div>
    </div>

    <details className="adminNotice">
      <summary><b>Advanced · Raw canonical command JSON</b> (สิ่งที่จะเข้าคิวจริง)</summary>
      <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.8rem" }}>{JSON.stringify(proposal.batchPayload, null, 2)}</pre>
    </details>

    <form action={confirmEditProposal} className="adminForm">
      <input type="hidden" name="token" value={token} />
      <div className="adminFormActions">
        <button className="adminPrimary">Confirm &amp; queue this change</button>
      </div>
    </form>
    <p><Link href={`/admin/vehicles/${encodeURIComponent(modelId)}`}>ยกเลิกและกลับไปแก้ไข</Link> — ไม่กด Confirm ก็เท่ากับยกเลิก, token หมดอายุเองใน ~20 นาที</p>
  </div>;
}
