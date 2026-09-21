import Link from "next/link";
import { getAdminUnmappedRegistrationSummary } from "@/lib/admin-registration-market";
import { listVehicleModelsForPicker } from "@/lib/canonical-editor";
import { importExceptions } from "@/lib/import-runs";
import { assignRegistrationIdentity } from "@/app/admin/exception-actions";

export const dynamic = "force-dynamic";

const PAGE_LIMIT = 200;

function n(value: number) {
  return Number(value || 0).toLocaleString("th-TH");
}

export default async function ExceptionsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; assigned?: string; created?: string }>;
}) {
  const query = await searchParams;
  const term = (query.q || "").trim().toLowerCase();
  const year = new Date().getFullYear();

  const [unmapped, models] = await Promise.all([
    getAdminUnmappedRegistrationSummary(200).catch(() => [] as any[]),
    listVehicleModelsForPicker("").catch(() => []),
  ]);
  const fileRows = importExceptions(year).flatMap((run) => run.rows);

  const dlt = (unmapped as any[])
    .filter((row) => !term || `${row.brand_name_raw} ${row.model_name_raw}`.toLowerCase().includes(term))
    .slice(0, PAGE_LIMIT);
  const files = fileRows
    .filter((row) => !term || JSON.stringify(row).toLowerCase().includes(term))
    .slice(0, PAGE_LIMIT);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>EXCEPTIONS</small>
        <h1>รายการที่ระบบตัดสินแทนไม่ได้</h1>
        <p>
          ทุกแถวที่จับคู่ได้ชัดถูกเขียนไปแล้วโดยไม่ต้องถาม เหลือแต่ที่นี่ —
          ตัดสินครั้งเดียว ระบบจำไว้ เดือนถัดไปไม่ถามซ้ำ
        </p>
      </div>
    </div>

    {query.assigned ? <div className="adminSaved">
      ผูกรถเรียบร้อย — ป้ายชื่อนี้จะจับคู่เองอัตโนมัติในเดือนถัดไป และยอดเดือนก่อนๆ ถูกผูกย้อนหลังให้แล้ว
    </div> : null}
    {query.created ? <div className="adminSaved">
      สร้างรถใหม่แล้ว — เลือกรถคันนั้นในช่อง “ผูกกับรถ” ด้านล่างเพื่อปิดรายการนี้
    </div> : null}

    <form className="adminForm" action="/admin/exceptions">
      <label className="adminField adminFieldWide">
        <span>ค้นหายี่ห้อ / รุ่น / เหตุผล</span>
        <input name="q" type="text" defaultValue={term} placeholder="jaguar, camry, powertrain…" />
      </label>
      <div className="adminFormActions"><button className="adminPrimary">ค้นหา</button></div>
    </form>

    {/* ---------- DLT labels with no vehicle yet ---------- */}
    <div className="adminHeader"><div>
      <small>ยอดจดทะเบียน</small>
      <h2>ป้ายชื่อจาก DLT ที่ยังไม่รู้ว่าเป็นรถคันไหน ({n(dlt.length)})</h2>
      <p>
        DLT รายงานระดับรุ่น ไม่ใช่รุ่นย่อย — การผูกที่นี่จึงผูกกับ “รุ่น” เท่านั้น ไม่เดารุ่นย่อย
        ถ้าเป็นรถที่ยังไม่มีในระบบ กด “สร้างรถใหม่” แล้วกลับมาผูกที่แถวเดิม
      </p>
    </div></div>
    <div className="libraryTable"><table>
      <thead><tr><th>ป้ายชื่อจาก DLT</th><th>ยอด</th><th>ล่าสุด</th><th>ผูกกับรถ</th></tr></thead>
      <tbody>
        {dlt.length ? dlt.map((row: any) => {
          const key = `${row.registration_type}|${row.brand_name_raw}|${row.model_name_raw}`;
          return <tr key={key}>
            <td><b>{row.brand_name_raw}</b><br />{row.model_name_raw}<br /><small>{row.registration_type}</small></td>
            <td>{n(row.registrations)}<br /><small>{row.months} เดือน</small></td>
            <td>{row.latest_period}</td>
            <td>
              <form action={assignRegistrationIdentity} className="adminInlineForm">
                <input type="hidden" name="raw_brand" value={row.brand_name_raw} />
                <input type="hidden" name="raw_model" value={row.model_name_raw} />
                <input type="hidden" name="registration_type" value={row.registration_type} />
                <select name="canonical_model_id" defaultValue="" required aria-label={`รถสำหรับ ${row.model_name_raw}`}>
                  <option value="" disabled>เลือกรถที่มีอยู่…</option>
                  {models.map((model: any) => <option key={model.canonicalId} value={model.canonicalId}>
                    {model.brandId} {model.nameEn}
                  </option>)}
                </select>
                <button className="adminPrimary">ผูก</button>
              </form>
              <Link href="/admin/vehicles?return=exceptions">+ สร้างรถใหม่</Link>
            </td>
          </tr>;
        }) : <tr><td colSpan={4}>ไม่มีป้ายชื่อค้าง</td></tr>}
      </tbody>
    </table></div>

    {/* ---------- Rows an uploaded file could not place ---------- */}
    <div className="adminHeader"><div>
      <small>ไฟล์นำเข้า</small>
      <h2>แถวจากไฟล์ที่ระบุตัวรถไม่ได้ ({n(fileRows.length)})</h2>
      <p>แก้ที่หน้ารถแล้วอัปไฟล์เดิมซ้ำได้เลย — แถวที่ผูกได้แล้วจะไม่ถูกเขียนซ้ำ</p>
    </div></div>
    <div className="libraryTable"><table>
      <thead><tr><th>รถ</th><th>รุ่นย่อยจากต้นทาง</th><th>ทำไมตัดสินไม่ได้</th></tr></thead>
      <tbody>
        {files.length ? files.map((row, index) => <tr key={`${row.source_id || index}-${index}`}>
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
