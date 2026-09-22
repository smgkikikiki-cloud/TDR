import { randomUUID } from "node:crypto";
import Link from "next/link";
import { redirect } from "next/navigation";
import { currentEditor } from "@/lib/admin-auth";
import { listVehicleBrandsForPicker, listVehicleModelsForPicker } from "@/lib/canonical-editor";
import { createCanonicalVehicle } from "@/app/admin/vehicle-create-actions";
import { MARKET_TRIM_POWERTRAINS } from "@/lib/vehicle-taxonomy";

type ReturnQuery = {
  return?: string; exception_ids?: string; raw_brand?: string; raw_model?: string;
  registration_type?: string; grain?: string;
};

export default async function CreateVehiclePage({
  searchParams,
}: {
  searchParams: Promise<ReturnQuery>;
}) {
  const editor = await currentEditor();
  if (!editor) redirect("/admin/login");
  const query = await searchParams;
  const fromExceptions = query.return === "exceptions";
  const trimGrained = query.grain === "TRIM";
  // grain=MODEL (or no grain at all -- a plain non-exception model gap):
  // the source names a car, never a grade or a powertrain, so the trim
  // section is not offered at all here -- see readTrim() in
  // app/admin/vehicle-create-actions.ts for why it is ignored server-side
  // even if this were somehow submitted.
  const modelGrained = fromExceptions && query.grain !== "TRIM";
  const [brands, existingModels] = await Promise.all([
    listVehicleBrandsForPicker(),
    fromExceptions && query.raw_brand ? listVehicleModelsForPicker(query.raw_brand) : Promise.resolve([]),
  ]);

  const submittedAt = new Date().toISOString();
  const returnHidden = fromExceptions ? <>
    <input type="hidden" name="return" value="exceptions" />
    <input type="hidden" name="exception_ids" value={query.exception_ids || ""} />
    <input type="hidden" name="raw_brand" value={query.raw_brand || ""} />
    <input type="hidden" name="raw_model" value={query.raw_model || ""} />
    <input type="hidden" name="registration_type" value={query.registration_type || ""} />
    <input type="hidden" name="grain" value={query.grain || ""} />
  </> : null;

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · สร้างรถใหม่</small>
        <h1>สร้าง canonical vehicle ใหม่</h1>
        <p>
          บันทึกแล้วเข้าคิว canonical เดียวกับทุกการแก้ใน Admin — เขียน, commit,
          publish อัตโนมัติ ใช้เวลาสักครู่ก่อนจะปรากฏในระบบ
        </p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/vehicles">← กลับรายการรถ</Link>
    </div>

    {fromExceptions ? <div className="adminNotice">
      <span>
        มาจากรายการค้าง: <b>{query.raw_brand}</b> {query.raw_model}
        {query.registration_type ? ` · ${query.registration_type}` : ""} —
        บันทึกแล้วจะพากลับไปหน้า Exceptions พร้อมเลือกรถคันนี้ไว้ให้ กด "ผูก" ได้เลย
      </span>
      {modelGrained ? <span>
        ต้นทางระบุแค่ <b>ชื่อรุ่น</b> ไม่มีรุ่นย่อย/powertrain — ฟอร์มนี้จะสร้างแค่ Brand → Model → Generation
        ไว้ก่อน (ทำเครื่องหมาย "incomplete" ให้อัตโนมัติ) เพิ่มรุ่นย่อยทีหลังที่หน้ารถได้เมื่อรู้ข้อมูลแล้ว
      </span> : null}
    </div> : null}

    {trimGrained ? <div className="adminNotice">
      <span>
        ต้นทางระบุว่าเป็นระดับ<b>รุ่นย่อย</b> — ถ้ารถคันนี้<b>มีอยู่แล้ว</b>ในระบบ
        ให้เปิดหน้ารถแล้วเพิ่มรุ่นย่อยที่นั่นแทน (ที่ส่วน “+ เพิ่มรุ่นย่อยใหม่”)
        ซึ่งจะพากลับมาที่นี่ให้เองหลังบันทึก — ใช้ฟอร์มด้านล่างเฉพาะตอนที่รถคันนี้ยังไม่มีในระบบเลย
      </span>
      {existingModels.length ? <div className="libraryTable"><table><thead><tr>
        <th>Canonical model</th><th>ชื่อ</th><th></th>
      </tr></thead><tbody>
        {existingModels.slice(0, 10).map((model) => {
          const params = new URLSearchParams({
            return: "exceptions",
            exception_ids: query.exception_ids || "",
            raw_brand: query.raw_brand || "",
            raw_model: query.raw_model || "",
            registration_type: query.registration_type || "",
            grain: "TRIM",
          });
          return <tr key={model.canonicalId}>
            <td><code>{model.canonicalId}</code></td>
            <td>{model.brandId} {model.nameEn}</td>
            <td><Link className="adminPrimaryLink"
              href={`/admin/vehicles/${encodeURIComponent(model.canonicalId)}?${params.toString()}#trims`}
            >เปิดหน้ารถ →</Link></td>
          </tr>;
        })}
      </tbody></table></div> : null}
    </div> : null}

    <form action={createCanonicalVehicle} className="adminForm">
      {returnHidden}
      <input type="hidden" name="submission_id" value={randomUUID()} />
      <input type="hidden" name="submitted_at" value={submittedAt} />

      <fieldset className="adminFieldset">
        <legend>ยี่ห้อ</legend>
        <label className="adminField">
          <span><input type="radio" name="brand_mode" value="existing" defaultChecked /> เลือกยี่ห้อที่มีอยู่</span>
          <select name="brand_id" defaultValue="">
            <option value="">— เลือกยี่ห้อ —</option>
            {brands.map((brand) => <option key={brand.canonicalId} value={brand.canonicalId}>
              {brand.nameEn}{brand.nameTh ? ` · ${brand.nameTh}` : ""} ({brand.canonicalId})
            </option>)}
          </select>
        </label>
        <label className="adminField">
          <span><input type="radio" name="brand_mode" value="new" /> สร้างยี่ห้อใหม่</span>
        </label>
        <label className="adminField">
          <span>ชื่อยี่ห้อใหม่ (EN)</span>
          <input name="brand_name_en" type="text" defaultValue={fromExceptions ? query.raw_brand || "" : ""}
            placeholder="เช่น Great Wall" />
        </label>
        <label className="adminField">
          <span>ชื่อยี่ห้อใหม่ (TH) — ไม่บังคับ</span>
          <input name="brand_name_th" type="text" />
        </label>
      </fieldset>

      <fieldset className="adminFieldset">
        <legend>รุ่น (Model)</legend>
        <label className="adminField adminFieldWide">
          <span>ชื่อรุ่น (EN)</span>
          <input name="model_name_en" type="text" required
            defaultValue={fromExceptions ? query.raw_model || "" : ""} placeholder="เช่น Tank 300" />
        </label>
        <label className="adminField">
          <span>ชื่อรุ่น (TH) — ไม่บังคับ</span>
          <input name="model_name_th" type="text" />
        </label>
        <label className="adminField">
          <span>รหัส Generation</span>
          <input name="generation_code" type="text" required placeholder="เช่น GEN1" />
        </label>
      </fieldset>

      {modelGrained ? (
        // TRIM-grain requires a real name+powertrain the source actually
        // published; MODEL-grain has neither, and asking for one here would
        // be fabricating a fact -- see readTrim() in
        // app/admin/vehicle-create-actions.ts. No fieldset, no hidden
        // trim_powertrain either: MarketTrim.powertrain cannot be UNKNOWN, so
        // there is no safe default to send even silently.
        <p className="adminHint">
          ไม่มีช่องรุ่นย่อยในฟอร์มนี้ — ต้นทางระบุแค่ระดับรุ่น ระบบจะไม่สร้างรุ่นย่อยปลอมให้
        </p>
      ) : trimGrained ? (
        <fieldset className="adminFieldset">
          <legend>รุ่นย่อยแรก (MarketTrim)</legend>
          <p className="adminHint">ต้นทางระบุรุ่นย่อยมาด้วย — ต้องกรอกชื่อและ powertrain ให้ตรง</p>
          <label className="adminField adminFieldWide">
            <span>ชื่อรุ่นย่อย</span>
            <input name="trim_name" type="text" required
              defaultValue={query.raw_model || ""} placeholder="เช่น Standard" />
          </label>
          <label className="adminField">
            <span>Powertrain</span>
            <select name="trim_powertrain" required defaultValue="">
              <option value="" disabled>เลือก powertrain</option>
              {MARKET_TRIM_POWERTRAINS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        </fieldset>
      ) : (
        <fieldset className="adminFieldset">
          <legend>รุ่นย่อยแรก (MarketTrim) — ไม่บังคับ</legend>
          <label className="adminField">
            <span><input type="radio" name="create_mode" value="model_only" defaultChecked /> สร้างแค่ Model ก่อน</span>
          </label>
          <label className="adminField">
            <span><input type="radio" name="create_mode" value="with_trim" /> สร้างพร้อมรุ่นย่อยแรก</span>
          </label>
          <p className="adminHint">
            กรอกชื่อ/Powertrain ด้านล่างเฉพาะตอนที่เลือก “สร้างพร้อมรุ่นย่อยแรก” — ถ้าเลือก “สร้างแค่ Model ก่อน”
            สองช่องนี้จะไม่ถูกใช้เลย
          </p>
          <label className="adminField adminFieldWide">
            <span>ชื่อรุ่นย่อย</span>
            <input name="trim_name" type="text" placeholder="เช่น Standard" />
          </label>
          <label className="adminField">
            <span>Powertrain</span>
            <select name="trim_powertrain" defaultValue="">
              <option value="">— ไม่ใช้ —</option>
              {MARKET_TRIM_POWERTRAINS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        </fieldset>
      )}

      <label className="adminField adminFieldWide">
        <span>เหตุผล (ไม่บังคับ)</span>
        <input name="reason" type="text" placeholder="เว้นว่างได้" />
      </label>

      <div className="adminFormActions"><button className="adminPrimary">บันทึกและสร้างรถ</button></div>
    </form>

    <p className="adminHint">
      body_type ยังไม่ตั้ง (OTHER เป็นค่าเริ่มต้น) — แก้ได้ที่หน้ารถหลังสร้างเสร็จ ไม่ต้องกรอกตอนนี้
    </p>
  </div>;
}
