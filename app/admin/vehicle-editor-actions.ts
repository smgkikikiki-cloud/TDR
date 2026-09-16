"use server";

/**
 * Server actions behind the Canonical Vehicle Editor (/admin/vehicles/[id]).
 *
 * Model/Generation and MarketTrim edits are one-shot:
 *   prepare*(formData) -> validate, load current canonical state, build the
 *                         canonical batch payload + diff, store it as a
 *                         PENDING_REVIEW proposal (lib/edit-session-store.ts),
 *                         redirect to /review/[proposalId] (opaque id only).
 *
 * Comparable-spec edits go through an explicit multi-field draft so a whole
 * vehicle's worth of specs can be reviewed and queued as ONE batch instead of
 * one round trip per field:
 *   addSpecDraftEntry     -> create-or-append one field into a DRAFT session
 *   removeSpecDraftEntry  -> drop one field back out of the draft
 *   prepareSpecDraftReview -> compile every entry into one batch + one diff,
 *                             promote DRAFT -> PENDING_REVIEW, redirect
 *
 * confirmEditProposal is the one path into the real queue for every kind: it
 * atomically consumes the proposal (so a duplicate confirm can never queue
 * twice), re-checks the release has not moved on since the page/draft was
 * opened (fail closed if it has), then hands the exact payload the admin
 * reviewed to enqueueCanonicalInputBatch. Nothing here ever touches
 * current_vehicle_*, canonical_*_projection or any release row directly --
 * those stay reachable only through the same
 * queue -> validate -> revision -> PR -> release path /admin/vehicle-input
 * already uses.
 */
import { redirect } from "next/navigation";
import { currentEditor, isAdmin, type AdminEditor } from "@/lib/admin-auth";
import { field, requiredField, isoDate, safeSubmissionId, submissionTimestamp, evidenceUrl } from "@/lib/admin-form";
import {
  buildModelGenerationBatch, buildMarketTrimBatch, buildSpecDraftBatch, diffSpecDraft,
  diffPatch, findDuplicateMarketTrim, isStaleRelease, applySourceRefEdits,
  type Evidence, type EvidenceKind, type MarketTrimFields, type SpecDraftEntry,
  type SpecFactValueState, type SpecFactVerification, type SourceRefEdit,
} from "@/lib/canonical-command-builder";
import { loadVehicleWorkspace, liveModelReleaseId } from "@/lib/canonical-editor";
import {
  createProposal, createDraft, loadDraft, upsertDraftEntry, removeDraftEntry, discardDraft,
  promoteDraftToProposal, loadProposal, consumeProposal,
} from "@/lib/edit-session-store";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { specFieldByKey, type SpecFieldDefinition } from "@/lib/spec-field-registry";
import { MARKET_TRIM_POWERTRAINS } from "@/lib/vehicle-taxonomy";

const EVIDENCE_KINDS = new Set<EvidenceKind>(["ADMIN", "OEM", "MEDIA"]);
const SOURCE_KIND_TOKEN = /^[a-z][a-z0-9_]{0,63}$/;

async function requireEditor(): Promise<AdminEditor> {
  const editor = await currentEditor();
  if (!editor) redirect("/admin/login");
  return editor;
}

function readEvidence(formData: FormData, opts: { requireRef: boolean }): Evidence {
  const sourceKind = requiredField(formData, "evidence_kind", "ชนิดหลักฐาน").toUpperCase() as EvidenceKind;
  if (!EVIDENCE_KINDS.has(sourceKind)) throw new Error("ชนิดหลักฐานไม่รองรับ");
  const sourceRefRaw = field(formData, "evidence_ref");
  if (opts.requireRef && !sourceRefRaw) throw new Error("ต้องใส่ evidence URL");
  const sourceRef = sourceRefRaw ? evidenceUrl(sourceRefRaw) : undefined;
  const reviewedAt = isoDate(requiredField(formData, "reviewed_at", "วันที่ตรวจ"), "วันที่ตรวจ", true)!;
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
      "Active canonical release เปลี่ยนไปตั้งแต่เปิดหน้านี้ — ข้อมูลอาจไม่ตรงกับของจริงแล้ว "
      + "กรุณา refresh หน้า vehicle editor แล้วแก้ไขใหม่ (ป้องกันการเขียนทับ revision ใหม่โดยไม่ตั้งใจ)",
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
  if (nameEn) modelPatch.name_en = nameEn;
  if (nameTh) modelPatch.name_th = nameTh;
  if (bodyType) modelPatch.body_type = bodyType;
  const generationPatch: Record<string, unknown> = {};
  if (segment) generationPatch.segment = segment;
  if (seats) {
    const seatsNumber = Number(seats);
    if (!Number.isInteger(seatsNumber) || seatsNumber <= 0) throw new Error("จำนวนที่นั่งต้องเป็นจำนวนเต็มบวก");
    generationPatch.seats = seatsNumber;
  }
  if (launched) generationPatch.launched = launched;
  if (ended) generationPatch.ended = ended;
  if (!Object.keys(modelPatch).length && !Object.keys(generationPatch).length) {
    throw new Error("เลือกอย่างน้อย 1 field ที่ต้องการแก้");
  }

  const reason = requiredField(formData, "reason", "เหตุผลการแก้");
  const evidence = readEvidence(formData, { requireRef: false });
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
    batchPayload: payload, diff, reason, evidence,
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
  for (let index = 1; index <= 3; index += 1) {
    const targetId = field(formData, `new_source_target_${index}`);
    const manualKind = field(formData, `new_source_kind_${index}`).toLowerCase();
    const manualRef = field(formData, `new_source_ref_${index}`);
    if (targetId) {
      add.push({ kind: targetId, url: "" }); // resolved by the caller, which knows modelId
    } else if (manualKind || manualRef) {
      if (!manualKind || !SOURCE_KIND_TOKEN.test(manualKind)) {
        throw new Error(`source kind แถวที่ ${index} ต้องเป็น a-z/0-9/_ (เช่น official_brandsite, ecosticker)`);
      }
      add.push({ kind: manualKind, url: evidenceUrl(manualRef || "") });
    }
  }
  return { remove, add };
}

export async function prepareMarketTrimEdit(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const modelId = requiredField(formData, "model_id", "canonical model");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  assertNotStale(pageReleaseId, workspace.releaseId);
  if (!workspace.generation) throw new Error("รุ่นนี้ไม่มี active generation ให้เพิ่ม MarketTrim");

  const existingTrimId = field(formData, "trim_id") || undefined;
  if (existingTrimId && !workspace.trims.some((row) => row.canonicalId === existingTrimId)) {
    throw new Error("MarketTrim นี้ไม่อยู่ใต้ canonical model ที่เลือก");
  }
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

  // Three states per optional field, never two: an explicit "clear_<name>"
  // checkbox means "unset this field" (numeric -> null, text -> the field's
  // canonical empty representation, drivetrain -> its UNKNOWN sentinel); a
  // blank input with no clear checkbox means "untouched, leave whatever the
  // canonical writer already has"; a filled input means "set this value".
  // Blank alone is never destructive -- only the explicit checkbox is.
  function isClearing(name: string): boolean {
    return field(formData, `clear_${name}`) === "on";
  }
  function numberField(name: string, label: string, integer: boolean): number | null | undefined {
    if (isClearing(name)) return null;
    const raw = field(formData, name);
    if (!raw) return undefined;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || (integer && !Number.isInteger(value))) {
      throw new Error(`${label} ต้องเป็นจำนวนบวกที่ถูกต้อง`);
    }
    return value;
  }
  /** Text fields default to `""` (their own canonical empty representation
   * per vehreg/entities.py's MarketTrim dataclass), so clearing sets that
   * same `""` rather than a separate null the writer would not recognize. */
  function textField(name: string): string | undefined {
    if (isClearing(name)) return "";
    const raw = field(formData, name);
    return raw || undefined;
  }

  const trim: MarketTrimFields = { name, powertrain };
  // Drivetrain is an enum defaulting to UNKNOWN, not a nullable field --
  // clearing it means resetting it to that sentinel, not null.
  const drivetrain = isClearing("drivetrain") ? "UNKNOWN" : field(formData, "drivetrain").toUpperCase();
  if (drivetrain) trim.drivetrain = drivetrain;
  const engineCode = textField("engine_code");
  if (engineCode !== undefined) trim.engine_code = engineCode;
  const engineCc = numberField("engine_cc", "ความจุเครื่องยนต์", true);
  if (engineCc !== undefined) trim.engine_cc = engineCc;
  const batteryKwh = numberField("battery_kwh", "ความจุแบตเตอรี่", false);
  if (batteryKwh !== undefined) trim.battery_kwh = batteryKwh;
  const transmission = textField("transmission");
  if (transmission !== undefined) trim.transmission = transmission;
  const seats = numberField("seats", "จำนวนที่นั่ง", true);
  if (seats !== undefined) trim.seats = seats;
  const lengthMm = numberField("length_mm", "ความยาว", true);
  if (lengthMm !== undefined) trim.length_mm = lengthMm;
  const widthMm = numberField("width_mm", "ความกว้าง", true);
  if (widthMm !== undefined) trim.width_mm = widthMm;
  const heightMm = numberField("height_mm", "ความสูง", true);
  if (heightMm !== undefined) trim.height_mm = heightMm;
  const wheelbaseMm = numberField("wheelbase_mm", "ระยะฐานล้อ", true);
  if (wheelbaseMm !== undefined) trim.wheelbase_mm = wheelbaseMm;
  const tireFront = textField("tire_front");
  if (tireFront !== undefined) trim.tire_front = tireFront;
  const tireRear = textField("tire_rear");
  if (tireRear !== undefined) trim.tire_rear = tireRear;
  const wheelFront = textField("wheel_front");
  if (wheelFront !== undefined) trim.wheel_front = wheelFront;
  const wheelRear = textField("wheel_rear");
  if (wheelRear !== undefined) trim.wheel_rear = wheelRear;
  const notes = textField("notes");
  if (notes !== undefined) trim.notes = notes;

  const reason = requiredField(formData, "reason", "เหตุผล/review note");
  // Manual MarketTrim identity always needs a traceable source -- the task's
  // own requirement that ECO snapshot review must not remain the only
  // structured way to create one, backed by real evidence, not just a note.
  const evidence = readEvidence(formData, { requireRef: true });
  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);

  const existing = existingTrimId ? workspace.trims.find((row) => row.canonicalId === existingTrimId) : undefined;
  const existingRefs = (existing?.sourceRefs || {}) as Record<string, string[]>;

  const { remove, add } = readSourceRefEdits(formData);
  const resolvedAdd = add.map((row) => {
    if (row.url) return row; // manual kind+url, already validated
    const target = workspace.evidenceTargets.find((candidate) => candidate.id === row.kind);
    if (!target) throw new Error("registered OEM evidence target ที่เลือกไม่ตรงกับ canonical model นี้");
    return { kind: target.sourceId, url: target.url };
  });
  const sourceRefsTouched = remove.length > 0 || resolvedAdd.length > 0;
  const newSourceRefs = sourceRefsTouched ? applySourceRefEdits(existingRefs, { remove, add: resolvedAdd }) : undefined;

  const { payload } = buildMarketTrimBatch({
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
  });

  const diff = diffPatch(
    existing ? { name: existing.name, powertrain: existing.powertrain, ...existing.payload } : {},
    trim as unknown as Record<string, unknown>,
    { name: "Name", powertrain: "Powertrain", drivetrain: "Drivetrain", engine_code: "Engine code", engine_cc: "Engine cc",
      battery_kwh: "Battery kWh", transmission: "Transmission", seats: "Seats", length_mm: "Length mm",
      width_mm: "Width mm", height_mm: "Height mm", wheelbase_mm: "Wheelbase mm", tire_front: "Tire front",
      tire_rear: "Tire rear", wheel_front: "Wheel front", wheel_rear: "Wheel rear", notes: "Notes" },
  );
  if (sourceRefsTouched) {
    diff.push(...diffPatch(
      { source_refs: existingRefs },
      { source_refs: newSourceRefs },
      { source_refs: "Source refs" },
    ));
  }

  const proposalId = await createProposal({
    kind: "MARKET_TRIM", modelId, trimId: existingTrimId, actor: editor.name, pageReleaseId,
    batchPayload: payload, diff, reason, evidence,
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}/review/${encodeURIComponent(proposalId)}`);
}

function parseSpecFieldValue(definition: SpecFieldDefinition, formData: FormData): {
  valueState: SpecFactValueState; value: string | number | boolean | string[] | null;
} {
  const valueState = requiredField(formData, "value_state", "value state").toUpperCase() as SpecFactValueState;
  if (!["KNOWN", "UNKNOWN", "NOT_AVAILABLE", "NOT_APPLICABLE"].includes(valueState)) {
    throw new Error("value state ไม่ถูกต้อง");
  }
  if (valueState !== "KNOWN") return { valueState, value: null };

  const raw = requiredField(formData, "value", `ค่าของ ${definition.labelEn}`);
  if (definition.valueType === "NUMBER") {
    const num = Number(raw);
    if (!Number.isFinite(num) || num < 0) throw new Error(`${definition.labelEn} ต้องเป็นตัวเลขที่ไม่ติดลบ`);
    return { valueState, value: num };
  }
  if (definition.valueType === "BOOLEAN") {
    if (raw !== "true" && raw !== "false") throw new Error(`${definition.labelEn} ต้องเป็น true/false`);
    return { valueState, value: raw === "true" };
  }
  if (definition.valueType === "SET") {
    const items = raw.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
    if (!items.length) throw new Error(`${definition.labelEn} ต้องมีอย่างน้อย 1 ค่า`);
    return { valueState, value: items };
  }
  return { valueState, value: raw };
}

/** Adds (or overwrites, if the same field was already staged) one field into
 * a multi-spec draft session, creating the session on first use. Every call
 * re-checks the release fingerprint against live state -- the whole point of
 * a multi-step draft is that it must not quietly drift onto stale data just
 * because it spans several requests. */
export async function addSpecDraftEntry(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const modelId = requiredField(formData, "model_id", "canonical model");
  const trimId = requiredField(formData, "trim_id", "MarketTrim");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  assertNotStale(pageReleaseId, workspace.releaseId);
  const trim = workspace.trims.find((row) => row.canonicalId === trimId);
  if (!trim || trim.modelId !== modelId) throw new Error("MarketTrim นี้ไม่อยู่ใต้ canonical model ที่เลือก");

  const fieldKey = requiredField(formData, "field_key", "spec field");
  const definition = specFieldByKey(workspace.releaseYear, fieldKey);
  if (!definition) throw new Error("ไม่พบ spec field นี้ใน canonical registry");
  const { valueState, value } = parseSpecFieldValue(definition, formData);

  const qualifiers: Record<string, string> = {};
  for (const qualifierKey of definition.comparisonQualifiers) {
    const raw = field(formData, `qualifier__${qualifierKey}`);
    if (raw) qualifiers[qualifierKey] = raw;
  }
  const observedAt = isoDate(field(formData, "observed_at"), "วันที่สังเกต");
  const verificationStatus = (field(formData, "verification_status") || "VERIFIED").toUpperCase() as SpecFactVerification;
  if (!["VERIFIED", "PROVISIONAL"].includes(verificationStatus)) throw new Error("verification status ไม่ถูกต้อง");
  // A KNOWN fact is a positive claim and needs a traceable source; disposing
  // a field as unknown/not-available/not-applicable still needs an evidence
  // *kind* + review date, but not necessarily a URL.
  const evidence = readEvidence(formData, { requireRef: valueState === "KNOWN" });

  const entry: SpecDraftEntry = {
    fieldKey, labelForDiff: `${definition.labelEn} (${definition.canonicalUnit || definition.valueType})`,
    valueState, value, unit: definition.canonicalUnit, qualifiers, observedAt, verificationStatus, evidence,
  };

  let draftId = field(formData, "draft_id");
  if (!draftId) {
    draftId = await createDraft({ modelId, trimId, actor: editor.name, pageReleaseId, defaultEvidence: evidence });
  }
  await upsertDraftEntry(draftId, editor.name, entry, evidence);
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}?draft=${encodeURIComponent(draftId)}#specs-${encodeURIComponent(trimId)}`);
}

export async function removeSpecDraftEntry(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const modelId = requiredField(formData, "model_id", "canonical model");
  const trimId = requiredField(formData, "trim_id", "MarketTrim");
  const draftId = requiredField(formData, "draft_id", "draft session");
  const fieldKey = requiredField(formData, "field_key", "spec field");
  await removeDraftEntry(draftId, editor.name, fieldKey);
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}?draft=${encodeURIComponent(draftId)}#specs-${encodeURIComponent(trimId)}`);
}

export async function discardSpecDraft(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const modelId = requiredField(formData, "model_id", "canonical model");
  const draftId = requiredField(formData, "draft_id", "draft session");
  await discardDraft(draftId, editor.name);
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}`);
}

/** Compiles every entry currently staged in a spec draft into ONE canonical
 * batch (one APPEND_SPEC command per changed field) and ONE combined diff,
 * then promotes the draft to a PENDING_REVIEW proposal. This is the only
 * place a multi-field spec edit becomes a canonical command -- fields the
 * admin never added to the draft never produce a command at all. */
export async function prepareSpecDraftReview(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const modelId = requiredField(formData, "model_id", "canonical model");
  const trimId = requiredField(formData, "trim_id", "MarketTrim");
  const draftId = requiredField(formData, "draft_id", "draft session");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  assertNotStale(pageReleaseId, workspace.releaseId);

  const draft = await loadDraft(draftId, editor.name);
  if (!draft) throw new Error("draft session หมดอายุหรือไม่พบ — กรุณาเริ่ม spec draft ใหม่");
  if (draft.modelId !== modelId || draft.trimId !== trimId) throw new Error("draft session ไม่ตรงกับรุ่น/MarketTrim ที่เลือก");
  if (!draft.draftEntries.length) throw new Error("ยังไม่มี field ใน draft นี้ — เพิ่มอย่างน้อย 1 field ก่อน review");

  const reason = requiredField(formData, "reason", "เหตุผลรวมของ spec draft นี้");
  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);
  const defaultEvidence = (draft.defaultEvidence || draft.draftEntries[draft.draftEntries.length - 1].evidence) as Evidence;
  if (!defaultEvidence) throw new Error("draft นี้ไม่มี evidence เริ่มต้น");

  const entries = draft.draftEntries as unknown as SpecDraftEntry[];
  const { payload } = buildSpecDraftBatch({
    batchId: `admin-vehicle-spec-draft-${submissionId}`,
    year: workspace.releaseYear,
    submittedAt,
    reason,
    evidence: defaultEvidence,
    trimId,
    entries,
  });

  const existingFacts = workspace.specFactsByTrim.get(trimId) || [];
  const currentByField: Record<string, { value_state: string; value: unknown }> = {};
  for (const fact of existingFacts) {
    currentByField[fact.fieldKey] = { value_state: String((fact.payload as any)?.value_state || "UNKNOWN"), value: (fact.payload as any)?.value ?? null };
  }
  const diff = diffSpecDraft(currentByField, entries);

  const proposalId = await promoteDraftToProposal(draftId, editor.name, {
    batchPayload: payload, diff, reason, evidence: defaultEvidence,
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}/review/${encodeURIComponent(proposalId)}`);
}

/**
 * Load -> re-check staleness -> enqueue -> consume, in that order, so a
 * transient failure can never permanently lose a reviewed edit.
 *
 * canonical_input_batches is already idempotent on (batch_key, payload
 * hash) -- see lib/canonical-input-queue.ts's enqueueCanonicalInputBatch,
 * which on a batch_key conflict compares the payload hash and returns a
 * no-op "duplicate" result instead of erroring when it matches. A proposal's
 * batch_id/payload never changes between attempts (it was fixed at prepare
 * time and stored as-is), so re-running enqueueCanonicalInputBatch against
 * the same still-PENDING_REVIEW proposal -- whether that is this request
 * retrying after the consume step below failed, or a genuinely concurrent
 * duplicate confirm of the same proposal -- always resolves to the SAME
 * queued batch, never a duplicate one.
 *
 * Consuming only after a successful enqueue means: if enqueue throws (a
 * transient DB error), the proposal stays PENDING_REVIEW and the admin's
 * retry (same proposal_id) starts this function over from a fresh load,
 * eventually enqueueing (idempotently) and then consuming. If consume
 * itself returns null -- most likely because a concurrent duplicate confirm
 * of this same proposal already consumed it -- that is not a failure worth
 * reporting: the edit is already safely queued either way, so this request
 * still redirects to success rather than surfacing an error for work that
 * in fact completed.
 */
export async function confirmEditProposal(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await requireEditor();
  const proposalId = requiredField(formData, "proposal_id", "proposal");

  const proposal = await loadProposal(proposalId, editor.name);
  if (!proposal) {
    throw new Error("proposal นี้หมดอายุ ถูกใช้ไปแล้ว หรือไม่ใช่ของคุณ — กรุณาทำรายการใหม่");
  }
  const liveReleaseId = await liveModelReleaseId(proposal.modelId);
  if (!liveReleaseId) throw new Error("ไม่พบ canonical model นี้ใน active release แล้ว");
  assertNotStale(proposal.pageReleaseId, liveReleaseId);

  await enqueueCanonicalInputBatch(proposal.batchPayload as Record<string, unknown>);
  await consumeProposal(proposalId, editor.name);

  redirect(`/admin/vehicles/${encodeURIComponent(proposal.modelId)}?queued=1&kind=${encodeURIComponent(proposal.kind)}`);
}

/** Read-only helper for the review page: loads a PENDING_REVIEW proposal
 * owned by the current admin, or null (never distinguishes "not yours" from
 * "expired" from "never existed" -- all three render the same generic
 * message). */
export async function loadOwnedProposal(proposalId: string) {
  const editor = await currentEditor();
  if (!editor) return null;
  return loadProposal(proposalId, editor.name);
}
