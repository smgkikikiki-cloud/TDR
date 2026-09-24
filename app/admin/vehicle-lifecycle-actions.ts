"use server";

import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { isAdmin } from "@/lib/admin-auth";
import { loadVehicleWorkspace } from "@/lib/canonical-editor";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function required(formData: FormData, name: string): string {
  const value = field(formData, name);
  if (!value) throw new Error(`missing ${name}`);
  return value;
}

/**
 * Owner-facing lifecycle switch for the normal Vehicle Editor.
 *
 * Policy is CURRENT by default; this action only records the exceptions the
 * owner actually decides: archive a model, or reopen it.  No evidence URL is
 * required because the owner clicking the control is the decision and the
 * canonical revision log is the audit trail.
 */
export async function setModelRetailState(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");

  const modelId = required(formData, "model_id");
  const pageReleaseId = required(formData, "page_release_id");
  const requested = required(formData, "retail_status").toUpperCase();
  if (requested !== "CURRENT" && requested !== "HISTORICAL") {
    throw new Error("retail_status must be CURRENT or HISTORICAL");
  }

  const workspace = await loadVehicleWorkspace(modelId);
  if (!workspace) throw new Error("ไม่พบ canonical model นี้ใน active release");
  if (workspace.releaseId !== pageReleaseId) {
    throw new Error("มี canonical release ใหม่แล้ว กรุณา refresh หน้านี้ก่อนเปลี่ยนสถานะรถ");
  }
  if (!workspace.generation) throw new Error("รุ่นนี้ไม่มี generation สำหรับ canonical write");

  const submittedAt = new Date().toISOString();
  const today = submittedAt.slice(0, 10);
  const batchId = `admin-vehicle-lifecycle-${randomUUID()}`;

  const command = requested === "HISTORICAL"
    ? {
        operation: "WITHDRAW_MODEL",
        canonical_id: modelId,
        payload: {},
      }
    : {
        operation: "UPSERT_MODEL_BUNDLE",
        canonical_id: modelId,
        payload: {
          brand: {
            id: workspace.brand.canonicalId,
            name_en: workspace.brand.nameEn,
            ...(workspace.brand.nameTh ? { name_th: workspace.brand.nameTh } : {}),
          },
          model: {
            retail_status: "CURRENT",
            retail_source: "manual-admin",
            retail_checked_at: today,
          },
          generation: {
            code: workspace.generation.code,
            ...(workspace.generation.segment ? { segment: workspace.generation.segment } : {}),
          },
        },
      };

  await enqueueCanonicalInputBatch({
    schema_version: 1,
    batch_id: batchId,
    year: workspace.releaseYear,
    submitted_at: submittedAt,
    source: { kind: "ADMIN" },
    reason: requested === "HISTORICAL"
      ? "Owner archived model from Canonical Vehicle Editor"
      : "Owner reopened model from Canonical Vehicle Editor",
    commands: [command],
  });

  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}?saved=LIFECYCLE`);
}
