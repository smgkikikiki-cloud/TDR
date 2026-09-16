"use server";

/**
 * Server actions behind the Canonical Vehicle Editor (/admin/vehicles/[id]).
 *
 * Every mutation here follows the same two-step shape:
 *   prepare*(formData)  -> validate, load current canonical state, build the
 *                          canonical batch payload + diff, sign it into a
 *                          short-lived token, redirect to the review page.
 *   confirmEditProposal -> re-verify the token, re-check the release has not
 *                          moved on (fail closed if it has), then hand the
 *                          exact payload the admin reviewed to
 *                          enqueueCanonicalInputBatch. Nothing here ever
 *                          touches current_vehicle_*, canonical_*_projection
 *                          or any release row directly -- those stay
 *                          reachable only through the same
 *                          queue -> validate -> revision -> PR -> release
 *                          path /admin/vehicle-input already uses.
 */
import { redirect } from "next/navigation";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import { field, requiredField, isoDate, safeSubmissionId, submissionTimestamp, evidenceUrl } from "@/lib/admin-form";
import {
  buildModelGenerationBatch, buildMarketTrimBatch, buildSpecFactBatch,
  diffPatch, findDuplicateMarketTrim, isStaleRelease,
  type Evidence, type EvidenceKind, type MarketTrimFields,
  type SpecFactValueState, type SpecFactVerification,
} from "@/lib/canonical-command-builder";
import { loadVehicleWorkspace, liveModelReleaseId } from "@/lib/canonical-editor";
import { signEditProposal, verifyEditProposal } from "@/lib/edit-proposal-token";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { specFieldByKey } from "@/lib/spec-field-registry";
import { MARKET_TRIM_POWERTRAINS } from "@/lib/vehicle-taxonomy";

const EVIDENCE_KINDS = new Set<EvidenceKind>(["ADMIN", "OEM", "MEDIA"]);

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

  const editor = await currentEditor();
  const token = signEditProposal({
    kind: "MODEL_GENERATION", modelId, pageReleaseId, batchPayload: payload, diff, reason, evidence,
    actor: editor?.name || "tdr-admin",
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}/review?token=${encodeURIComponent(token)}`);
}

export async function prepareMarketTrimEdit(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
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

  function numberField(name: string, label: string, integer: boolean): number | undefined {
    const raw = field(formData, name);
    if (!raw) return undefined;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || (integer && !Number.isInteger(value))) {
      throw new Error(`${label} ต้องเป็นจำนวนบวกที่ถูกต้อง`);
    }
    return value;
  }

  const trim: MarketTrimFields = { name, powertrain };
  const drivetrain = field(formData, "drivetrain").toUpperCase();
  if (drivetrain) trim.drivetrain = drivetrain;
  const engineCode = field(formData, "engine_code");
  if (engineCode) trim.engine_code = engineCode;
  const engineCc = numberField("engine_cc", "ความจุเครื่องยนต์", true);
  if (engineCc !== undefined) trim.engine_cc = engineCc;
  const batteryKwh = numberField("battery_kwh", "ความจุแบตเตอรี่", false);
  if (batteryKwh !== undefined) trim.battery_kwh = batteryKwh;
  const transmission = field(formData, "transmission");
  if (transmission) trim.transmission = transmission;
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
  const tireFront = field(formData, "tire_front");
  if (tireFront) trim.tire_front = tireFront;
  const tireRear = field(formData, "tire_rear");
  if (tireRear) trim.tire_rear = tireRear;
  const wheelFront = field(formData, "wheel_front");
  if (wheelFront) trim.wheel_front = wheelFront;
  const wheelRear = field(formData, "wheel_rear");
  if (wheelRear) trim.wheel_rear = wheelRear;
  const notes = field(formData, "notes");
  if (notes) trim.notes = notes;

  const reason = requiredField(formData, "reason", "เหตุผล/review note");
  // Manual MarketTrim identity always needs a traceable source -- the task's
  // own requirement that ECO snapshot review must not remain the only
  // structured way to create one, backed by real evidence, not just a note.
  const evidence = readEvidence(formData, { requireRef: true });
  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);

  const existing = existingTrimId ? workspace.trims.find((row) => row.canonicalId === existingTrimId) : undefined;
  const existingRefs = (existing?.sourceRefs || {}) as Record<string, string[]>;
  const evidenceKey = evidence.sourceKind.toLowerCase();
  const mergedSourceRefs = evidence.sourceRef ? {
    ...existingRefs,
    [evidenceKey]: [...new Set([...(existingRefs[evidenceKey] || []), evidence.sourceRef])],
  } : (Object.keys(existingRefs).length ? existingRefs : undefined);

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
    sourceRefs: mergedSourceRefs,
  });

  const diff = diffPatch(
    existing ? { name: existing.name, powertrain: existing.powertrain, ...existing.payload } : {},
    trim as unknown as Record<string, unknown>,
    { name: "Name", powertrain: "Powertrain", drivetrain: "Drivetrain", engine_code: "Engine code", engine_cc: "Engine cc",
      battery_kwh: "Battery kWh", transmission: "Transmission", seats: "Seats", length_mm: "Length mm",
      width_mm: "Width mm", height_mm: "Height mm", wheelbase_mm: "Wheelbase mm", tire_front: "Tire front",
      tire_rear: "Tire rear", wheel_front: "Wheel front", wheel_rear: "Wheel rear", notes: "Notes" },
  );

  const editor = await currentEditor();
  const token = signEditProposal({
    kind: "MARKET_TRIM", modelId, pageReleaseId, batchPayload: payload, diff, reason, evidence,
    actor: editor?.name || "tdr-admin",
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}/review?token=${encodeURIComponent(token)}`);
}

export async function prepareSpecFactEdit(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const modelId = requiredField(formData, "model_id", "canonical model");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const workspace = await loadWorkspaceOrThrow(modelId);
  assertNotStale(pageReleaseId, workspace.releaseId);

  const trimId = requiredField(formData, "trim_id", "MarketTrim");
  const trim = workspace.trims.find((row) => row.canonicalId === trimId);
  if (!trim || trim.modelId !== modelId) throw new Error("MarketTrim นี้ไม่อยู่ใต้ canonical model ที่เลือก");

  const fieldKey = requiredField(formData, "field_key", "spec field");
  const definition = specFieldByKey(workspace.releaseYear, fieldKey);
  if (!definition) throw new Error("ไม่พบ spec field นี้ใน canonical registry");

  const valueState = requiredField(formData, "value_state", "value state").toUpperCase() as SpecFactValueState;
  if (!["KNOWN", "UNKNOWN", "NOT_AVAILABLE", "NOT_APPLICABLE"].includes(valueState)) {
    throw new Error("value state ไม่ถูกต้อง");
  }

  let value: string | number | boolean | string[] | null = null;
  if (valueState === "KNOWN") {
    const raw = requiredField(formData, "value", `ค่าของ ${definition.labelEn}`);
    if (definition.valueType === "NUMBER") {
      const num = Number(raw);
      if (!Number.isFinite(num) || num < 0) throw new Error(`${definition.labelEn} ต้องเป็นตัวเลขที่ไม่ติดลบ`);
      value = num;
    } else if (definition.valueType === "BOOLEAN") {
      if (raw !== "true" && raw !== "false") throw new Error(`${definition.labelEn} ต้องเป็น true/false`);
      value = raw === "true";
    } else if (definition.valueType === "SET") {
      const items = raw.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
      if (!items.length) throw new Error(`${definition.labelEn} ต้องมีอย่างน้อย 1 ค่า`);
      value = items;
    } else {
      value = raw;
    }
  }

  const qualifiers: Record<string, string> = {};
  for (const qualifierKey of definition.comparisonQualifiers) {
    const raw = field(formData, `qualifier__${qualifierKey}`);
    if (raw) qualifiers[qualifierKey] = raw;
  }

  const observedAt = isoDate(field(formData, "observed_at"), "วันที่สังเกต");
  const verificationStatus = (field(formData, "verification_status") || "VERIFIED").toUpperCase() as SpecFactVerification;
  if (!["VERIFIED", "PROVISIONAL"].includes(verificationStatus)) throw new Error("verification status ไม่ถูกต้อง");

  const reason = requiredField(formData, "reason", "เหตุผล/review note");
  // A KNOWN fact is a positive claim about the car and needs a traceable
  // source; disposing a field as unknown/not-available/not-applicable still
  // needs a reason but not necessarily a URL.
  const evidence = readEvidence(formData, { requireRef: valueState === "KNOWN" });
  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);

  const { payload } = buildSpecFactBatch({
    batchId: `admin-vehicle-spec-${submissionId}`,
    year: workspace.releaseYear,
    submittedAt,
    reason,
    evidence,
    trimId,
    fieldKey,
    valueState,
    value,
    unit: definition.canonicalUnit,
    qualifiers,
    observedAt,
    verificationStatus,
  });

  const existingFact = (workspace.specFactsByTrim.get(trimId) || []).find((row) => row.fieldKey === fieldKey);
  const diff = diffPatch(
    { value_state: existingFact?.payload?.value_state ?? "UNKNOWN", value: existingFact?.payload?.value ?? null },
    { value_state: valueState, value },
    { value_state: "Value state", value: `${definition.labelEn} (${definition.canonicalUnit || definition.valueType})` },
  );

  const editor = await currentEditor();
  const token = signEditProposal({
    kind: "SPEC_FACT", modelId, pageReleaseId, batchPayload: payload, diff, reason, evidence,
    actor: editor?.name || "tdr-admin",
  });
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}/review?token=${encodeURIComponent(token)}`);
}

export async function confirmEditProposal(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const token = requiredField(formData, "token", "review token");
  const proposal = verifyEditProposal(token);
  if (!proposal) {
    throw new Error("review session หมดอายุหรือไม่ถูกต้อง — กรุณากลับไปแก้ไขและ preview ใหม่");
  }
  const liveReleaseId = await liveModelReleaseId(proposal.modelId);
  if (!liveReleaseId) throw new Error("ไม่พบ canonical model นี้ใน active release แล้ว");
  assertNotStale(proposal.pageReleaseId, liveReleaseId);

  await enqueueCanonicalInputBatch(proposal.batchPayload);
  redirect(`/admin/vehicles/${encodeURIComponent(proposal.modelId)}?queued=1&kind=${encodeURIComponent(proposal.kind)}`);
}
