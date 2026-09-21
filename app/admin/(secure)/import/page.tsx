import Link from "next/link";
import { importReports } from "@/lib/import-runs";

export const dynamic = "force-dynamic";

function n(value: number) {
  return Number(value || 0).toLocaleString("th-TH");
}

export default async function ImportPage() {
  const year = new Date().getFullYear();
  const reports = importReports(year);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · IMPORT</small>
        <h1>นำเข้าข้อมูลจากไฟล์</h1>
        <p>
          ระบบจับคู่รถให้เอง แล้วเขียนทับเฉพาะช่องที่แหล่งข้อมูลมีค่าจริง — ช่องว่างในไฟล์ไม่แตะของเดิม
          แถวไหนจับคู่ไม่ได้จริงๆ จะไปอยู่ที่ <Link href="/admin/exceptions">รายการที่ต้องตัดสิน</Link> ไม่ต้องกดอนุมัติทีละคัน
        </p>
      </div>
    </div>

    <div className="adminNotice">
      <b>สั่งนำเข้า</b>
      <span>รันคำสั่งนี้กับไฟล์ CSV หรือ XLSX — ไม่ใส่ <code>--apply</code> คือลองดูผลก่อนโดยไม่เขียนอะไร</span>
      <code>python -m tools.import_source &lt;ไฟล์&gt; --source ECO --apply</code>
    </div>

    <div className="adminHeader"><div><small>ประวัติ</small><h2>รอบที่นำเข้าไปแล้ว</h2></div></div>
    <div className="libraryTable"><table>
      <thead><tr>
        <th>ไฟล์</th><th>อ่านได้</th><th>อัปเดต</th><th>สร้างใหม่</th>
        <th>ไม่เปลี่ยน</th><th>ต้องตัดสิน</th><th>เขียนแล้ว</th>
      </tr></thead>
      <tbody>
        {reports.length ? reports.map((report) => <tr key={report.stem}>
          <td><b>{report.stem.replace(/^import_/, "")}</b></td>
          <td>{n(report.rows_read)}</td>
          <td>{n(report.patched)}</td>
          <td>{n(report.created)}</td>
          <td>{n(report.unchanged)}</td>
          <td>{n(report.exceptions)}</td>
          <td>{report.applied ? "เขียนแล้ว" : "ยังไม่เขียน (dry run)"}</td>
        </tr>) : <tr><td colSpan={7}>ยังไม่มีการนำเข้า</td></tr>}
      </tbody>
    </table></div>
  </div>;
}
