"use server";

import { redirect } from "next/navigation";
import { enqueueVehicleInput } from "@/app/admin/input-actions";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import {
  ECO_TRIM_SNAPSHOT_DATE,
  getEcoTrimCandidateGroup,
  getEcoTrimSnapshotHash,
} from "@/lib/eco-trim-snapshot";
import { adminDb } from "@/lib/supabase";

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function required(formData: FormData, name: string, label: string): string {
  const value = field(formData, name);
  if (!value) throw new Error(`กรุณาใส่ ${label}`);
  return value;
}

function normalizedName(value: unknown): string {
  return String(value || "").normalize("NFKC").toLocaleLowerCase("en-US").replace(/[^\p{L}\p{N}]+/gu, " ").trim().replace(/\s+/g, " ");
}

function ecoRefs(row: any): string[] {
  const refs = row?.source_refs?.ecosticker;
  return Array.isArray(refs) ? refs.map((value) => String(value || "").toLowerCase()).filter(Boolean) : [];
}

function mergedSourceRefs(existing: unknown, sourceIds: string[]): Record<string, unknown> {
  const refs = existing && typeof existing === "object" && !Array.isArray(existing)
    ? { ...(existing as Record<string, unknown>) }
    : {};
  const current = Array.isArray(refs.ecosticker)
    ? refs.ecosticker.map((value) => String(value || "").toLowerCase()).filter(Boolean)
    : [];
  refs.ecosticker = [...new Set([...current, ...sourceIds.map((value) => value.toLowerCase())])];
  return refs;
}

function validateSubmission(submissionId: string, submittedAt: string) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(submissionId)) throw new Error("submission_id ไม่ถูกต้อง");
  const stamp = new Date(submittedAt);
  if (Number.isNaN(stamp.getTime()) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(submittedAt)) {
    throw new Error("submission timestamp ต้องเป็น ISO-8601 พร้อม timezone");
  }
}

async function loadEcoWriteContext(groupKey: string) {
  const group = getEcoTrimCandidateGroup(groupKey);
  if (!group || group.snapshotDate !== ECO_TRIM_SNAPSHOT_DATE) throw new Error("ไม่พบ candidate นี้ใน immutable ECO snapshot");
  if (!group.modelId || !group.generationId || !group.powertrain || !group.sourceIds.length) {
    throw new Error("candidate ไม่มี model / generation / powertrain / source identity ครบ");
  }

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const [{ data: model, error: modelError }, { data: generation, error: generationError }, { data: trims, error: trimError }] = await Promise.all([
    db.from("current_vehicle_models")
      .select("canonical_id,release_id,brand_id,name_en,name_th")
      .eq("canonical_id", group.modelId).maybeSingle(),
    db.from("current_vehicle_generations")
      .select("canonical_id,model_id,code")
      .eq("canonical_id", group.generationId).maybeSingle(),
    db.from("current_market_trims")
      .select("canonical_id,model_id,generation_id,name,powertrain,source_refs")
      .eq("model_id", group.modelId).limit(500),
  ]);
  if (modelError) throw modelError;
  if (generationError) throw generationError;
  if (trimError) throw trimError;
  if (!model?.release_id || !model.brand_id) throw new Error("candidate model ไม่อยู่ใน active canonical release");
  if (!generation?.code || generation.model_id !== group.modelId || generation.canonical_id !== group.generationId) {
    throw new Error("candidate generation ไม่ตรง active canonical model");
  }

  const existingTrims = trims || [];
  const sourceSet = new Set(group.sourceIds.map((id) => id.toLowerCase()));
  const alreadyAttached = existingTrims.find((row: any) => ecoRefs(row).some((id) => sourceSet.has(id)));
  if (alreadyAttached) throw new Error(`ECO source ในกลุ่มนี้ถูก attach ไปแล้วที่ ${alreadyAttached.canonical_id}`);

  const [{ data: brand, error: brandError }, { data: release, error: releaseError }, editor] = await Promise.all([
    db.from("current_vehicle_brands")
      .select("canonical_id,name_en,name_th").eq("canonical_id", model.brand_id).maybeSingle(),
    db.from("canonical_vehicle_releases")
      .select("payload,as_of").eq("release_id", model.release_id).maybeSingle(),
    currentEditor(),
  ]);
  if (brandError) throw brandError;
  if (releaseError) throw releaseError;
  if (!brand?.canonical_id) throw new Error("หา canonical brand ของ candidate ไม่ได้");
  if (!editor?.name) throw new Error("HUMAN editor identity required");

  const releasePayload = release?.payload && typeof release.payload === "object" ? release.payload as Record<string, unknown> : {};
  const year = Number(releasePayload.year || String(release?.as_of || "").slice(0, 4));
  if (!Number.isInteger(year) || year < 2000 || year > 2100) throw new Error("หา catalog year ไม่ได้");
  return { group, model, generation, existingTrims, brand, year };
}

function canonicalBatch(args: {
  submissionId: string;
  submittedAt: string;
  reason: string;
  context: Awaited<ReturnType<typeof loadEcoWriteContext>>;
  trim: Record<string, unknown>;
}) {
  const { group, model, generation, brand, year } = args.context;
  const snapshotHash = getEcoTrimSnapshotHash();
  return {
    schema_version: 1,
    batch_id: `admin-eco-trim-${args.submissionId}`,
    year,
    submitted_at: args.submittedAt,
    source: {
      kind: "ECO",
      ref: `ecosticker:snapshot:${ECO_TRIM_SNAPSHOT_DATE}:sha256:${snapshotHash}`,
    },
    reason: `HUMAN-reviewed ECO MarketTrim: ${args.reason}`,
    commands: [{
      operation: "UPSERT_MODEL_BUNDLE",
      canonical_id: group.modelId,
      reason: `HUMAN-reviewed ECO MarketTrim: ${args.reason}`,
      payload: {
        brand: {
          id: brand.canonical_id,
          name_en: brand.name_en || brand.canonical_id,
          ...(brand.name_th ? { name_th: brand.name_th } : {}),
        },
        model: {
          id: group.modelId.split(".", 2)[1],
          name_en: model.name_en || model.name_th || group.modelId,
        },
        generation: { code: generation.code },
        variants: [],
        trims: [args.trim],
      },
    }],
  };
}

async function enqueueBatch(payload: unknown, submittedAt: string) {
  const advanced = new FormData();
  advanced.set("payload", JSON.stringify(payload));
  advanced.set("submitted_at", submittedAt);
  return enqueueVehicleInput(advanced);
}

export async function enqueueEcoMarketTrim(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const groupKey = required(formData, "group_key", "ECO candidate");
  // The field is intentionally blank in the UI. A human must type/confirm the
  // canonical name, but a correctly-written ECO label may legitimately equal it.
  const trimName = required(formData, "trim_name", "ชื่อ MarketTrim ที่ตรวจแล้ว");
  const reason = required(formData, "reason", "review note");
  const submissionId = required(formData, "submission_id", "submission id");
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  validateSubmission(submissionId, submittedAt);

  const context = await loadEcoWriteContext(groupKey);
  const duplicateIdentity = context.existingTrims.find((row: any) =>
    row.generation_id === context.group.generationId
    && String(row.powertrain || "").toUpperCase() === context.group.powertrain
    && normalizedName(row.name) === normalizedName(trimName));
  if (duplicateIdentity) {
    throw new Error(`มี MarketTrim ชื่อ/powertrain เดียวกันแล้ว: ${duplicateIdentity.canonical_id}; ใช้ Attach to existing trim แทน`);
  }

  return enqueueBatch(canonicalBatch({
    submissionId,
    submittedAt,
    reason,
    context,
    trim: {
      name: trimName,
      powertrain: context.group.powertrain,
      source_refs: { ecosticker: context.group.sourceIds },
    },
  }), submittedAt);
}

export async function enqueueEcoAttachExistingTrim(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const groupKey = required(formData, "group_key", "ECO candidate");
  const targetTrimId = required(formData, "target_trim_id", "MarketTrim ปลายทาง");
  const reason = required(formData, "reason", "review note");
  const submissionId = required(formData, "submission_id", "submission id");
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  validateSubmission(submissionId, submittedAt);

  const context = await loadEcoWriteContext(groupKey);
  const targetTrim = context.existingTrims.find((row: any) => String(row.canonical_id || "") === targetTrimId);
  if (!targetTrim) throw new Error("MarketTrim ปลายทางไม่อยู่ใต้ canonical model นี้");
  if (targetTrim.generation_id !== context.group.generationId) throw new Error("MarketTrim ปลายทางอยู่คนละ generation");
  if (String(targetTrim.powertrain || "").toUpperCase() !== context.group.powertrain) {
    throw new Error("MarketTrim ปลายทางมี powertrain ไม่ตรง ECO candidate");
  }
  if (!targetTrim.name) throw new Error("MarketTrim ปลายทางไม่มี canonical name");

  return enqueueBatch(canonicalBatch({
    submissionId,
    submittedAt,
    reason,
    context,
    trim: {
      canonical_id: targetTrim.canonical_id,
      name: targetTrim.name,
      powertrain: targetTrim.powertrain,
      source_refs: mergedSourceRefs(targetTrim.source_refs, context.group.sourceIds),
    },
  }), submittedAt);
}

export async function enqueueEcoReviewDisposition(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const groupKey = required(formData, "group_key", "ECO candidate");
  const action = required(formData, "disposition", "review disposition").toLowerCase();
  if (!new Set(["reject", "defer"]).has(action)) throw new Error("review disposition รองรับ reject/defer เท่านั้น");
  const reason = required(formData, "reason", "review note");
  const submissionId = required(formData, "submission_id", "submission id");
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  validateSubmission(submissionId, submittedAt);

  const context = await loadEcoWriteContext(groupKey);
  const snapshotHash = getEcoTrimSnapshotHash();
  // Reviewer/origin are deliberately absent. enqueueVehicleInput injects the
  // authenticated editor as command.actor; the worker derives reviewer from it.
  return enqueueBatch({
    schema_version: 1,
    batch_id: `admin-eco-review-${submissionId}`,
    year: context.year,
    submitted_at: submittedAt,
    source: {
      kind: "ECO",
      ref: `ecosticker:snapshot:${ECO_TRIM_SNAPSHOT_DATE}:sha256:${snapshotHash}`,
    },
    reason: `HUMAN ECO ${action}: ${reason}`,
    commands: [{
      operation: "UPSERT_ECO_REVIEW",
      payload: {
        snapshot_date: ECO_TRIM_SNAPSHOT_DATE,
        action,
        source_ids: context.group.sourceIds,
        notes: reason,
      },
    }],
  }, submittedAt);
}
