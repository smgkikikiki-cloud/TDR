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
 * Both build a canonical batch and write it: the editor owns this data, so
 * Save is the decision, not a request for one. The only thing standing
 * between the form and the write is integrity -- the release the page was
 * rendered from must still be the live one, so a save cannot silently
 * overwrite an edit that landed while the form sat open -- and
 * enqueueCanonicalInputBatch's (batch_key, payload-hash) idempotency, so a
 * retry after a transient failure resolves to the same batch instead of
 * losing the edit or writing it twice.
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
  buildModelGenerationBatch, buildTrimEditBatch,
  findDuplicateMarketTrim, isStaleRelease, applySourceRefEdits,
  type Evidence, type EvidenceKind,
  type SpecFactValueState, type TrimFieldSubmission, type SourceRefEdit,
} from "@/lib/canonical-command-builder";
import { loadVehicleWorkspace, liveModelReleaseId } from "@/lib/canonical-editor";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { trimEditorFields } from "@/lib/spec-field-registry";
import {
  fieldAppliesTo, validateFieldValue, validateTrimConsistency,
  valueInputName, naInputName, qualifierInputName, type TrimEditState,
} from "@/lib/trim-editor-fields";
import { MARKET_TRIM_POWERTRAINS } from "@/lib/vehicle-taxonomy";

const EVIDENCE_KINDS = new Set<EvidenceKind>(["ADMIN", "OEM", "MEDIA"]);
const SOURCE_KIND_TOKEN = /^[a-z][a-z0-9_]{0,63}$/;

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
  await enqueueCanonicalInputBatch(payload as Record<string, unknown>);
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}?saved=MODEL_GENERATION`);
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

/**
 * ONE trim, edited whole, in one pass.
 *
 * The form carries one box per concept -- Seats, Drivetrain, Battery capacity,
 * Range -- with no hint of which backend each lands in. This action reads the
 * same field catalog the page rendered (lib/trim-editor-fields.ts), validates
 * each value with the same function the page used, and hands the touched ones
 * to the builder, which fans each out to every backend representation its
 * entry declares. One form, one diff, one proposal, one batch.
 *
 * A brand-new trim carries its specs in that same save. The old flow -- create
 * the trim, come back, then add specs -- existed only because the builder could
 * not know the new trim's canonical_id; the spec commands now name the trim by
 * reference and the canonical writer resolves it with the one identity rule.
 */
export async function prepareTrimEdit(
  _previous: TrimEditState, formData: FormData,
): Promise<TrimEditState> {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const modelId = requiredField(formData, "model_id", "canonical model");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  if (!workspace.generation) throw new Error("รุ่นนี้ไม่มี active generation ให้เพิ่ม/แก้ MarketTrim");

  // A release activating under an open form is an ordinary race, not a bug:
  // the admin needs to see it on the page they are typing in.
  if (isStaleRelease(pageReleaseId, workspace.releaseId)) {
    return {
      fieldErrors: {},
      formError: "มี canonical release ใหม่ออกมาระหว่างที่เปิดหน้านี้ ข้อมูลบนหน้าจอจึงอาจไม่ตรงกับของจริงแล้ว "
        + "กรุณา refresh หน้านี้แล้วแก้ไขใหม่อีกครั้ง",
    };
  }

  const existingTrimId = field(formData, "trim_id") || undefined;
  const existing = existingTrimId
    ? workspace.trims.find((row) => row.canonicalId === existingTrimId) : undefined;
  if (existingTrimId && !existing) throw new Error("MarketTrim นี้ไม่อยู่ใต้ canonical model ที่เลือก");

  const fields = trimEditorFields(workspace.releaseYear)
    .filter((entry) => !entry.identityLocked || !existing);
  const fieldErrors: Record<string, string> = {};

  const name = field(formData, valueInputName("name")) || existing?.name || "";
  if (!name) fieldErrors.name = "ต้องระบุชื่อรุ่นย่อย";
  // Powertrain is part of the canonical_id, so an existing trim keeps its own.
  const powertrain = existing
    ? existing.powertrain
    : field(formData, valueInputName("powertrain")).toUpperCase();
  if (!powertrain) fieldErrors.powertrain = "ต้องเลือก powertrain";
  else if (!MARKET_TRIM_POWERTRAINS.includes(powertrain as any)) {
    fieldErrors.powertrain = "powertrain ไม่อยู่ใน canonical taxonomy";
  }

  const applicable = fields.filter((entry) => fieldAppliesTo(entry, powertrain));
  const current = existing?.editor.editableSpecs || {};

  const submissions: TrimFieldSubmission[] = [];
  const submittedValues: Record<string, string | number | boolean | null> = {};
  for (const entry of applicable) {
    const notApplicable = field(formData, naInputName(entry.key)) === "on";
    const raw = field(formData, valueInputName(entry.key));
    const before = current[entry.key] || { value: "", valueState: "UNKNOWN" as const, qualifiers: {} };

    let valueState: SpecFactValueState;
    let value: string | number | boolean | null = null;
    if (notApplicable) {
      valueState = "NOT_APPLICABLE";
    } else if (raw) {
      const parsed = validateFieldValue(entry, raw);
      if (!parsed.ok) { fieldErrors[entry.key] = parsed.message; continue; }
      valueState = "KNOWN";
      value = parsed.value;
      submittedValues[entry.key] = parsed.value;
    } else {
      // Blank is "untouched" while the field has never been set, and an
      // explicit clear once it has -- there is no third box to tick.
      if (before.valueState === "UNKNOWN") continue;
      valueState = "UNKNOWN";
    }

    const qualifiers: Record<string, string> = {};
    for (const qualifier of entry.qualifiers) {
      const chosen = field(formData, qualifierInputName(entry.key, qualifier.key));
      if (chosen) qualifiers[qualifier.key] = chosen;
    }

    const unchanged = before.valueState === valueState
      && String(before.value) === String(value ?? "")
      && JSON.stringify(before.qualifiers) === JSON.stringify(qualifiers);
    if (unchanged) continue;
    submissions.push({ key: entry.key, valueState, value, qualifiers });
  }

  for (const [key, message] of Object.entries(
    validateTrimConsistency(submittedValues, powertrain))) {
    fieldErrors[key] = message;
  }
  if (Object.keys(fieldErrors).length) return { formError: "", fieldErrors };

  const duplicate = findDuplicateMarketTrim(
    workspace.trims.map((row) => ({
      canonicalId: row.canonicalId, generationId: row.generationId,
      name: row.name, powertrain: row.powertrain,
    })),
    { generationId: workspace.generation.canonicalId, name, powertrain, excludeCanonicalId: existingTrimId },
  );
  if (duplicate) {
    return {
      formError: `มีรุ่นย่อยชื่อ/powertrain เดียวกันในรุ่นนี้แล้ว: ${duplicate.canonicalId} — แก้ตัวที่มีอยู่แทนการสร้างใหม่`,
      fieldErrors: {},
    };
  }

  const { remove, add } = readSourceRefEdits(formData);
  const existingRefs = existing?.editor.sourceRefs || {};
  const resolvedAdd: SourceRefEdit[] = [];
  for (const row of add) {
    if (row.url) { resolvedAdd.push(row); continue; }
    const target = workspace.evidenceTargets.find((candidate) => candidate.id === row.kind);
    if (!target) {
      return { formError: "แหล่งข้อมูล OEM ที่เลือกไม่ตรงกับรุ่นนี้", fieldErrors: {} };
    }
    resolvedAdd.push({ kind: target.sourceId, url: target.url });
  }
  const sourceRefsTouched = remove.length > 0 || resolvedAdd.length > 0;
  const newSourceRefs = sourceRefsTouched
    ? applySourceRefEdits(existingRefs, { remove, add: resolvedAdd }) : undefined;

  const identityChanged = !existing || existing.name !== name;
  if (existing && !submissions.length && !sourceRefsTouched && !identityChanged) {
    return { formError: "ไม่มีอะไรเปลี่ยน — แก้อย่างน้อย 1 ช่องก่อนกดบันทึก", fieldErrors: {} };
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
    brand: {
      id: workspace.brand.canonicalId, nameEn: workspace.brand.nameEn,
      nameTh: workspace.brand.nameTh || undefined,
    },
    generationCode: workspace.generation.code,
    generationId: workspace.generation.canonicalId,
    existingTrimId,
    identity: { name, powertrain },
    submissions,
    fields: applicable,
    sourceRefs: newSourceRefs,
  });

  await enqueueCanonicalInputBatch(payload as Record<string, unknown>);
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}?saved=TRIM`);
}
