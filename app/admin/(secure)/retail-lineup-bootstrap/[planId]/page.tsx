import Link from "next/link";
import { applyRetailLineupPlanAction } from "@/app/admin/retail-lineup-actions";
import { loadRetailLineupPlan } from "@/lib/retail-lineup-admin";

export const dynamic = "force-dynamic";

const STATUS_LABEL: Record<string, string> = {
  PREVIEW_READY: "พร้อมตรวจและ Apply",
  APPLYING: "กำลัง Apply",
  WRITTEN_PENDING_PUBLISH: "Canonical commit เขียนแล้ว · กำลัง publish",
  COMPLETED: "Publish เสร็จแล้ว",
  FAILED: "Apply ไม่สำเร็จ · ตรวจ error แล้ว retry ได้",
  STALE: "STALE · ต้องสร้าง workbook ใหม่",
  CANCELLED: "ยกเลิกแล้ว",
};

function n(value: number) {
  return Number(value || 0).toLocaleString("th-TH");
}

function Hash({ value }: { value: string }) {
  return <code style={{ overflowWrap: "anywhere" }}>{value || "—"}</code>;
}

export default async function RetailLineupPlanPage({
  params,
  searchParams,
}: {
  params: Promise<{ planId: string }>;
  searchParams: Promise<{ apply?: string }>;
}) {
  const [{ planId }, query] = await Promise.all([params, searchParams]);
  const result = await loadRetailLineupPlan(planId);

  if (result.error) return <div className="adminEditor">
    <div className="adminHeader"><div><small>RETAIL LINEUP BOOTSTRAP</small><h1>เปิด Preview ไม่ได้</h1></div></div>
    <div className="adminNotice"><b>Preview store ไม่พร้อม</b><span>{result.error}</span></div>
    <Link href="/admin/retail-lineup-bootstrap">← กลับ</Link>
  </div>;

  const plan = result.data;
  if (!plan) return <div className="adminEditor">
    <div className="adminHeader"><div><small>RETAIL LINEUP BOOTSTRAP</small><h1>ไม่พบ Preview</h1></div></div>
    <Link href="/admin/retail-lineup-bootstrap">← กลับ</Link>
  </div>;

  const canApply = plan.status === "PREVIEW_READY" || plan.status === "FAILED";

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>RETAIL LINEUP BOOTSTRAP · IMMUTABLE PREVIEW</small>
        <h1>{STATUS_LABEL[plan.status] || plan.status}</h1>
        <p>
          Preview นี้คือ object ที่จะ Apply จริง ถ้าต้องแก้ target แม้แต่หนึ่งแถว ให้แก้ XLSX แล้วอัปโหลดใหม่เพื่อสร้าง Preview ใหม่
        </p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/retail-lineup-bootstrap">กลับหน้ารวม</Link>
    </div>

    {query.apply === "queued" ? <div className="adminNotice"><b>ยืนยัน Apply แล้ว</b><span>ระบบจะใช้ stored compiled_plan ของ Preview นี้เท่านั้น แล้วอัปเดตสถานะจนถึง COMPLETED หลัง exact revision ถูก publish</span></div> : null}
    {plan.error ? <div className="adminNotice"><b>สถานะล่าสุดมี error</b><span>{plan.error}</span></div> : null}

    <div className="adminStatGrid">
      <div className="adminStat"><span>Models</span><strong>{n(plan.models)}</strong><small>target models</small></div>
      <div className="adminStat"><span>CURRENT</span><strong>{n(plan.beforeCurrent)} → {n(plan.afterCurrent)}</strong><small>before → after</small></div>
      <div className="adminStat"><span>CREATE</span><strong>{n(plan.create)}</strong><small>new identities</small></div>
      <div className="adminStat"><span>ARCHIVE</span><strong>{n(plan.archive)}</strong><small>literal HISTORICAL</small></div>
    </div>

    <div className="adminHeader"><div><small>AUDIT IDENTITY</small><h2>สิ่งที่ถูก pin ตอน Preview</h2></div></div>
    <div className="libraryTable"><table>
      <tbody>
        <tr><th>Plan ID</th><td><Hash value={plan.id} /></td></tr>
        <tr><th>Source SHA-256</th><td><Hash value={plan.sourceSha256} /></td></tr>
        <tr><th>Baseline hash</th><td><Hash value={plan.baselineHash} /></td></tr>
        <tr><th>Plan hash</th><td><Hash value={plan.planHash} /></td></tr>
        <tr><th>Base release</th><td>{plan.baseReleaseId}</td></tr>
        <tr><th>As of</th><td>{plan.asOf} · catalog {plan.catalogYear}</td></tr>
        <tr><th>Compiled by</th><td>{plan.actor}</td></tr>
        <tr><th>Approved by</th><td>{plan.approvedBy || "—"}</td></tr>
        <tr><th>Commit</th><td><Hash value={plan.appliedCommitSha || ""} /></td></tr>
        <tr><th>Serving release</th><td>{plan.releaseId || "—"}</td></tr>
      </tbody>
    </table></div>

    {plan.modelsDetail.map((model) => <section key={model.modelId}>
      <div className="adminHeader"><div>
        <small>MODEL DIFF</small>
        <h2>{model.modelId}</h2>
        <p>
          CURRENT {n(model.beforeCurrentTrimIds.length)} → {n(model.targetCurrentTrimIds.length)} · KEEP {n(model.counts.keep)} · CREATE {n(model.counts.create)} · REACTIVATE {n(model.counts.reactivate)} · ARCHIVE {n(model.counts.archive)}
        </p>
      </div></div>
      <div className="libraryTable"><table>
        <thead><tr><th>Action</th><th>Trim</th><th>Powertrain</th><th>Generation</th><th>Canonical ID</th><th>Identity</th></tr></thead>
        <tbody>{model.items.map((item) => <tr key={`${item.action}:${item.canonicalTrimId}`}>
          <td><b>{item.action}</b>{item.reopenRequired ? <><br /><small>explicit reopen</small></> : null}</td>
          <td>{item.trimName}</td>
          <td>{item.powertrain}</td>
          <td>{item.generationId}</td>
          <td><code>{item.canonicalTrimId}</code></td>
          <td>{item.identityResolution}</td>
        </tr>)}</tbody>
      </table></div>
    </section>)}

    <div className="adminHeader"><div><small>EXPLICIT APPLY</small><h2>ยืนยันเฉพาะ Preview นี้</h2><p>ปุ่มนี้ไม่อ่าน XLSX ใหม่และไม่หา identity ใหม่ มันส่ง plan ID + plan hash + baseline hash ที่เห็นด้านบนไป compare-and-set ก่อน worker ทำงาน</p></div></div>
    {canApply ? <form action={applyRetailLineupPlanAction} className="adminForm">
      <input type="hidden" name="plan_id" value={plan.id} />
      <input type="hidden" name="plan_hash" value={plan.planHash} />
      <input type="hidden" name="baseline_hash" value={plan.baselineHash} />
      <label className="adminField adminFieldWide">
        <span>ยืนยันว่าได้ตรวจ CREATE / REACTIVATE / ARCHIVE ด้านบนแล้ว</span>
        <span><input type="checkbox" name="confirm" value="YES" required /> Apply immutable plan นี้</span>
      </label>
      <div className="adminFormActions"><button className="adminPrimary">Apply Retail Lineup</button></div>
    </form> : <div className="adminNotice"><b>Apply ถูกล็อกตามสถานะ</b><span>{STATUS_LABEL[plan.status] || plan.status}</span></div>}
  </div>;
}
