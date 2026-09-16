import { randomUUID } from "node:crypto";
import Link from "next/link";
import { notFound } from "next/navigation";
import { loadVehicleWorkspace } from "@/lib/canonical-editor";
import { loadSpecFieldRegistry, groupSpecFields, fieldAppliesToPowertrain } from "@/lib/spec-field-registry";
import { BODY_TYPES, SEGMENTS, MARKET_TRIM_POWERTRAINS, DRIVETRAINS } from "@/lib/vehicle-taxonomy";
import { prepareModelGenerationEdit, prepareMarketTrimEdit, prepareSpecFactEdit } from "@/app/admin/vehicle-editor-actions";

function money(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? `${number.toLocaleString("th-TH")} บาท` : "ยังไม่มี List price";
}

const KIND_LABEL: Record<string, string> = {
  MODEL_GENERATION: "Model / Generation",
  MARKET_TRIM: "MarketTrim",
  SPEC_FACT: "Spec field",
};

export default async function VehicleWorkspacePage({
  params, searchParams,
}: {
  params: Promise<{ modelId: string }>;
  searchParams: Promise<{ queued?: string; kind?: string }>;
}) {
  const { modelId } = await params;
  const query = await searchParams;
  const workspace = await loadVehicleWorkspace(modelId);
  if (!workspace) notFound();

  const { brand, model, generation, trims, specFactsByTrim, evidenceTargets, relatedBatches, releaseId, releaseYear } = workspace;
  const submittedAt = new Date().toISOString();
  const today = submittedAt.slice(0, 10);
  const registry = loadSpecFieldRegistry(releaseYear);
  const groups = groupSpecFields(registry);
  const qualifierKeys = [...new Set(registry.flatMap((f) => f.comparisonQualifiers))].sort();

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · CANONICAL VEHICLE EDITOR</small>
        <h1>{brand.nameEn} {model.nameEn}{model.nameTh ? ` · ${model.nameTh}` : ""}</h1>
        <p><code>{modelId}</code> · generation {generation?.code || "—"} · active release <code>{releaseId}</code></p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/vehicles">← กลับรายการรถ</Link>
    </div>

    {query.queued ? <div className="adminSaved">คิว {KIND_LABEL[query.kind || ""] || "canonical"} เข้าคิวแล้ว — ตรวจสถานะได้ที่ Input queue ด้านล่าง</div> : null}

    <div className="adminNotice">
      <b>หนึ่งเวิร์กสเปซ ไม่ใช่ bench แยก</b>
      <span>
        ทุกการแก้ที่นี่เข้าคิวเดียวกับ /admin/vehicle-input (validate → revision → PR → release) ไม่เขียน current_vehicle_* /
        canonical projection / release row ตรง ๆ. งานที่ยังอยู่คนละหน้า:{" "}
        {model.tdrModelId ? <Link href={`/admin/models/${model.tdrModelId}/edit`}>Editorial ↗</Link> : "Editorial (ไม่มี TDR model UUID cross-walk)"}
        {" · "}<Link href={`/admin/vehicle-input?model=${encodeURIComponent(modelId)}`}>Price Bench ↗</Link>
        {" · "}<Link href="/admin/prices/coverage">Price coverage ↗</Link>
        {" · "}<Link href={`/admin/retail-lifecycle?model=${encodeURIComponent(modelId)}`}>Retail lifecycle ↗</Link>
        {" · "}<Link href="/admin/vehicle-input">Advanced JSON ↗</Link>
      </span>
    </div>

    {/* ---------- A. Model / Generation ---------- */}
    <div className="adminHeader"><div><small>CANONICAL · A</small><h2>Model / Generation</h2>
      <p>ช่องว่าง = ไม่แก้ field นั้น. Generation code คงที่เสมอเพื่อรักษา canonical identity (เปลี่ยน code = สร้าง generation ใหม่ที่ writer ระดับ canonical_write.py)</p>
    </div></div>
    <form action={prepareModelGenerationEdit} className="adminForm">
      <input type="hidden" name="model_id" value={modelId} />
      <input type="hidden" name="page_release_id" value={releaseId} />
      <input type="hidden" name="submission_id" value={randomUUID()} />
      <input type="hidden" name="submitted_at" value={submittedAt} />
      <label className="adminField"><span>Name EN (ปัจจุบัน: {model.nameEn})</span><input name="name_en" type="text" /></label>
      <label className="adminField"><span>Name TH (ปัจจุบัน: {model.nameTh || "—"})</span><input name="name_th" type="text" /></label>
      <label className="adminField"><span>Body type (ปัจจุบัน: {model.bodyType || "—"})</span><select name="body_type" defaultValue=""><option value="">ไม่แก้</option>{BODY_TYPES.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
      <label className="adminField"><span>Segment (ปัจจุบัน: {generation?.segment || "—"})</span><select name="segment" defaultValue=""><option value="">ไม่แก้</option>{SEGMENTS.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
      <label className="adminField"><span>Seats (ปัจจุบัน: {(generation as any)?.seats || "—"})</span><input name="seats" type="number" min="1" step="1" /></label>
      <label className="adminField"><span>Launched (ปัจจุบัน: {generation?.launched || "—"})</span><input name="launched" type="date" /></label>
      <label className="adminField"><span>Ended (ปัจจุบัน: {generation?.ended || "—"})</span><input name="ended" type="date" /></label>
      <label className="adminField"><span>ชนิดหลักฐาน</span><select name="evidence_kind" defaultValue="ADMIN">
        <option value="ADMIN">Admin manual note</option><option value="OEM">OEM / official</option><option value="MEDIA">Media</option>
      </select></label>
      <label className="adminField"><span>Evidence URL (ถ้ามี)</span><input name="evidence_ref" type="text" placeholder="https://…" /></label>
      <label className="adminField"><span>วันที่ตรวจ</span><input name="reviewed_at" type="date" defaultValue={today} required /></label>
      <label className="adminField adminFieldWide"><span>เหตุผลการแก้</span><input name="reason" type="text" placeholder="Correct official model naming / taxonomy…" required /></label>
      <div className="adminFormActions"><button className="adminPrimary">Preview diff →</button></div>
    </form>

    {/* ---------- B. MarketTrims ---------- */}
    <div className="adminHeader"><div><small>CANONICAL · B</small><h2>MarketTrims ({trims.length})</h2>
      <p>สร้างใหม่หรือแก้ที่มีอยู่ — ต้องมี evidence URL เสมอ (OEM/Media) เพื่อกันสร้าง identity มั่ว ระบบเช็ค duplicate (generation + powertrain + ชื่อ normalize) ให้อัตโนมัติ</p>
    </div></div>
    <div className="libraryTable"><table><thead><tr>
      <th>Trim</th><th>Powertrain</th><th>Status</th><th>List price</th><th>Source refs</th>
    </tr></thead><tbody>
      {trims.length ? trims.map((trim) => <tr key={trim.canonicalId}>
        <td><code>{trim.canonicalId}</code><br /><b>{trim.name}</b></td>
        <td>{trim.powertrain}</td>
        <td>{trim.status}</td>
        <td>{money(trim.currentListPrice?.amount_thb)}</td>
        <td>{Object.keys(trim.sourceRefs || {}).join(", ") || "—"}</td>
      </tr>) : <tr><td colSpan={5}>ยังไม่มี MarketTrim ใต้รุ่นนี้</td></tr>}
    </tbody></table></div>

    {generation ? <details className="adminNotice">
      <summary><b>เพิ่ม MarketTrim ใหม่</b> — manual, OEM-backed (ไม่ต้องผ่าน ECO snapshot)</summary>
      <MarketTrimForm modelId={modelId} releaseId={releaseId} submittedAt={submittedAt} today={today} />
    </details> : <div className="adminNotice"><span>รุ่นนี้ไม่มี active generation — ไม่สามารถเพิ่ม/แก้ MarketTrim ได้จนกว่าจะแก้ generation ผ่าน Advanced JSON</span></div>}

    {trims.map((trim) => <details key={trim.canonicalId} className="adminNotice">
      <summary><b>แก้ MarketTrim: {trim.name}</b> · <code>{trim.canonicalId}</code></summary>
      <MarketTrimForm modelId={modelId} releaseId={releaseId} submittedAt={submittedAt} today={today} existing={trim} />
    </details>)}

    {/* ---------- C. Variant / powertrain / spec facts ---------- */}
    <div className="adminHeader"><div><small>CANONICAL · C</small><h2>Spec facts ต่อ MarketTrim</h2>
      <p>Field list มาจาก automotive/vehicle_master canonical spec registry ({registry.length} fields, {groups.size} groups) ไม่ใช่ hardcode — เพิ่ม field ใหม่ใน registry แล้วมันโผล่ที่นี่เอง</p>
    </div></div>
    {trims.map((trim) => {
      const facts = specFactsByTrim.get(trim.canonicalId) || [];
      const applicableCount = registry.filter((f) => fieldAppliesToPowertrain(f, trim.powertrain)).length;
      return <details key={trim.canonicalId} className="adminNotice">
        <summary><b>Specs · {trim.name}</b> ({facts.length} facts recorded / {applicableCount} fields applicable to {trim.powertrain})</summary>
        {facts.length ? <div className="libraryTable"><table><thead><tr>
          <th>Field</th><th>State</th><th>Value</th><th>Verification</th><th>Source</th>
        </tr></thead><tbody>
          {facts.map((fact) => {
            const def = registry.find((f) => f.key === fact.fieldKey);
            const payload = fact.payload as any;
            return <tr key={fact.factId}>
              <td>{def ? `${def.labelEn} (${def.group})` : fact.fieldKey}</td>
              <td>{payload.value_state}</td>
              <td>{payload.value_state === "KNOWN" ? `${Array.isArray(payload.value) ? payload.value.join(", ") : String(payload.value)}${payload.unit ? ` ${payload.unit}` : ""}` : "—"}</td>
              <td>{payload.verification_status || "—"}</td>
              <td>{payload.source_ref ? <a href={payload.source_ref} target="_blank" rel="noreferrer">↗</a> : payload.source || "—"}</td>
            </tr>;
          })}
        </tbody></table></div> : <p>ยังไม่มี spec fact ที่บันทึกไว้สำหรับ trim นี้</p>}

        <form action={prepareSpecFactEdit} className="adminForm">
          <input type="hidden" name="model_id" value={modelId} />
          <input type="hidden" name="trim_id" value={trim.canonicalId} />
          <input type="hidden" name="page_release_id" value={releaseId} />
          <input type="hidden" name="submission_id" value={randomUUID()} />
          <input type="hidden" name="submitted_at" value={submittedAt} />
          <label className="adminField adminFieldWide"><span>Field</span><select name="field_key" required defaultValue="">
            <option value="" disabled>เลือก spec field…</option>
            {[...groups.entries()].map(([group, fields]) => <optgroup key={group} label={group}>
              {fields.filter((f) => fieldAppliesToPowertrain(f, trim.powertrain)).map((f) => <option key={f.key} value={f.key}>
                {f.labelEn} ({f.labelTh}){f.canonicalUnit ? ` · ${f.canonicalUnit}` : ""} · {f.valueType}
              </option>)}
            </optgroup>)}
          </select></label>
          <label className="adminField"><span>Value state</span><select name="value_state" defaultValue="KNOWN">
            <option value="KNOWN">KNOWN — มีค่าจริง</option>
            <option value="NOT_AVAILABLE">NOT_AVAILABLE — แหล่งข้อมูลไม่ระบุ</option>
            <option value="NOT_APPLICABLE">NOT_APPLICABLE — ไม่เกี่ยวกับรถคันนี้ (เช่น BEV ไม่มี displacement)</option>
            <option value="UNKNOWN">UNKNOWN — ยังไม่มีใครตรวจ</option>
          </select></label>
          <label className="adminField"><span>Value (ใส่เฉพาะตอน KNOWN)</span><input name="value" type="text" placeholder="ตัวเลข / true|false / ข้อความ / comma,separated,list" /></label>
          <label className="adminField"><span>Verification</span><select name="verification_status" defaultValue="VERIFIED">
            <option value="VERIFIED">VERIFIED</option><option value="PROVISIONAL">PROVISIONAL — ยังไม่ยืนยันเต็มที่</option>
          </select></label>
          <label className="adminField"><span>Observed at</span><input name="observed_at" type="date" defaultValue={today} /></label>
          {qualifierKeys.length ? <details className="adminField adminFieldWide"><summary>Qualifiers (ใส่เฉพาะที่ field นี้ใช้)</summary>
            <div className="adminQuickGrid">{qualifierKeys.map((key) => <label key={key} className="adminField"><span>{key}</span><input name={`qualifier__${key}`} type="text" /></label>)}</div>
          </details> : null}
          <label className="adminField"><span>ชนิดหลักฐาน</span><select name="evidence_kind" defaultValue="OEM">
            <option value="OEM">OEM / official</option><option value="MEDIA">Media</option><option value="ADMIN">Admin manual note</option>
          </select></label>
          <label className="adminField"><span>Evidence URL (ต้องมีถ้า KNOWN)</span><input name="evidence_ref" type="text" placeholder="https://…" /></label>
          <label className="adminField"><span>วันที่ตรวจ</span><input name="reviewed_at" type="date" defaultValue={today} required /></label>
          <label className="adminField adminFieldWide"><span>เหตุผล/review note</span><input name="reason" type="text" placeholder="Official spec sheet lists this value…" required /></label>
          <div className="adminFormActions"><button className="adminPrimary">Preview diff →</button></div>
        </form>
      </details>;
    })}

    {/* ---------- Evidence ---------- */}
    {evidenceTargets.length ? <>
      <div className="adminHeader"><div><small>EVIDENCE</small><h2>Registered OEM evidence สำหรับรุ่นนี้</h2></div></div>
      <div className="adminQuickGrid">{evidenceTargets.map((target) => <a key={target.id} href={target.url} target="_blank" rel="noreferrer">
        <b>{target.sourceId}</b><span>{target.role} ↗</span><small>{target.notes || target.url}</small>
      </a>)}</div>
    </> : null}

    {/* ---------- Input queue for this vehicle ---------- */}
    <div className="adminHeader"><div><small>INPUT QUEUE</small><h2>Batch ล่าสุดที่พูดถึงรุ่นนี้</h2></div></div>
    <div className="libraryTable"><table><thead><tr>
      <th>Batch</th><th>Source</th><th>Items</th><th>Status</th><th>Result</th>
    </tr></thead><tbody>
      {relatedBatches.length ? relatedBatches.map((row) => <tr key={row.batchKey}>
        <td><b>{row.batchKey}</b><small>{new Date(row.createdAt).toLocaleString("th-TH")} · {row.actor}</small></td>
        <td>{row.sourceKind}</td><td>{row.itemCount}</td><td>{row.status}</td>
        <td>{row.pullRequestUrl ? <a href={row.pullRequestUrl} target="_blank" rel="noreferrer">PR ↗</a> : row.releaseId || row.error || "—"}</td>
      </tr>) : <tr><td colSpan={5}>ยังไม่มี batch ที่อ้างถึงรุ่นนี้ใน 60 รายการล่าสุด</td></tr>}
    </tbody></table></div>
  </div>;
}

function MarketTrimForm({
  modelId, releaseId, submittedAt, today, existing,
}: {
  modelId: string; releaseId: string; submittedAt: string; today: string;
  existing?: {
    canonicalId: string; name: string; powertrain: string;
    payload: Record<string, unknown>;
  };
}) {
  const p = (existing?.payload || {}) as any;
  return <form action={prepareMarketTrimEdit} className="adminForm">
    <input type="hidden" name="model_id" value={modelId} />
    <input type="hidden" name="page_release_id" value={releaseId} />
    <input type="hidden" name="submission_id" value={randomUUID()} />
    <input type="hidden" name="submitted_at" value={submittedAt} />
    {existing ? <input type="hidden" name="trim_id" value={existing.canonicalId} /> : null}
    <label className="adminField"><span>ชื่อ MarketTrim</span><input name="name" type="text" defaultValue={existing?.name || ""} required /></label>
    <label className="adminField"><span>Powertrain</span><select name="powertrain" defaultValue={existing?.powertrain || ""} required>
      <option value="" disabled>เลือก…</option>{MARKET_TRIM_POWERTRAINS.map((v) => <option key={v} value={v}>{v}</option>)}
    </select></label>
    <label className="adminField"><span>Drivetrain</span><select name="drivetrain" defaultValue={p.drivetrain || ""}>
      <option value="">ไม่แก้ / ไม่ระบุ</option>{DRIVETRAINS.map((v) => <option key={v} value={v}>{v}</option>)}
    </select></label>
    <label className="adminField"><span>Engine code</span><input name="engine_code" type="text" defaultValue={p.engine_code || ""} /></label>
    <label className="adminField"><span>Engine cc</span><input name="engine_cc" type="number" min="1" step="1" defaultValue={p.engine_cc || ""} /></label>
    <label className="adminField"><span>Battery kWh</span><input name="battery_kwh" type="number" min="0" step="0.1" defaultValue={p.battery_kwh || ""} /></label>
    <label className="adminField"><span>Transmission</span><input name="transmission" type="text" defaultValue={p.transmission || ""} /></label>
    <label className="adminField"><span>Seats</span><input name="seats" type="number" min="1" step="1" defaultValue={p.seats || ""} /></label>
    <label className="adminField"><span>Length mm</span><input name="length_mm" type="number" min="1" step="1" defaultValue={p.length_mm || ""} /></label>
    <label className="adminField"><span>Width mm</span><input name="width_mm" type="number" min="1" step="1" defaultValue={p.width_mm || ""} /></label>
    <label className="adminField"><span>Height mm</span><input name="height_mm" type="number" min="1" step="1" defaultValue={p.height_mm || ""} /></label>
    <label className="adminField"><span>Wheelbase mm</span><input name="wheelbase_mm" type="number" min="1" step="1" defaultValue={p.wheelbase_mm || ""} /></label>
    <label className="adminField"><span>Tire front</span><input name="tire_front" type="text" defaultValue={p.tire_front || ""} /></label>
    <label className="adminField"><span>Tire rear</span><input name="tire_rear" type="text" defaultValue={p.tire_rear || ""} /></label>
    <label className="adminField"><span>Wheel front</span><input name="wheel_front" type="text" defaultValue={p.wheel_front || ""} /></label>
    <label className="adminField"><span>Wheel rear</span><input name="wheel_rear" type="text" defaultValue={p.wheel_rear || ""} /></label>
    <label className="adminField adminFieldWide"><span>Notes</span><input name="notes" type="text" defaultValue={p.notes || ""} /></label>
    <label className="adminField"><span>ชนิดหลักฐาน</span><select name="evidence_kind" defaultValue="OEM">
      <option value="OEM">OEM / official</option><option value="MEDIA">Media</option><option value="ADMIN">Admin manual note</option>
    </select></label>
    <label className="adminField"><span>Evidence URL (ต้องมีเสมอ)</span><input name="evidence_ref" type="text" placeholder="https://…" required /></label>
    <label className="adminField"><span>วันที่ตรวจ</span><input name="reviewed_at" type="date" defaultValue={today} required /></label>
    <label className="adminField adminFieldWide"><span>เหตุผล/review note</span><input name="reason" type="text" placeholder="Official trim list / brochure confirms this configuration…" required /></label>
    <div className="adminFormActions"><button className="adminPrimary">Preview diff →</button></div>
  </form>;
}
