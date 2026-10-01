import Link from "next/link";
import {
  downloadRetailLineupWorkbookAction,
  requestRetailLineupWorkbookAction,
  uploadRetailLineupWorkbookAction,
} from "@/app/admin/retail-lineup-actions";
import {
  listRetailLineupPlans,
  listRetailLineupWorkbookExports,
} from "@/lib/retail-lineup-admin";

export const dynamic = "force-dynamic";

const PLAN_STATUS: Record<string, string> = {
  PREVIEW_READY: "พร้อมตรวจ",
  APPLYING: "กำลังเขียน",
  WRITTEN_PENDING_PUBLISH: "เขียนแล้ว · กำลัง publish",
  COMPLETED: "เสร็จแล้ว",
  FAILED: "Apply ไม่สำเร็จ",
  STALE: "Workbook เก่าแล้ว",
  CANCELLED: "ยกเลิก",
};

const EXPORT_STATUS: Record<string, string> = {
  QUEUED: "รอสร้าง",
  PROCESSING: "กำลังสร้าง",
  READY: "พร้อมดาวน์โหลด",
  FAILED: "สร้างไม่สำเร็จ",
};

function n(value: number) {
  return Number(value || 0).toLocaleString("th-TH");
}

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : "—";
}

export default async function RetailLineupBootstrapPage({
  searchParams,
}: {
  searchParams: Promise<{ export?: string; upload?: string }>;
}) {
  const query = await searchParams;
  const [exportsResult, plansResult] = await Promise.all([
    listRetailLineupWorkbookExports(),
    listRetailLineupPlans(),
  ]);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · LEVEL 0</small>
        <h1>Retail Lineup Bootstrap</h1>
        <p>
          ใช้เฉพาะตอน reset รายชื่อรุ่นย่อย CURRENT แบบ authoritative: สร้าง workbook จากฐานจริง,
          แก้ target lineup, อัปโหลดเพื่อ compile preview แล้วกด Apply หลังตรวจ diff เท่านั้น
        </p>
      </div>
    </div>

    <div className="adminNotice">
      <b>นี่ไม่ใช่ Price Feed</b>
      <span>
        แถวที่หายจาก TARGET_LINEUP จะถูก ARCHIVE เป็น HISTORICAL หลัง Apply จริง
        แต่ข้อมูลราคา สเปก แคมเปญ และประวัติเดิมจะไม่ถูกลบ การอัปโหลดไฟล์อย่างเดียวห้ามแตะ canonical data
      </span>
    </div>

    {query.export === "queued" ? <div className="adminNotice"><b>รับคำขอแล้ว</b><span>กำลังสร้าง workbook จาก main/current release กด refresh อีกครั้งเมื่อสถานะพร้อมดาวน์โหลด</span></div> : null}
    {query.upload === "queued" ? <div className="adminNotice"><b>อัปโหลดแล้ว</b><span>ไฟล์ถูกส่งเข้า compile-only pipeline; เมื่อผ่านจะมี PREVIEW_READY โผล่ด้านล่าง</span></div> : null}

    <div className="adminHeader"><div><small>STEP 1</small><h2>สร้าง workbook จากฐานปัจจุบัน</h2><p>ใส่ canonical model_id หนึ่งบรรทัดต่อรุ่น หรือคั่นด้วย comma ระบบจะ pin release + baseline ให้เอง</p></div></div>
    <form action={requestRetailLineupWorkbookAction} className="adminForm">
      <label className="adminField adminFieldWide">
        <span>model_id ที่ต้องการ reset</span>
        <textarea name="model_ids" rows={6} required placeholder={"toyota.camry\nhonda.accord"} />
      </label>
      <div className="adminFormActions"><button className="adminPrimary">สร้าง workbook</button></div>
    </form>

    {exportsResult.error ? <div className="adminNotice"><b>Workbook exporter ยังไม่พร้อม</b><span>{exportsResult.error}</span></div> : null}
    <div className="libraryTable"><table>
      <thead><tr><th>สร้างเมื่อ</th><th>รุ่น</th><th>Release</th><th>Baseline</th><th>สถานะ</th><th>ไฟล์</th></tr></thead>
      <tbody>
        {exportsResult.data.length ? exportsResult.data.map((row) => <tr key={row.id}>
          <td>{row.createdAt ? new Date(row.createdAt).toLocaleString("th-TH") : "—"}<br /><small>{row.actor}</small></td>
          <td><b>{n(row.modelIds.length)} รุ่น</b><br /><small>{row.modelIds.slice(0, 3).join(", ")}{row.modelIds.length > 3 ? " …" : ""}</small></td>
          <td>{row.baseReleaseId}<br /><small>catalog {row.catalogYear}</small></td>
          <td><code>{shortHash(row.baselineHash)}</code></td>
          <td>{EXPORT_STATUS[row.status] || row.status}{row.error ? <><br /><small>{row.error}</small></> : null}</td>
          <td>{row.status === "READY" ? <form action={downloadRetailLineupWorkbookAction}>
            <input type="hidden" name="export_id" value={row.id} />
            <button className="textButton">ดาวน์โหลด XLSX</button>
          </form> : "—"}</td>
        </tr>) : <tr><td colSpan={6}>ยังไม่มี workbook export</td></tr>}
      </tbody>
    </table></div>

    <div className="adminHeader"><div><small>STEP 2</small><h2>อัปโหลด workbook ที่แก้แล้ว</h2><p>ระบบอ่านเฉพาะ TARGET_LINEUP + IMPORT_META และ compile เป็น immutable plan ก่อน ยังไม่มี canonical write ในขั้นนี้</p></div></div>
    <form action={uploadRetailLineupWorkbookAction} className="adminForm">
      <label className="adminField adminFieldWide">
        <span>Retail Lineup Bootstrap XLSX (สูงสุด 4 MB)</span>
        <input name="file" type="file" accept=".xlsx" required />
      </label>
      <div className="adminFormActions"><button className="adminPrimary">อัปโหลดและสร้าง Preview</button></div>
    </form>

    <div className="adminHeader"><div><small>STEP 3</small><h2>Preview / Apply / Publish</h2><p>Apply ใช้ compiled_plan ที่เก็บไว้ตรง ๆ พร้อม plan hash + baseline hash ที่ตรวจตอน preview ไม่ recompile workbook ใหม่ตอนกด</p></div></div>
    {plansResult.error ? <div className="adminNotice"><b>Preview store ยังไม่พร้อม</b><span>{plansResult.error}</span></div> : null}
    <div className="libraryTable"><table>
      <thead><tr><th>Preview</th><th>สถานะ</th><th>Models</th><th>CURRENT ก่อน → หลัง</th><th>KEEP</th><th>CREATE</th><th>REACTIVATE</th><th>ARCHIVE</th><th>ผลลัพธ์</th></tr></thead>
      <tbody>
        {plansResult.data.length ? plansResult.data.map((plan) => <tr key={plan.id}>
          <td><Link href={`/admin/retail-lineup-bootstrap/${plan.id}`}><b>{new Date(plan.createdAt).toLocaleString("th-TH")}</b></Link><br /><small>{plan.actor} · {shortHash(plan.planHash)}</small></td>
          <td>{PLAN_STATUS[plan.status] || plan.status}{plan.error ? <><br /><small>{plan.error}</small></> : null}</td>
          <td>{n(plan.models)}</td>
          <td>{n(plan.beforeCurrent)} → {n(plan.afterCurrent)}</td>
          <td>{n(plan.keep)}</td><td>{n(plan.create)}</td><td>{n(plan.reactivate)}</td><td>{n(plan.archive)}</td>
          <td>{plan.releaseId ? <><b>{plan.releaseId}</b><br /><small>{shortHash(plan.appliedCommitSha)}</small></> : "—"}</td>
        </tr>) : <tr><td colSpan={9}>ยังไม่มี Preview</td></tr>}
      </tbody>
    </table></div>
  </div>;
}
