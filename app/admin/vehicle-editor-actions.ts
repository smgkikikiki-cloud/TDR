"use server";

/**
 * Server actions behind the Canonical Vehicle Editor (/admin/vehicles/[id]).
 *
 * Two edit surfaces, both one-shot:
 *   prepareModelGenerationEdit -> the model's own taxonomy (name, body type,
 *                                 segment, seats, launched/ended).
 *   prepareTrimEdit            -> ONE trim, whole: its MarketTrim fields AND
 *                                 its comparable-spec facts in a single form,
 *                                 a single diff, a single queued batch.
 *
 * Both build a canonical batch, store it as a PENDING_REVIEW proposal
 * (lib/edit-session-store.ts) and redirect to /review/[proposalId] with an
 * opaque id only. confirmEditProposal is the one path into the real queue:
 * load -> re-check the active release -> enqueue -> consume, relying on
 * enqueueCanonicalInputBatch's (batch_key, payload-hash) idempotency so a
 * retry after a transient failure resolves to the same batch instead of
 * losing the edit.
 *
 * Reason and evidence are optional everywhere. Nothing downstream requires
 * them (both CanonicalInputBatch.from_dict and CanonicalWriteCommand.from_dict
 * accept an empty reason, and SpecFieldDefinition.validate_value never looks
 * at source_ref), so the editor records them when given and never blocks a
 * save on them. Actor and timestamp stay automatic and mandatory -- they cost
 * the editor nothing and keep the canonical revision trail attributable.
 */
import { redirect } from "next/navigation";
import { currentEditor, isAdmin, type AdminEditor } from "@/lib/admin-auth";
import { field, requiredField, isoDate, safeSubmissionId, submissionTimestamp } from "@/lib/admin-form";
import {
  buildModelGenerationBatch, buildTrimEditBatch, diffPatch, diffTrimEdit,
  findDuplicateMarketTrim, isStaleRelease, applySourceRefEdits,
  type Evidence, type EvidenceKind, type MarketTrimFields,
  type SpecFactValueState, type TrimSpecEntry, type SourceRefEdit,
} from "@/lib/canonical-command-builder";
import { loadVehicleWorkspace, liveModelReleaseId } from "@/lib/canonical-editor";
import { createProposal, loadProposal, consumeProposal } from "@/lib/edit-session-store";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { loadSpecFieldRegistry, fieldAppliesToPowertrain, type SpecFieldDefinition } from "@/lib/spec-field-registry";
import { MARKET_TRIM_POWERTRAINS } from "@/lib/vehicle-taxonomy";

const EVIDENCE_KINDS = new Set<EvidenceKind>(["ADMIN", "OEM", "MEDIA"]);
const SOURCE_KIND_TOKEN = /^[a-z][a-z0-9_]{0,63}$/;

const TRIM_FIELD_LABELS: Record<string, string> = {
  name: "Name", powertrain: "Powertrain", drivetrain: "Drivetrain", engine_code: "Engine code",
  engine_cc: "Engine cc", battery_kwh: "Battery kWh", transmission: "Transmission", seats: "Seats",
  length_mm: "Length mm", width_mm: "Width mm", height_mm: "Height mm", wheelbase_mm: "Wheelbase mm",
  tire_front: "Tire front", tire_rear: "Tire rear", wheel_front: "Wheel front", wheel_rear: "Wheel rear",
  notes: "Notes", source_refs: "Source refs",
};

async function requireEditor(): Promise<AdminEditor> {
  const editor = await currentEditor();
  if (!editor) redirect("/admin/login");
  return editor;
}

/** Evidence is entirely optional: kind defaults to ADMIN, the reference is
 * free text (a URL, a brochure name, "confirmed at the dealer"), and the
 * review date defaults to today. Nothing here can reject a save. */
function readEvidence(formData: FormData): Evidence {
  const rawKind = field(formData, "evidence_kind").toUpperCase() as EvidenceKind;
  const sourceKind = EVIDENCE_KINDS.has(rawKind) ? rawKind : "ADMIN";
  const sourceRef = field(formData, "evidence_ref") || undefined;
  const reviewedAt = isoDate(field(formData, "reviewed_at"), "วันที่ตรวจ") || new Date().toISOString().slice(0, 10);
  return { sourceKind, sourceRef, reviewedAt };
}

async function loadWorkspaceOrThrow(modelId: string) {
  const workspace = await loadVehicleWorkspace(modelId);
  if (!workspace) throw new Error("ไม่พบ canonical model นี้ใน active release");
  return workspace;
}

function assertNotStale(pageReleaseId: string, liveReleaseId: string) {
  if (isStaleRelease(pageReleaseId, liveReleaseId)) {
    throw new Error(
      "มี canonical release ใหม่ออกมาระหว่างที่เปิดหน้านี้ ข้อมูลบนหน้าจอจึงอาจไม่ตรงกับของจริงแล้ว "
      + "กรุณากด refresh หน้านี้แล้วแก้ไขใหม่อีกครั้ง (กันการเขียนทับข้อมูลที่เพิ่งอัปเดตไป)",
    );
  }
}

export async function prepareModelGenerationEdit(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const modelId = requiredField(formData, "model_id", "canonical model");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  assertNotStale(pageReleaseId, workspace.releaseId);
  if (!workspace.generation) throw new Error("รุ่นนี้ไม่มี active generation ให้แก้ผ่าน editor");

  const nameEn = field(formData, "name_en");
  const nameTh = field(formData, "name_th");
  const bodyType = field(formData, "body_type").toUpperCase();
  const segment = field(formData, "segment").toUpperCase();
  const seats = field(formData, "seats");
  const launched = isoDate(field(formData, "launched"), "วันเริ่มขาย");
  const ended = isoDate(field(formData, "ended"), "วันยุติขาย");

  const modelPatch: Record<string, unknown> = {};
  if (nameEn && nameEn !== workspace.model.nameEn) modelPatch.name_en = nameEn;
  if (nameTh && nameTh !== workspace.model.nameTh) modelPatch.name_th = nameTh;
  if (bodyType && bodyType !== workspace.model.bodyType) modelPatch.body_type = bodyType;
  const generationPatch: Record<string, unknown> = {};
  if (segment && segment !== workspace.generation.segment) generationPatch.segment = segment;
  if (seats) {
    const seatsNumber = Number(seats);
    if (!Number.isInteger(seatsNumber) || seatsNumber <= 0) throw new Error("จำนวนที่นั่งต้องเป็นจำนวนเต็มบวก");
    if (seatsNumber !== (workspace.generation as any).seats) generationPatch.seats = seatsNumber;
  }
  if (launched && launched !== workspace.generation.launched) generationPatch.launched = launched;
  if (ended && ended !== workspace.generation.ended) generationPatch.ended = ended;
  if (!Object.keys(modelPatch).length && !Object.keys(generationPatch).length) {
    throw new Error("ไม่มีอะไรเปลี่ยน — แก้อย่างน้อย 1 ช่องก่อนกดบันทึก");
  }

  const reason = field(formData, "reason");
  const evidence = readEvidence(formData);
  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);

  const { payload } = buildModelGenerationBatch({
    batchId: `admin-vehicle-model-${submissionId}`,
    year: workspace.releaseYear,
    submittedAt,
    reason,
    evidence,
    canonicalModelId: modelId,
    brand: { id: workspace.brand.canonicalId, nameEn: workspace.brand.nameEn, nameTh: workspace.brand.nameTh || undefined },
    generationCode: workspace.generation.code,
    modelPatch,
    generationPatch,
  });
  const diff = [
    ...diffPatch(
      { name_en: workspace.model.nameEn, name_th: workspace.model.nameTh, body_type: workspace.model.bodyType },
      modelPatch,
      { name_en: "Model name (EN)", name_th: "ชื่อรุ่น (TH)", body_type: "Body type" },
    ),
    ...diffPatch(
      { segment: workspace.generation.segment, seats: (workspace.generation as any).seats, launched: workspace.generation.launched, ended: workspace.generation.ended },
      generationPatch,
      { segment: "Segment", seats: "Seats", launched: "Launched", ended: "Ended" },
    ),
  ];

  const proposalId = await createProposal({
    kind: "MODEL_GENERATION", modelId, actor: editor.name, pageReleaseId,
    batchPayload: payload, diff, reason: payload.reason, evidence,
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}/review/${encodeURIComponent(proposalId)}`);
}

function readSourceRefEdits(formData: FormData): { remove: SourceRefEdit[]; add: SourceRefEdit[] } {
  const remove: SourceRefEdit[] = formData.getAll("remove_source")
    .filter((value): value is string => typeof value === "string" && value.includes("::"))
    .map((value) => {
      const separator = value.indexOf("::");
      return { kind: value.slice(0, separator), url: value.slice(separator + 2) };
    });

  const add: SourceRefEdit[] = [];
  for (let index = 1; index <= 2; index += 1) {
    const targetId = field(formData, `new_source_target_${index}`);
    const manualKind = field(formData, `new_source_kind_${index}`).toLowerCase();
    const manualRef = field(formData, `new_source_ref_${index}`);
    if (targetId) {
      add.push({ kind: targetId, url: "" }); // resolved by the caller, which knows modelId
    } else if (manualRef) {
      const kind = manualKind || "admin";
      if (!SOURCE_KIND_TOKEN.test(kind)) {
        throw new Error(`source kind แถวที่ ${index} ต้องเป็น a-z/0-9/_ (เช่น official_brandsite, ecosticker)`);
      }
      add.push({ kind, url: manualRef });
    }
  }
  return { remove, add };
}

function parseSpecValue(definition: SpecFieldDefinition, raw: string): string | number | boolean | string[] {
  if (definition.valueType === "NUMBER") {
    const num = Number(raw);
    if (!Number.isFinite(num) || num < 0) throw new Error(`${definition.labelEn} ต้องเป็นตัวเลขที่ไม่ติดลบ`);
    return num;
  }
  if (definition.valueType === "BOOLEAN") {
    if (raw !== "true" && raw !== "false") throw new Error(`${definition.labelEn} ต้องเป็น มี/ไม่มี`);
    return raw === "true";
  }
  if (definition.valueType === "SET") {
    const items = raw.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
    if (!items.length) throw new Error(`${definition.labelEn} ต้องมีอย่างน้อย 1 ค่า`);
    return items;
  }
  return raw;
}

/**
 * ONE trim, edited whole. The form carries the MarketTrim's own fields and
 * every applicable comparable-spec field side by side; this action turns
 * whatever actually changed into one batch (an UPSERT_MODEL_BUNDLE for the
 * trim patch plus one APPEND_SPEC per changed spec fact) and one diff.
 *
 * Fields the admin left alone produce nothing at all: a blank input is
 * "untouched", a filled input that matches the current value is skipped, and
 * only an explicit clear/NA checkbox writes an emptied value.
 */
export async function prepareTrimEdit(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const modelId = requiredField(formData, "model_id", "canonical model");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  assertNotStale(pageReleaseId, workspace.releaseId);
  if (!workspace.generation) throw new Error("รุ่นนี้ไม่มี active generation ให้เพิ่ม/แก้ MarketTrim");

  const existingTrimId = field(formData, "trim_id") || undefined;
  const existing = existingTrimId ? workspace.trims.find((row) => row.canonicalId === existingTrimId) : undefined;
  if (existingTrimId && !existing) throw new Error("MarketTrim นี้ไม่อยู่ใต้ canonical model ที่เลือก");

  const name = requiredField(formData, "name", "ชื่อ MarketTrim");
  const powertrain = requiredField(formData, "powertrain", "powertrain").toUpperCase();
  if (!MARKET_TRIM_POWERTRAINS.includes(powertrain as any)) throw new Error("powertrain ไม่อยู่ใน canonical taxonomy");

  const duplicate = findDuplicateMarketTrim(
    workspace.trims.map((row) => ({ canonicalId: row.canonicalId, generationId: row.generationId, name: row.name, powertrain: row.powertrain })),
    { generationId: workspace.generation.canonicalId, name, powertrain, excludeCanonicalId: existingTrimId },
  );
  if (duplicate) {
    throw new Error(`มี MarketTrim ชื่อ/powertrain เดียวกันในรุ่นนี้แล้ว: ${duplicate.canonicalId} — แก้ตัวที่มีอยู่แทนการสร้างใหม่`);
  }

  const current = (existing?.payload || {}) as Record<string, unknown>;
  const currentTrimFields: Record<string, unknown> = {
    ...current, name: existing?.name, powertrain: existing?.powertrain,
  };

  // Three states per optional field: an explicit clear_<name> checkbox means
  // "unset it", a blank input means "untouched", a filled input means "set it".
  // A value identical to what is already stored is dropped so an unchanged
  // field never produces a command or a diff row.
  function isClearing(fieldName: string): boolean {
    return field(formData, `clear_${fieldName}`) === "on";
  }
  const trim: MarketTrimFields = { name, powertrain };
  function assignNumber(fieldName: keyof MarketTrimFields, label: string, integer: boolean) {
    const currentValue = current[fieldName as string] ?? null;
    if (isClearing(fieldName as string)) {
      if (currentValue !== null && currentValue !== undefined) (trim as any)[fieldName] = null;
      return;
    }
    const raw = field(formData, fieldName as string);
    if (!raw) return;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || (integer && !Number.isInteger(value))) {
      throw new Error(`${label} ต้องเป็นจำนวนบวกที่ถูกต้อง`);
    }
    if (value !== Number(currentValue)) (trim as any)[fieldName] = value;
  }
  function assignText(fieldName: keyof MarketTrimFields, emptyValue = "") {
    const currentValue = String(current[fieldName as string] ?? "");
    if (isClearing(fieldName as string)) {
      if (currentValue) (trim as any)[fieldName] = emptyValue;
      return;
    }
    const raw = field(formData, fieldName as string);
    if (!raw || raw === currentValue) return;
    (trim as any)[fieldName] = raw;
  }

  // Drivetrain is an enum defaulting to UNKNOWN, not a nullable field.
  assignText("drivetrain", "UNKNOWN");
  if (trim.drivetrain) trim.drivetrain = trim.drivetrain.toUpperCase();
  assignText("engine_code");
  assignNumber("engine_cc", "ความจุเครื่องยนต์", true);
  assignNumber("battery_kwh", "ความจุแบตเตอรี่", false);
  assignText("transmission");
  assignNumber("seats", "จำนวนที่นั่ง", true);
  assignNumber("length_mm", "ความยาว", true);
  assignNumber("width_mm", "ความกว้าง", true);
  assignNumber("height_mm", "ความสูง", true);
  assignNumber("wheelbase_mm", "ระยะฐานล้อ", true);
  assignText("tire_front");
  assignText("tire_rear");
  assignText("wheel_front");
  assignText("wheel_rear");
  assignText("notes");

  // Comparable-spec facts, read straight off the same form.
  const registry = loadSpecFieldRegistry(workspace.releaseYear);
  const currentSpecsByField: Record<string, { value_state: string; value: unknown }> = {};
  for (const fact of workspace.specFactsByTrim.get(existingTrimId || "") || []) {
    currentSpecsByField[fact.fieldKey] = {
      value_state: String((fact.payload as any)?.value_state || "UNKNOWN"),
      value: (fact.payload as any)?.value ?? null,
    };
  }
  const specEntries: TrimSpecEntry[] = [];
  if (existingTrimId) {
    for (const definition of registry) {
      if (!fieldAppliesToPowertrain(definition, powertrain)) continue;
      const notApplicable = field(formData, `spec_na__${definition.key}`) === "on";
      const raw = field(formData, `spec__${definition.key}`);
      const currentFact = currentSpecsByField[definition.key];
      const currentState = currentFact?.value_state || "UNKNOWN";

      let valueState: SpecFactValueState | null = null;
      let value: string | number | boolean | string[] | null = null;
      if (notApplicable) {
        if (currentState === "NOT_APPLICABLE") continue;
        valueState = "NOT_APPLICABLE";
      } else if (raw) {
        const parsed = parseSpecValue(definition, raw);
        if (currentState === "KNOWN" && JSON.stringify(currentFact?.value) === JSON.stringify(parsed)) continue;
        valueState = "KNOWN";
        value = parsed;
      }
      if (!valueState) continue;
      specEntries.push({
        fieldKey: definition.key,
        labelForDiff: `${definition.labelEn}${definition.canonicalUnit ? ` (${definition.canonicalUnit})` : ""}`,
        valueState, value, unit: definition.canonicalUnit,
      });
    }
  }

  const { remove, add } = readSourceRefEdits(formData);
  const existingRefs = (existing?.sourceRefs || {}) as Record<string, string[]>;
  const resolvedAdd = add.map((row) => {
    if (row.url) return row;
    const target = workspace.evidenceTargets.find((candidate) => candidate.id === row.kind);
    if (!target) throw new Error("registered OEM evidence target ที่เลือกไม่ตรงกับ canonical model นี้");
    return { kind: target.sourceId, url: target.url };
  });
  const sourceRefsTouched = remove.length > 0 || resolvedAdd.length > 0;
  const newSourceRefs = sourceRefsTouched ? applySourceRefEdits(existingRefs, { remove, add: resolvedAdd }) : undefined;

  const trimFieldsTouched = Object.keys(trim).some((key) => key !== "name" && key !== "powertrain");
  const identityChanged = !existing || existing.name !== name || existing.powertrain !== powertrain;
  if (existing && !trimFieldsTouched && !identityChanged && !sourceRefsTouched && !specEntries.length) {
    throw new Error("ไม่มีอะไรเปลี่ยน — แก้อย่างน้อย 1 ช่องก่อนกดบันทึก");
  }

  const reason = field(formData, "reason");
  const evidence = readEvidence(formData);
  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);

  const { payload } = buildTrimEditBatch({
    batchId: `admin-vehicle-trim-${submissionId}`,
    year: workspace.releaseYear,
    submittedAt,
    reason,
    evidence,
    canonicalModelId: modelId,
    brand: { id: workspace.brand.canonicalId, nameEn: workspace.brand.nameEn, nameTh: workspace.brand.nameTh || undefined },
    generationCode: workspace.generation.code,
    existingTrimId,
    trim,
    sourceRefs: newSourceRefs,
    specEntries,
  });

  const trimPatch = { ...(trim as unknown as Record<string, unknown>) };
  if (!identityChanged) { delete trimPatch.name; delete trimPatch.powertrain; }
  if (sourceRefsTouched) trimPatch.source_refs = newSourceRefs;
  const diff = diffTrimEdit({
    currentTrimFields: existing ? { ...currentTrimFields, source_refs: existingRefs } : {},
    trimPatch,
    trimLabels: TRIM_FIELD_LABELS,
    currentSpecsByField,
    specEntries,
  });

  const proposalId = await createProposal({
    kind: "TRIM", modelId, trimId: existingTrimId, actor: editor.name, pageReleaseId,
    batchPayload: payload, diff, reason: payload.reason, evidence,
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}/review/${encodeURIComponent(proposalId)}`);
}

export async function confirmEditProposal(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const proposalId = requiredField(formData, "proposal_id", "proposal");

  const proposal = await loadProposal(proposalId, editor.name);
  if (!proposal) {
    throw new Error("รายการนี้หมดอายุ ถูกบันทึกไปแล้ว หรือไม่ใช่ของคุณ — กรุณากลับไปแก้ไขใหม่อีกครั้ง");
  }
  const liveReleaseId = await liveModelReleaseId(proposal.modelId);
  if (!liveReleaseId) throw new Error("ไม่พบ canonical model นี้ใน active release แล้ว");
  assertNotStale(proposal.pageReleaseId, liveReleaseId);

  // enqueueCanonicalInputBatch is idempotent on (batch_key, payload hash), so a
  // retry after a transient failure below -- or a concurrent duplicate confirm
  // -- resolves to the same queued batch instead of a duplicate or a lost edit.
  await enqueueCanonicalInputBatch(proposal.batchPayload as Record<string, unknown>);
  // Consumption is bookkeeping after the durable write: a null result just
  // means a racing duplicate confirm already consumed it, not a failure.
  await consumeProposal(proposalId, editor.name);

  redirect(`/admin/vehicles/${encodeURIComponent(proposal.modelId)}?queued=1&kind=${encodeURIComponent(proposal.kind)}`);
}

/** Read-only helper for the review page: loads a PENDING_REVIEW proposal owned
 * by the current admin, or null (never distinguishing "not yours" from
 * "expired" from "never existed"). */
export async function loadOwnedProposal(proposalId: string) {
  const editor = await currentEditor();
  if (!editor) return null;
  return loadProposal(proposalId, editor.name);
}
