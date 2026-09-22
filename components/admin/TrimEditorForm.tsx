"use client";

/**
 * One trim = one form.
 *
 * Every box here is one concept the admin recognises -- Seats, Drivetrain,
 * Battery capacity, Range -- and there is exactly one of each. Which backend a
 * value lands in (MarketTrim's own column, a comparable-spec fact, or both) is
 * decided by lib/trim-editor-fields.ts and never shown; the admin is editing a
 * car, not a storage layout.
 *
 * It is a client component for one reason: validation. The same
 * validateFieldValue the server action runs is called here on blur, so a value
 * the form accepts is a value the canonical writer accepts. That is what stops
 * the old failure where the UI took battery capacity 0 and the pipeline
 * rejected the whole batch minutes later, in a place the admin never saw.
 */
import { useActionState, useState } from "react";
import {
  fieldsByCategory, validateFieldValue, EMPTY_TRIM_EDIT_STATE,
  valueInputName, naInputName, qualifierInputName,
  type TrimEditorField, type QualifierDefinition,
} from "@/lib/trim-editor-fields";
import type { EditableField } from "@/lib/trim-editor-state";
import { prepareTrimEdit } from "@/app/admin/vehicle-editor-actions";
import { deleteCanonicalTrim } from "@/app/admin/trim-delete-actions";
import type { OemEvidenceTarget } from "@/lib/price-evidence-registry";

type TrimEditorFormProps = {
  modelId: string;
  releaseId: string;
  submittedAt: string;
  submissionId: string;
  today: string;
  fields: TrimEditorField[];
  current: Record<string, EditableField>;
  sourceRefs: Record<string, string[]>;
  evidenceTargets: OemEvidenceTarget[];
  trimId?: string;
  trimName?: string;
  /** Present only when this "+ เพิ่มรุ่นย่อยใหม่" form was opened from an
   *  Exceptions row (/admin/vehicles/new's grain=TRIM path): carries the
   *  exception back through the save so prepareTrimEdit can redirect to
   *  /admin/exceptions instead of this page, with the new trim preselected
   *  there once it publishes. Never set for an edit of an existing trim. */
  returnContext?: {
    exceptionIds: string; rawBrand: string; rawModel: string;
    registrationType: string; grain: string;
  };
};

function QualifierInput({ fieldKey, qualifier, value }: {
  fieldKey: string; qualifier: QualifierDefinition; value: string;
}) {
  const name = qualifierInputName(fieldKey, qualifier.key);
  if (qualifier.input === "enum" && qualifier.options?.length) {
    return <label className="trimQualifier">
      <span>{qualifier.labelEn}</span>
      <select name={name} defaultValue={value}>
        <option value="">—</option>
        {qualifier.options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>;
  }
  return <label className="trimQualifier">
    <span>{qualifier.labelEn}</span>
    <input name={name} type={qualifier.input === "number" ? "number" : "text"}
      step={qualifier.input === "number" ? "any" : undefined} defaultValue={value} />
  </label>;
}

function FieldRow({ field, current, serverError }: {
  field: TrimEditorField;
  current: EditableField;
  serverError?: string;
}) {
  const [localError, setLocalError] = useState("");
  const [notApplicable, setNotApplicable] = useState(current.valueState === "NOT_APPLICABLE");
  const error = serverError || localError;
  const name = valueInputName(field.key);

  function check(raw: string) {
    const result = validateFieldValue(field, raw);
    setLocalError(result.ok ? "" : result.message);
  }

  const common = {
    name,
    defaultValue: current.value,
    disabled: notApplicable,
    "aria-invalid": error ? true : undefined,
    onBlur: (event: React.FocusEvent<HTMLInputElement | HTMLSelectElement>) =>
      check(event.target.value),
  };

  return <div className={`trimField${error ? " trimFieldError" : ""}`}>
    <label>
      <span className="trimFieldLabel">
        {field.labelEn}{field.unit ? <em> ({field.unit})</em> : null}
      </span>
      {field.input === "enum" && field.options.length
        ? <select {...common}>
            <option value="">—</option>
            {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
        : field.input === "boolean"
          ? <select {...common}>
              <option value="">—</option>
              <option value="true">มี</option>
              <option value="false">ไม่มี</option>
            </select>
          : <input {...common}
              type={field.input === "number" ? "number" : "text"}
              step={field.input === "number" ? (field.integer ? "1" : "any") : undefined}
              min={field.input === "number" ? (field.positive ? undefined : "0") : undefined}
              placeholder={field.placeholder} />}
      <small className="trimFieldHint">{field.labelTh}{field.help ? ` · ${field.help}` : ""}</small>
    </label>

    {/* Qualifiers are part of the fact's identity, not decoration: a range of
        442 km measured on NEDC is a different fact from 442 km on WLTP, so
        they sit beside the value rather than behind a dialog. */}
    {field.qualifiers.length && !notApplicable ? <div className="trimQualifiers">
      {field.qualifiers.map((qualifier) => <QualifierInput
        key={qualifier.key} fieldKey={field.key} qualifier={qualifier}
        value={current.qualifiers[qualifier.key] || ""} />)}
    </div> : null}

    <label className="trimNotApplicable">
      <input type="checkbox" name={naInputName(field.key)}
        defaultChecked={current.valueState === "NOT_APPLICABLE"}
        onChange={(event) => setNotApplicable(event.target.checked)} />
      ไม่มีในรุ่นนี้
    </label>
    {error ? <p className="trimFieldMessage" role="alert">{error}</p> : null}
  </div>;
}

export default function TrimEditorForm(props: TrimEditorFormProps) {
  const [state, action, pending] = useActionState(prepareTrimEdit, EMPTY_TRIM_EDIT_STATE);
  const groups = fieldsByCategory(props.fields);
  const refRows = Object.entries(props.sourceRefs)
    .flatMap(([kind, urls]) => urls.map((url) => ({ kind, url })));

  return <form action={action} className="trimForm">
    <input type="hidden" name="model_id" value={props.modelId} />
    <input type="hidden" name="page_release_id" value={props.releaseId} />
    <input type="hidden" name="submission_id" value={props.submissionId} />
    <input type="hidden" name="submitted_at" value={props.submittedAt} />
    <input type="hidden" name="reviewed_at" value={props.today} />
    {props.trimId ? <input type="hidden" name="trim_id" value={props.trimId} /> : null}
    {props.returnContext ? <>
      <input type="hidden" name="return" value="exceptions" />
      <input type="hidden" name="exception_ids" value={props.returnContext.exceptionIds} />
      <input type="hidden" name="raw_brand" value={props.returnContext.rawBrand} />
      <input type="hidden" name="raw_model" value={props.returnContext.rawModel} />
      <input type="hidden" name="registration_type" value={props.returnContext.registrationType} />
      <input type="hidden" name="grain" value={props.returnContext.grain} />
    </> : null}

    {state.formError ? <p className="trimFormError" role="alert">{state.formError}</p> : null}

    {groups.map((group) => <section key={group.category.id} className="trimSection">
      <h3>{group.category.labelEn} <em>{group.category.labelTh}</em></h3>
      <div className="trimGrid">
        {group.fields.map((field) => <FieldRow
          key={field.key} field={field}
          current={props.current[field.key]
            || { value: "", valueState: "UNKNOWN", qualifiers: {}, origin: "none" }}
          serverError={state.fieldErrors[field.key]} />)}
      </div>
    </section>)}

    {/* One source context for the whole edit, chosen once and inherited by
        every field. Optional -- nothing downstream requires it. */}
    <section className="trimSection">
      <h3>ที่มาของข้อมูล <em>ไม่บังคับ · ใช้กับทุก field ที่แก้ในครั้งนี้</em></h3>
      <div className="trimGrid">
        <div className="trimField"><label>
          <span className="trimFieldLabel">ประเภทแหล่งข้อมูล</span>
          <select name="evidence_kind" defaultValue="ADMIN">
            <option value="ADMIN">Admin / รู้เอง</option>
            <option value="OEM">OEM / official</option>
            <option value="MEDIA">Media</option>
          </select>
        </label></div>
        <div className="trimField"><label>
          <span className="trimFieldLabel">อ้างอิง</span>
          <input name="evidence_ref" type="text" placeholder="URL, ชื่อโบรชัวร์, โน้ต — เว้นว่างได้" />
        </label></div>
        <div className="trimField"><label>
          <span className="trimFieldLabel">เหตุผล</span>
          <input name="reason" type="text" placeholder="เว้นว่างได้" />
        </label></div>
      </div>

      <details className="trimSourceRefs">
        <summary>Source references ({refRows.length}) — สำหรับงานดูแล ID ต้นทาง</summary>
        {refRows.length ? <div className="trimGrid">{refRows.map(({ kind, url }) =>
          <label key={`${kind}::${url}`} className="trimField">
            <span className="trimFieldLabel">
              <input type="checkbox" name="remove_source" value={`${kind}::${url}`} /> ลบ
            </span>
            <small>{kind} · {url}</small>
          </label>)}</div> : <p className="trimFieldHint">ยังไม่มี source ref</p>}
        {[1, 2].map((row) => <div key={row} className="trimGrid">
          <label className="trimField"><span className="trimFieldLabel">เพิ่มจาก registry</span>
            <select name={`new_source_target_${row}`} defaultValue="">
              <option value="">— ไม่ใช้ —</option>
              {props.evidenceTargets.map((target) =>
                <option key={target.id} value={target.id}>{target.sourceId} · {target.role}</option>)}
            </select>
          </label>
          <label className="trimField"><span className="trimFieldLabel">หรือพิมพ์เอง — kind</span>
            <input name={`new_source_kind_${row}`} type="text" placeholder="ecosticker, official_brandsite…" />
          </label>
          <label className="trimField"><span className="trimFieldLabel">URL / อ้างอิง</span>
            <input name={`new_source_ref_${row}`} type="text" />
          </label>
        </div>)}
      </details>
    </section>

    <div className="adminFormActions">
      <button className="adminPrimary" disabled={pending}>
        {pending ? "กำลังตรวจ…" : "ตรวจก่อนบันทึก →"}
      </button>
      {props.trimId ? <button
        type="submit"
        formAction={deleteCanonicalTrim}
        formNoValidate
        disabled={pending}
        onClick={(event) => {
          const label = props.trimName || props.trimId || "รุ่นย่อยนี้";
          if (!window.confirm(`ลบ ${label} ออกจาก canonical Vehicle Master จริงหรือไม่?\n\nลบได้เฉพาะ trim ที่ยังไม่มีราคา สเปค หรือข้อมูลจดทะเบียนผูกอยู่`)) {
            event.preventDefault();
          }
        }}
      >ลบรุ่นย่อย</button> : null}
    </div>
  </form>;
}