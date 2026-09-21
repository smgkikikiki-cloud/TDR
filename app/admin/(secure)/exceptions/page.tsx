import Link from "next/link";
import { importExceptions } from "@/lib/import-runs";

export const dynamic = "force-dynamic";

const PAGE_LIMIT = 200;

export default async function ExceptionsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const term = ((await searchParams).q || "").trim().toLowerCase();
  const year = new Date().getFullYear();
  const runs = importExceptions(year);
  const rows = runs.flatMap((run) => run.rows);
  const visible = rows
    .filter((row) => !term || JSON.stringify(row).toLowerCase().includes(term))
    .slice(0, PAGE_LIMIT);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · EXCEPTIONS</small>
        <h1>รายการที่ระบบตัดสินแทนไม่ได้</h1>
        <p>
          ทุกแถวที่จับคู่ได้ชัดถูกเขียนไปแล้วโดยไม่ต้องถาม เหลือแต่ที่นี่ —
          ชื่อรุ่นย่อยที่อาจซ้ำกับของเดิม แบรนด์ที่ยังไม่มีในแคตตาล็อก หรือข้อมูลต้นทางที่ไม่พอระบุตัวรถ
          แก้ได้ที่ <Link href="/admin/vehicles">หน้ารถ</Link> แล้วนำเข้าใหม่อีกรอบ
        </p>
      </div>
    </div>

    <form className="adminForm" action="/admin/exceptions">
      <label className="adminField adminFieldWide">
        <span>ค้นหาแบรนด์ / รุ่น / เหตุผล</span>
        <input name="q" type="text" defaultValue={term} placeholder="jaguar, camry, powertrain…" />
      </label>
      <div className="adminFormActions"><button className="adminPrimary">ค้นหา</button></div>
    </form>

    <div className="adminHeader"><div>
      <small>{rows.length.toLocaleString("th-TH")} รายการ</small>
      <h2>แสดง {visible.length.toLocaleString("th-TH")} รายการแรก</h2>
    </div></div>
    <div className="libraryTable"><table>
      <thead><tr><th>รถ</th><th>รุ่นย่อยจากต้นทาง</th><th>ทำไมตัดสินไม่ได้</th></tr></thead>
      <tbody>
        {visible.length ? visible.map((row, index) => <tr key={`${row.source_id || index}-${index}`}>
          <td>
            <b>{row.model_id || `${row.brand || ""} ${row.model || ""}`.trim() || "—"}</b>
            {row.model_id
              ? <><br /><Link href={`/admin/vehicles/${encodeURIComponent(row.model_id)}`}>เปิดหน้ารถ →</Link></>
              : null}
          </td>
          <td>{row.trim_name || "—"}{row.powertrain ? <><br /><small>{row.powertrain}</small></> : null}</td>
          <td>{row.reason}</td>
        </tr>) : <tr><td colSpan={3}>ไม่มีรายการค้าง</td></tr>}
      </tbody>
    </table></div>
  </div>;
}
