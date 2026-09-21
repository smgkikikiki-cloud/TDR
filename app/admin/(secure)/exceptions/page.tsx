import Link from "next/link";
import { getAdminUnmappedRegistrationSummary } from "@/lib/admin-registration-market";
import { listVehicleModelsForPicker, listVehicleTrimsForPicker } from "@/lib/canonical-editor";
import {
  type RegistrationGap, listOpenExceptions, otherExceptions, registrationGaps,
} from "@/lib/import-exceptions";
import { importExceptions } from "@/lib/import-runs";
import { assignRegistrationIdentity, resolveException } from "@/app/admin/exception-actions";

export const dynamic = "force-dynamic";

const PAGE_LIMIT = 200;

function n(value: number) {
  return Number(value || 0).toLocaleString("th-TH");
}

function norm(value: string) {
  return String(value || "").normalize("NFKC").toLocaleLowerCase("en-US")
    .replace(/[^\p{L}\p{N}]+/gu, "");
}

function gapKey(gap: { registrationType: string; brandRaw: string; modelRaw: string }) {
  return `${gap.registrationType}|${gap.brandRaw}|${gap.modelRaw}`;
}

export default async function ExceptionsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; assigned?: string; created?: string; resolved?: string }>;
}) {
  const query = await searchParams;
  const term = (query.q || "").trim().toLowerCase();
  const year = new Date().getFullYear();

  const [unmapped, models, open] = await Promise.all([
    getAdminUnmappedRegistrationSummary(200).catch(() => [] as any[]),
    listVehicleModelsForPicker("").catch(() => []),
    listOpenExceptions().catch(() => []),
  ]);

  // The work list is the exception store: one durable row per unresolved
  // thing, with the grain the source published. Labels already sitting
  // unmapped in the registration table from before that store existed are
  // folded in beside them, so nothing waits for a file to be re-uploaded
  // before it can be resolved.
  const gaps: RegistrationGap[] = registrationGaps(open);
  const known = new Set(gaps.map(gapKey));
  for (const row of unmapped as any[]) {
    const gap: RegistrationGap = {
      ids: [],
      brandRaw: String(row.brand_name_raw || ""),
      modelRaw: String(row.model_name_raw || ""),
      registrationType: String(row.registration_type || "*"),
      grain: "MODEL",
      units: Number(row.registrations || 0),
      months: Number(row.months || 0),
      latestPeriod: String(row.latest_period || ""),
      reason: "ยังไม่มี mapping ที่บันทึกไว้",
    };
    if (!gap.brandRaw || !gap.modelRaw || known.has(gapKey(gap))) continue;
    known.add(gapKey(gap));
    gaps.push(gap);
  }

  // A grade picker only where the source itself printed the grade, and only
  // for the brands in play -- the whole trim catalogue in a select is not a
  // choice anybody can make.
  const trimBrands = new Set(gaps.filter((gap) => gap.grain === "TRIM")
    .map((gap) => norm(gap.brandRaw)));
  const trimModels = trimBrands.size
    ? (models as any[]).filter((model) => trimBrands.has(norm(model.brandId)))
    : [];
  const trims = trimModels.length
    ? await listVehicleTrimsForPicker(trimModels.map((model: any) => model.canonicalId))
      .catch(() => [])
    : [];
  const trimsByModel = new Map<string, Array<{ canonicalId: string; name: string }>>();
  for (const trim of trims) {
    const list = trimsByModel.get(trim.modelId) || [];
    list.push({ canonicalId: trim.canonicalId, name: trim.name });
    trimsByModel.set(trim.modelId, list);
  }

  const others = otherExceptions(open)
    .filter((row) => !term || JSON.stringify(row).toLowerCase().includes(term));
  // What the CLI path left on disk, for runs that never went through a
  // queue row at all.
  const onDisk = importExceptions(year).flatMap((run) =>
    run.rows.map((row) => ({ ...row, runLabel: run.stem })));

  const visible = gaps
    .filter((gap) => !term || `${gap.brandRaw} ${gap.modelRaw}`.toLowerCase().includes(term))
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
    {query.resolved ? <div className="adminSaved">ปิดรายการแล้ว</div> : null}

    <form className="adminForm" action="/admin/exceptions">
      <label className="adminField adminFieldWide">
        <span>ค้นหายี่ห้อ / รุ่น / เหตุผล</span>
        <input name="q" type="text" defaultValue={term} placeholder="jaguar, camry, powertrain…" />
      </label>
      <div className="adminFormActions"><button className="adminPrimary">ค้นหา</button></div>
    </form>

    {/* ---------- registration labels with no car yet ---------- */}
    <div className="adminHeader"><div>
      <small>ยอดจดทะเบียน</small>
      <h2>ป้ายชื่อจากต้นทางที่ยังไม่รู้ว่าเป็นรถคันไหน ({n(gaps.length)})</h2>
      <p>
        ผูกตามที่ต้นทางบอกเท่านั้น — ไฟล์ที่บอกแค่ชื่อรุ่น ผูกได้แค่ระดับรุ่น
        ไฟล์ที่พิมพ์รุ่นย่อยมาด้วย (หลายยี่ห้อทำแบบนี้) ถึงจะเลือกรุ่นย่อยได้
        ถ้าเป็นรถที่ยังไม่มีในระบบ กด “สร้างรถใหม่” แล้วกลับมาผูกที่แถวเดิม
      </p>
    </div></div>
    <div className="libraryTable"><table>
      <thead><tr><th>ป้ายชื่อจากต้นทาง</th><th>ยอด</th><th>ล่าสุด</th><th>ผูกกับรถ</th></tr></thead>
      <tbody>
        {visible.length ? visible.map((gap) => {
          const trimGrained = gap.grain === "TRIM";
          return <tr key={gapKey(gap)}>
            <td>
              <b>{gap.brandRaw}</b><br />{gap.modelRaw}<br />
              <small>{gap.registrationType} · {trimGrained ? "ต้นทางระบุรุ่นย่อย" : "ต้นทางระบุแค่รุ่น"}</small>
            </td>
            <td>{n(gap.units)}<br /><small>{n(gap.months)} เดือน</small></td>
            <td>{gap.latestPeriod || "—"}</td>
            <td>
              <form action={assignRegistrationIdentity} className="adminInlineForm">
                <input type="hidden" name="raw_brand" value={gap.brandRaw} />
                <input type="hidden" name="raw_model" value={gap.modelRaw} />
                <input type="hidden" name="registration_type" value={gap.registrationType} />
                <input type="hidden" name="exception_ids" value={gap.ids.join(",")} />
                <select name="target" defaultValue="" required aria-label={`รถสำหรับ ${gap.modelRaw}`}>
                  <option value="" disabled>เลือกรถที่มีอยู่…</option>
                  {(models as any[]).map((model: any) => {
                    const grades = trimGrained ? trimsByModel.get(model.canonicalId) || [] : [];
                    const label = `${model.brandId} ${model.nameEn}`;
                    if (!grades.length) {
                      return <option key={model.canonicalId} value={model.canonicalId}>{label}</option>;
                    }
                    return <optgroup key={model.canonicalId} label={label}>
                      <option value={model.canonicalId}>{label} — ทั้งรุ่น</option>
                      {grades.map((trim) => <option
                        key={trim.canonicalId}
                        value={`${model.canonicalId}::${trim.canonicalId}`}
                      >{label} — {trim.name}</option>)}
                    </optgroup>;
                  })}
                </select>
                <button className="adminPrimary">ผูก</button>
              </form>
              <Link href="/admin/vehicles?return=exceptions">+ สร้างรถใหม่</Link>
            </td>
          </tr>;
        }) : <tr><td colSpan={4}>ไม่มีป้ายชื่อค้าง</td></tr>}
      </tbody>
    </table></div>

    {/* ---------- everything else an import could not place ---------- */}
    <div className="adminHeader"><div>
      <small>ไฟล์นำเข้า</small>
      <h2>แถวจากไฟล์ที่ระบุตัวรถไม่ได้ ({n(others.length)})</h2>
      <p>แก้ที่หน้ารถแล้วอัปไฟล์เดิมซ้ำได้เลย — แถวที่ผูกได้แล้วจะไม่ถูกเขียนซ้ำ</p>
    </div></div>
    <div className="libraryTable"><table>
      <thead><tr><th>จากต้นทาง</th><th>ทำไมตัดสินไม่ได้</th><th>ไฟล์</th><th>ปิดรายการ</th></tr></thead>
      <tbody>
        {others.length ? others.slice(0, PAGE_LIMIT).map((row) => <tr key={row.id}>
          <td>
            <b>{String(row.identity.model_id || row.identity.trim_id
              || `${row.identity.brand || ""} ${row.identity.model || ""}`.trim() || "—")}</b>
            {row.identity.model_id
              ? <><br /><Link href={`/admin/vehicles/${encodeURIComponent(String(row.identity.model_id))}`}>
                เปิดหน้ารถ →</Link></>
              : null}
            {row.identity.trim_name ? <><br /><small>{String(row.identity.trim_name)}</small></> : null}
          </td>
          <td>{row.reason}<br /><small>{row.kind}</small></td>
          <td><small>{row.runLabel}</small></td>
          <td>
            <form action={resolveException} className="adminInlineForm">
              <input type="hidden" name="exception_ids" value={row.id} />
              <input name="note" type="text" placeholder="ปิดเพราะ…" aria-label="เหตุผลที่ปิด" />
              <button>ปิด</button>
            </form>
          </td>
        </tr>) : <tr><td colSpan={4}>ไม่มีรายการค้าง</td></tr>}
      </tbody>
    </table></div>

    {onDisk.length ? <>
      <div className="adminHeader"><div>
        <small>รายงานจาก CLI</small>
        <h2>แถวที่ import ทาง command line ทิ้งไว้ ({n(onDisk.length)})</h2>
        <p>อ่านอย่างเดียว — รันผ่านหน้า Import เพื่อให้รายการเข้ามาปิดได้ที่นี่</p>
      </div></div>
      <div className="libraryTable"><table>
        <thead><tr><th>รถ</th><th>จากต้นทาง</th><th>ทำไมตัดสินไม่ได้</th><th>ไฟล์</th></tr></thead>
        <tbody>
          {onDisk.slice(0, PAGE_LIMIT).map((row, index) => <tr key={`${row.runLabel}-${index}`}>
            <td>{row.model_id || `${row.brand || ""} ${row.model || ""}`.trim() || "—"}</td>
            <td>{row.trim_name || row.model || "—"}</td>
            <td>{row.reason}</td>
            <td><small>{row.runLabel}</small></td>
          </tr>)}
        </tbody>
      </table></div>
    </> : null}
  </div>;
}
