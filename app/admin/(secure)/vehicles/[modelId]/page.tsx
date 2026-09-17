import { randomUUID } from "node:crypto";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { currentEditor } from "@/lib/admin-auth";
import { loadVehicleWorkspace, type WorkspaceTrim } from "@/lib/canonical-editor";
import { loadSpecFieldRegistry, fieldAppliesToPowertrain, type SpecFieldDefinition } from "@/lib/spec-field-registry";
import { BODY_TYPES, SEGMENTS, MARKET_TRIM_POWERTRAINS, DRIVETRAINS } from "@/lib/vehicle-taxonomy";
import { prepareModelGenerationEdit, prepareTrimEdit } from "@/app/admin/vehicle-editor-actions";
import type { OemEvidenceTarget } from "@/lib/price-evidence-registry";

function money(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? `${number.toLocaleString("th-TH")} บาท` : "ยังไม่มี List price";
}

const KIND_LABEL: Record<string, string> = {
  MODEL_GENERATION: "Model / Generation",
  TRIM: "MarketTrim",
};

/** The registry's 13 technical groups, folded into the four buckets a person
 * actually thinks in when they open a trim. Driven by the registry's own
 * `group`, so a new field added there lands in the right bucket by itself. */
const CATEGORY_OF_GROUP: Record<string, string> = {
  powertrain: "powertrain", performance: "powertrain", battery: "powertrain",
  efficiency: "powertrain", charging: "powertrain",
  dimensions: "body", utility: "body", chassis: "body",
  safety: "safety", comfort: "safety", technology: "safety",
  identity: "other", manufacturing: "other",
};
const CATEGORIES = [
  { key: "powertrain", title: "Powertrain & Performance", hint: "ระบบขับเคลื่อน แรงม้า แรงบิด แบตเตอรี่ การชาร์จ" },
  { key: "body", title: "Body, Chassis & Wheels", hint: "มิติตัวถัง ที่นั่ง ยาง ล้อ ช่วงล่าง" },
  { key: "safety", title: "Safety, ADAS & Comfort", hint: "ถุงลม ADAS ระบบช่วยขับ ออปชันความสบาย" },
  { key: "other", title: "Other", hint: "รุ่นปี โรงงานผลิต และข้อมูลอื่น" },
] as const;

export default async function VehicleWorkspacePage({
  params, searchParams,
}: {
  params: Promise<{ modelId: string }>;
  searchParams: Promise<{ queued?: string; kind?: string }>;
}) {
  const { modelId } = await params;
  const query = await searchParams;
  const editor = await currentEditor();
  if (!editor) redirect("/admin/login");
  const workspace = await loadVehicleWorkspace(modelId);
  if (!workspace) notFound();

  const { brand, model, generation, trims, specFactsByTrim, evidenceTargets, relatedBatches, releaseId, releaseYear } = workspace;
  const submittedAt = new Date().toISOString();
  const today = submittedAt.slice(0, 10);
  const registry = loadSpecFieldRegistry(releaseYear);

  return <div className="adminEditor">
    <div className="adminHeader">
      <div>
        <small>VEHICLE MASTER · CANONICAL VEHICLE EDITOR</small>
        <h1>{brand.nameEn} {model.nameEn}{model.nameTh ? ` · ${model.nameTh}` : ""}</h1>
        <p><code>{modelId}</code> · generation {generation?.code || "—"} · active release <code>{releaseId}</code> · editing as <b>{editor.name}</b></p>
      </div>
      <Link className="adminPrimaryLink" href="/admin/vehicles">← กลับรายการรถ</Link>
    </div>

    {query.queued ? <div className="adminSaved">
      บันทึก {KIND_LABEL[query.kind || ""] || "canonical"} เข้าคิวแล้ว — ข้อมูลจะขึ้นจริงหลัง PR ถูก merge และ release ใหม่ถูก publish (ดูสถานะที่ตาราง Input queue ด้านล่าง)
    </div> : null}

    <nav className="adminQuickGrid" aria-label="Vehicle workspace sections">
      <a href="#model-generation"><b>Canonical vehicle</b><span>Model / Generation ↓</span></a>
      <a href="#trims"><b>Trims &amp; specs</b><span>{trims.length} trims ↓</span></a>
      <a href={`/admin/vehicle-input?model=${encodeURIComponent(modelId)}`}><b>Prices</b><span>Price Bench ↗</span></a>
      <a href={`/admin/retail-lifecycle?model=${encodeURIComponent(modelId)}`}><b>Lifecycle</b><span>Retail lifecycle review ↗</span></a>
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
      <div className="adminFormActions"><button className="adminPrimary">ตรวจก่อนบันทึก →</button></div>
    </form>

    {/* ---------- Trims: one complete editor per trim ---------- */}
    <div id="trims" className="adminHeader"><div><small>CANONICAL</small><h2>MarketTrims ({trims.length})</h2>
      <p>
        เปิด trim แล้วแก้ได้ครบในที่เดียว — ทั้งข้อมูล trim เอง (ยาง ล้อ ที่นั่ง เครื่อง แบต) และสเปคเทียบ
        ({registry.length} fields: แรงม้า แรงบิด ADAS ฯลฯ) กดบันทึกครั้งเดียว เข้าคิวเป็นชุดเดียว
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
      <TrimEditor
        modelId={modelId} releaseId={releaseId} submittedAt={submittedAt} today={today}
        registry={registry} evidenceTargets={evidenceTargets} existing={trim}
        currentSpecs={specFactsByTrim.get(trim.canonicalId) || []}
      />
    </details>)}

    {generation ? <details className="adminNotice">
      <summary><b>+ เพิ่ม MarketTrim ใหม่</b></summary>
      <p className="adminHint">สร้าง trim ก่อน แล้วค่อยเปิดกลับมาแก้เพื่อใส่สเปคละเอียด (แรงม้า แรงบิด ADAS) — สเปคต้องผูกกับ trim ที่มี id แล้ว</p>
      <TrimEditor
        modelId={modelId} releaseId={releaseId} submittedAt={submittedAt} today={today}
        registry={registry} evidenceTargets={evidenceTargets} currentSpecs={[]}
      />
    </details> : <div className="adminNotice"><span>รุ่นนี้ไม่มี active generation — เพิ่ม/แก้ MarketTrim ไม่ได้จนกว่าจะแก้ generation ผ่าน Advanced JSON</span></div>}

    {/* ---------- Evidence ---------- */}
    {evidenceTargets.length ? <>
      <div id="evidence" className="adminHeader"><div><small>EVIDENCE</small><h2>Registered OEM sources ของรุ่นนี้</h2>
        <p>เลือกใช้ได้จาก dropdown "เพิ่ม source" ในฟอร์ม trim ด้านบน</p>
      </div></div>
      <div className="adminQuickGrid">{evidenceTargets.map((target) => <a key={target.id} href={target.url} target="_blank" rel="noreferrer">
        <b>{target.sourceId}</b><span>{target.role} ↗</span><small>{target.notes || target.url}</small>
      </a>)}</div>
    </> : null}

    {/* ---------- Input queue ---------- */}
    <div className="adminHeader"><div><small>INPUT QUEUE</small><h2>Batch ล่าสุดที่พูดถึงรุ่นนี้</h2>
      <p>QUEUED = รอ worker ดึงไปทำ (ทุก ~10 นาที) · STAGED = เปิด PR แล้ว รอ merge · PUBLISHED = ขึ้น release จริงแล้ว</p>
    </div></div>
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

function ClearToggle({ name }: { name: string }) {
  return <label className="adminClearToggle"><input type="checkbox" name={`clear_${name}`} /> ล้างค่า</label>;
}

function TrimField({
  existing, name, label, type, min, step, defaultValue, wide,
}: {
  existing: boolean; name: string; label: string; type: "text" | "number";
  min?: string; step?: string; defaultValue: string; wide?: boolean;
}) {
  return <label className={wide ? "adminField adminFieldWide" : "adminField"}>
    <span>{label}</span>
    <input name={name} type={type} min={min} step={step} defaultValue={defaultValue} />
    {existing ? <ClearToggle name={name} /> : null}
  </label>;
}

/** One comparable-spec field, rendered from its registry definition: a value
 * input (blank = ไม่แก้) plus an explicit "ไม่มี/ไม่เกี่ยว" box that records
 * NOT_APPLICABLE instead of silently writing a zero or a false. */
function SpecField({ definition, current }: {
  definition: SpecFieldDefinition;
  current?: { value_state: string; value: unknown };
}) {
  const known = current?.value_state === "KNOWN";
  const label = `${definition.labelEn}${definition.canonicalUnit ? ` (${definition.canonicalUnit})` : ""}`;
  const naDefault = current?.value_state === "NOT_APPLICABLE";
  const name = `spec__${definition.key}`;
  const shared = <>
    <small>{definition.labelTh}{current ? ` · ตอนนี้: ${known ? String(current.value) : current.value_state}` : ""}</small>
    <label className="adminClearToggle"><input type="checkbox" name={`spec_na__${definition.key}`} defaultChecked={naDefault} /> ไม่มี/ไม่เกี่ยว</label>
  </>;

  if (definition.valueType === "BOOLEAN") {
    return <label className="adminField"><span>{label}</span>
      <select name={name} defaultValue={known ? String(current!.value) : ""}>
        <option value="">ไม่แก้</option><option value="true">มี</option><option value="false">ไม่มี</option>
      </select>{shared}
    </label>;
  }
  return <label className="adminField"><span>{label}</span>
    <input
      name={name}
      type={definition.valueType === "NUMBER" ? "number" : "text"}
      step={definition.valueType === "NUMBER" ? "any" : undefined}
      min={definition.valueType === "NUMBER" ? "0" : undefined}
      defaultValue={known ? String(Array.isArray(current!.value) ? current!.value.join(", ") : current!.value) : ""}
    />{shared}
  </label>;
}

function TrimEditor({
  modelId, releaseId, submittedAt, today, registry, evidenceTargets, existing, currentSpecs,
}: {
  modelId: string; releaseId: string; submittedAt: string; today: string;
  registry: SpecFieldDefinition[];
  evidenceTargets: OemEvidenceTarget[];
  existing?: WorkspaceTrim;
  currentSpecs: Array<{ fieldKey: string; payload: Record<string, unknown> }>;
}) {
  const p = (existing?.payload || {}) as any;
  const isExisting = Boolean(existing);
  const powertrain = existing?.powertrain || "";
  const existingRefs = existing?.sourceRefs || {};
  const existingRefRows = Object.entries(existingRefs).flatMap(([kind, urls]) => urls.map((url) => ({ kind, url })));
  const currentSpecByKey: Record<string, { value_state: string; value: unknown }> = {};
  for (const fact of currentSpecs) {
    currentSpecByKey[fact.fieldKey] = {
      value_state: String((fact.payload as any)?.value_state || "UNKNOWN"),
      value: (fact.payload as any)?.value ?? null,
    };
  }
  // Only specs that apply to this trim's powertrain, bucketed into the four
  // human categories. A brand-new trim has no id yet, so it gets none.
  const specsByCategory: Record<string, SpecFieldDefinition[]> = { powertrain: [], body: [], safety: [], other: [] };
  if (isExisting) {
    for (const definition of registry) {
      if (!fieldAppliesToPowertrain(definition, powertrain)) continue;
      const category = CATEGORY_OF_GROUP[definition.group] || "other";
      specsByCategory[category].push(definition);
    }
  }

  const ownFields: Record<string, React.ReactNode[]> = {
    powertrain: [
      <label key="dt" className="adminField"><span>Drivetrain</span>
        <select name="drivetrain" defaultValue={p.drivetrain || ""}>
          <option value="">ไม่แก้</option>{DRIVETRAINS.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>{isExisting ? <ClearToggle name="drivetrain" /> : null}
      </label>,
      <TrimField key="ec" existing={isExisting} name="engine_code" label="Engine code" type="text" defaultValue={p.engine_code || ""} />,
      <TrimField key="cc" existing={isExisting} name="engine_cc" label="Engine cc" type="number" min="1" step="1" defaultValue={p.engine_cc || ""} />,
      <TrimField key="bk" existing={isExisting} name="battery_kwh" label="Battery kWh" type="number" min="0" step="0.1" defaultValue={p.battery_kwh || ""} />,
      <TrimField key="tm" existing={isExisting} name="transmission" label="Transmission" type="text" defaultValue={p.transmission || ""} />,
    ],
    body: [
      <TrimField key="st" existing={isExisting} name="seats" label="Seats" type="number" min="1" step="1" defaultValue={p.seats || ""} />,
      <TrimField key="l" existing={isExisting} name="length_mm" label="Length mm" type="number" min="1" step="1" defaultValue={p.length_mm || ""} />,
      <TrimField key="w" existing={isExisting} name="width_mm" label="Width mm" type="number" min="1" step="1" defaultValue={p.width_mm || ""} />,
      <TrimField key="h" existing={isExisting} name="height_mm" label="Height mm" type="number" min="1" step="1" defaultValue={p.height_mm || ""} />,
      <TrimField key="wb" existing={isExisting} name="wheelbase_mm" label="Wheelbase mm" type="number" min="1" step="1" defaultValue={p.wheelbase_mm || ""} />,
      <TrimField key="tf" existing={isExisting} name="tire_front" label="Tire front" type="text" defaultValue={p.tire_front || ""} />,
      <TrimField key="tr" existing={isExisting} name="tire_rear" label="Tire rear" type="text" defaultValue={p.tire_rear || ""} />,
      <TrimField key="wf" existing={isExisting} name="wheel_front" label="Wheel front" type="text" defaultValue={p.wheel_front || ""} />,
      <TrimField key="wr" existing={isExisting} name="wheel_rear" label="Wheel rear" type="text" defaultValue={p.wheel_rear || ""} />,
    ],
    safety: [],
    other: [],
  };

  return <form action={prepareTrimEdit} className="adminForm">
    <input type="hidden" name="model_id" value={modelId} />
    <input type="hidden" name="page_release_id" value={releaseId} />
    <input type="hidden" name="submission_id" value={randomUUID()} />
    <input type="hidden" name="submitted_at" value={submittedAt} />
    {existing ? <input type="hidden" name="trim_id" value={existing.canonicalId} /> : null}

    <label className="adminField"><span>ชื่อ MarketTrim</span><input name="name" type="text" defaultValue={existing?.name || ""} required /></label>
    <label className="adminField"><span>Powertrain</span><select name="powertrain" defaultValue={powertrain} required>
      <option value="" disabled>เลือก…</option>{MARKET_TRIM_POWERTRAINS.map((v) => <option key={v} value={v}>{v}</option>)}
    </select></label>

    {CATEGORIES.map((category) => {
      const own = ownFields[category.key] || [];
      const specs = specsByCategory[category.key] || [];
      if (!own.length && !specs.length) return null;
      return <details key={category.key} className="adminFieldWide adminNotice" open>
        <summary><b>{category.title}</b> — {category.hint}</summary>
        <div className="adminEmbeddedGrid">
          {own}
          {specs.map((definition) => <SpecField key={definition.key} definition={definition} current={currentSpecByKey[definition.key]} />)}
        </div>
      </details>;
    })}

    <TrimField existing={isExisting} name="notes" label="Notes" type="text" defaultValue={p.notes || ""} wide />

    <details className="adminFieldWide adminNotice">
      <summary><b>Source refs</b> ({existingRefRows.length})</summary>
      {existingRefRows.length ? <div className="adminEmbeddedGrid">{existingRefRows.map(({ kind, url }) => <label key={`${kind}::${url}`} className="adminField">
        <span><input type="checkbox" name="remove_source" value={`${kind}::${url}`} /> ลบ</span>
        <small>{kind} · <a href={url} target="_blank" rel="noreferrer">{url}</a></small>
      </label>)}</div> : <p className="adminHint">ยังไม่มี source ref</p>}
      {[1, 2].map((row) => <div key={row} className="adminEmbeddedGrid">
        <label className="adminField"><span>เพิ่ม source {row} — จาก registry</span><select name={`new_source_target_${row}`} defaultValue="">
          <option value="">— ไม่ใช้ —</option>
          {evidenceTargets.map((target) => <option key={target.id} value={target.id}>{target.sourceId} · {target.role}</option>)}
        </select></label>
        <label className="adminField"><span>หรือพิมพ์เอง — kind</span><input name={`new_source_kind_${row}`} type="text" placeholder="ecosticker, official_brandsite…" /></label>
        <label className="adminField"><span>URL / อ้างอิง</span><input name={`new_source_ref_${row}`} type="text" /></label>
      </div>)}
    </details>

    <EvidenceFields today={today} />
    {isExisting ? <p className="adminHint adminFieldWide">เว้นว่าง = ไม่แก้ field นั้น · ติ๊ก "ล้างค่า"/"ไม่มี/ไม่เกี่ยว" = ลบค่าเดิมออกจริง</p> : null}
    <div className="adminFormActions"><button className="adminPrimary">ตรวจก่อนบันทึก →</button></div>
  </form>;
}
