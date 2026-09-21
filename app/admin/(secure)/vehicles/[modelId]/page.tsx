import { randomUUID } from "node:crypto";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { currentEditor } from "@/lib/admin-auth";
import { loadVehicleWorkspace } from "@/lib/canonical-editor";
import { trimEditorFields } from "@/lib/spec-field-registry";
import { fieldAppliesTo } from "@/lib/trim-editor-fields";
import { BODY_TYPES, SEGMENTS } from "@/lib/vehicle-taxonomy";
import { prepareModelGenerationEdit } from "@/app/admin/vehicle-editor-actions";
import TrimEditorForm from "@/components/admin/TrimEditorForm";

function money(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? `${number.toLocaleString("th-TH")} บาท` : "ยังไม่มี List price";
}

const KIND_LABEL: Record<string, string> = {
  MODEL_GENERATION: "Model / Generation",
  TRIM: "MarketTrim",
};

export default async function VehicleWorkspacePage({
  params, searchParams,
}: {
  params: Promise<{ modelId: string }>;
  searchParams: Promise<{ saved?: string }>;
}) {
  const { modelId } = await params;
  const saved = (await searchParams).saved;
  const editor = await currentEditor();
  if (!editor) redirect("/admin/login");
  const workspace = await loadVehicleWorkspace(modelId);
  if (!workspace) notFound();

  const { brand, model, generation, trims, specFactsByTrim, evidenceTargets, releaseId, releaseYear } = workspace;
  const submittedAt = new Date().toISOString();
  const today = submittedAt.slice(0, 10);
  const allFields = trimEditorFields(releaseYear);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · CANONICAL VEHICLE EDITOR</small>
        <h1>{brand.nameEn} {model.nameEn}{model.nameTh ? ` · ${model.nameTh}` : ""}</h1>
        <p><code>{modelId}</code> · generation {generation?.code || "—"} · editing as <b>{editor.name}</b></p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/vehicles">← กลับรายการรถ</Link>
    </div>

    {saved ? <div className="adminSaved">
      บันทึก {KIND_LABEL[saved] || "canonical"} แล้ว — ระบบกำลังเขียนและ publish ให้อัตโนมัติ ใช้เวลาสักครู่แล้วรีเฟรช
    </div> : null}

    <nav className="adminQuickGrid" aria-label="Vehicle workspace sections">
      <a href="#model-generation"><b>Canonical vehicle</b><span>Model / Generation ↓</span></a>
      <a href="#trims"><b>Trims &amp; specs</b><span>{trims.length} trims ↓</span></a>
      {model.tdrModelId ? <a href={`/admin/models/${model.tdrModelId}/edit`}><b>Editorial</b><span>+ Industry/production context ↗</span></a> : null}
      <a href="#evidence"><b>Evidence</b><span>Registered OEM sources ↓</span></a>
    </nav>

    {/* ---------- Model / Generation ---------- */}
    <div id="model-generation" className="adminHeader"><div><small>CANONICAL</small><h2>Model / Generation</h2>
      <p>ช่องว่าง = ไม่แก้ field นั้น. Generation code คงที่เสมอเพื่อรักษา canonical identity</p>
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
      <EvidenceFields today={today} />
      <div className="adminFormActions"><button className="adminPrimary">บันทึก</button></div>
    </form>

    {/* ---------- Trims: one complete editor per trim ---------- */}
    <div id="trims" className="adminHeader"><div><small>CANONICAL</small><h2>รุ่นย่อย / Trims ({trims.length})</h2>
      <p>
        เปิดรุ่นย่อยแล้วแก้ได้ครบในฟอร์มเดียว — {allFields.length} ช่อง ตั้งแต่ระบบขับเคลื่อน แบตเตอรี่ ระยะทาง
        มิติตัวถัง ยาง ไปจนถึง ADAS. หนึ่งช่องต่อหนึ่งเรื่อง กดบันทึกครั้งเดียว ตรวจ diff เดียว เข้าคิวเป็นชุดเดียว
      </p>
    </div></div>
    <div className="libraryTable"><table><thead><tr>
      <th>Trim</th><th>Powertrain</th><th>Status</th><th>List price</th><th>Specs recorded</th>
    </tr></thead><tbody>
      {trims.length ? trims.map((trim) => <tr key={trim.canonicalId}>
        <td><a href={`#trim-${trim.canonicalId}`}><b>{trim.name}</b></a><br /><code>{trim.canonicalId}</code></td>
        <td>{trim.powertrain}</td>
        <td>{trim.status}</td>
        <td>{money(trim.currentListPrice?.amount_thb)}</td>
        <td>{(specFactsByTrim.get(trim.canonicalId) || []).length} facts</td>
      </tr>) : <tr><td colSpan={5}>ยังไม่มี MarketTrim ใต้รุ่นนี้</td></tr>}
    </tbody></table></div>

    {trims.map((trim) => <details key={trim.canonicalId} id={`trim-${trim.canonicalId}`} className="adminNotice">
      <summary><b>แก้ {trim.name}</b> · {trim.powertrain} · <code>{trim.canonicalId}</code></summary>
      <TrimEditorForm
        modelId={modelId} releaseId={releaseId} submittedAt={submittedAt}
        submissionId={randomUUID()} today={today}
        // Powertrain is part of the canonical_id, so an existing trim keeps
        // its own and the box is not offered.
        fields={allFields.filter((entry) =>
          !entry.identityLocked && fieldAppliesTo(entry, trim.powertrain))}
        current={trim.editor.editableSpecs}
        sourceRefs={trim.editor.sourceRefs}
        evidenceTargets={evidenceTargets}
        trimId={trim.canonicalId} trimName={trim.name}
      />
    </details>)}

    {generation ? <details className="adminNotice">
      <summary><b>+ เพิ่มรุ่นย่อยใหม่</b></summary>
      <p className="adminHint">
        กรอกชื่อ powertrain และสเปคให้ครบในฟอร์มเดียว แล้วกดบันทึกครั้งเดียว —
        รุ่นย่อยและสเปคทั้งหมดถูกสร้างพร้อมกันใน batch เดียว
      </p>
      <TrimEditorForm
        modelId={modelId} releaseId={releaseId} submittedAt={submittedAt}
        submissionId={randomUUID()} today={today}
        fields={allFields}
        current={{}} sourceRefs={{}} evidenceTargets={evidenceTargets}
      />
    </details> : <div className="adminNotice"><span>รุ่นนี้ไม่มี active generation — เพิ่ม/แก้รุ่นย่อยไม่ได้จนกว่าจะแก้ generation ผ่าน Advanced JSON</span></div>}

    {/* ---------- Evidence ---------- */}
    {evidenceTargets.length ? <>
      <div id="evidence" className="adminHeader"><div><small>EVIDENCE</small><h2>Registered OEM sources ของรุ่นนี้</h2>
        <p>เลือกใช้ได้จาก dropdown "เพิ่ม source" ในฟอร์ม trim ด้านบน</p>
      </div></div>
      <div className="adminQuickGrid">{evidenceTargets.map((target) => <a key={target.id} href={target.url} target="_blank" rel="noreferrer">
        <b>{target.sourceId}</b><span>{target.role} ↗</span><small>{target.notes || target.url}</small>
      </a>)}</div>
    </> : null}

  </div>;
}

/** Optional source/reason, shown once per form. Never required. */
function EvidenceFields({ today }: { today: string }) {
  return <>
    <label className="adminField"><span>ที่มา (ไม่บังคับ)</span><select name="evidence_kind" defaultValue="ADMIN">
      <option value="ADMIN">Admin / รู้เอง</option><option value="OEM">OEM / official</option><option value="MEDIA">Media</option>
    </select></label>
    <label className="adminField"><span>อ้างอิง (ไม่บังคับ — URL, ชื่อโบรชัวร์, โน้ตอะไรก็ได้)</span><input name="evidence_ref" type="text" /></label>
    <input type="hidden" name="reviewed_at" value={today} />
    <label className="adminField adminFieldWide"><span>เหตุผล (ไม่บังคับ)</span><input name="reason" type="text" placeholder="เว้นว่างได้" /></label>
  </>;
}
