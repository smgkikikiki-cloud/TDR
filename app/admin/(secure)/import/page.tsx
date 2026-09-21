import Link from "next/link";
import { importReports, listImportRuns } from "@/lib/import-runs";
import { uploadImportFileAction } from "@/app/admin/import-actions";

export const dynamic = "force-dynamic";

function n(value: number | null | undefined) {
  return Number(value || 0).toLocaleString("th-TH");
}

const STATUS_LABEL: Record<string, string> = {
  UPLOADED: "รอประมวลผล",
  PROCESSING: "กำลังประมวลผล",
  COMPLETED: "เสร็จแล้ว",
  FAILED: "ไม่สำเร็จ",
};

export default async function ImportPage() {
  const year = new Date().getFullYear();
  const [runs, reports] = await Promise.all([
    listImportRuns(),
    Promise.resolve(importReports(year)),
  ]);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · IMPORT</small>
        <h1>นำเข้าข้อมูลจากไฟล์</h1>
        <p>
          อัปไฟล์แล้วจบ — ระบบจับคู่รถให้เอง เขียนเฉพาะช่องที่ไฟล์มีค่าจริง ช่องว่างไม่แตะของเดิม
          แถวที่หา identity ไม่ได้จริงๆ ไปรออยู่ที่ <Link href="/admin/exceptions">รายการที่ต้องตัดสิน</Link>
        </p>
      </div>
    </div>

    <form action={uploadImportFileAction} className="adminForm">
      <label className="adminField adminFieldWide">
        <span>ไฟล์ CSV หรือ XLSX (สูงสุด 40 MB)</span>
        <input name="file" type="file" accept=".csv,.xlsx,.xls" required />
      </label>
      <label className="adminField">
        <span>แหล่งข้อมูล</span>
        <select name="source_kind" defaultValue="ECO">
          <option value="ECO">ECO Sticker</option>
          <option value="OEM">OEM / ผู้ผลิต</option>
          <option value="DLT">DLT / ยอดจดทะเบียน</option>
          <option value="MEDIA">สื่อ</option>
        </select>
      </label>
      <div className="adminFormActions"><button className="adminPrimary">อัปโหลดและนำเข้า</button></div>
    </form>

    <div className="adminHeader"><div><small>สถานะ</small><h2>ไฟล์ที่อัปไว้</h2></div></div>
    <div className="libraryTable"><table>
      <thead><tr>
        <th>ไฟล์</th><th>แหล่ง</th><th>สถานะ</th><th>อ่านได้</th>
        <th>อัปเดต</th><th>สร้างใหม่</th><th>ต้องตัดสิน</th>
      </tr></thead>
      <tbody>
        {runs.length ? runs.map((run) => <tr key={run.id}>
          <td><b>{run.originalName}</b><br /><small>{new Date(run.createdAt).toLocaleString("th-TH")}</small></td>
          <td>{run.sourceKind}</td>
          <td>{STATUS_LABEL[run.status] || run.status}{run.error ? <><br /><small>{run.error}</small></> : null}</td>
          <td>{n(run.rowsRead)}</td>
          <td>{n(run.patched)}</td>
          <td>{n(run.created)}</td>
          <td>{run.exceptions ? <Link href="/admin/exceptions">{n(run.exceptions)}</Link> : "0"}</td>
        </tr>) : <tr><td colSpan={7}>ยังไม่มีไฟล์ที่อัปโหลด</td></tr>}
      </tbody>
    </table></div>

    {reports.length ? <>
      <div className="adminHeader"><div><small>ก่อนหน้า</small><h2>รอบที่นำเข้าผ่านเครื่องมือภายใน</h2></div></div>
      <div className="libraryTable"><table>
        <thead><tr><th>ไฟล์</th><th>อ่านได้</th><th>อัปเดต</th><th>สร้างใหม่</th><th>ต้องตัดสิน</th><th>เขียนแล้ว</th></tr></thead>
        <tbody>{reports.map((report) => <tr key={report.stem}>
          <td><b>{report.stem.replace(/^import_/, "")}</b></td>
          <td>{n(report.rows_read)}</td><td>{n(report.patched)}</td><td>{n(report.created)}</td>
          <td>{n(report.exceptions)}</td>
          <td>{report.applied ? "เขียนแล้ว" : "ยังไม่เขียน"}</td>
        </tr>)}</tbody>
      </table></div>
    </> : null}
  </div>;
}
