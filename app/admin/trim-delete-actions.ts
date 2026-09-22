"use server";

import { redirect } from "next/navigation";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import { field, requiredField, safeSubmissionId, submissionTimestamp } from "@/lib/admin-form";
import { loadVehicleWorkspace } from "@/lib/canonical-editor";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { adminDb } from "@/lib/supabase";

/**
 * Permanently remove an erroneous MarketTrim from the canonical catalogue.
 *
 * This is intentionally fail-closed. A trim that already owns price history,
 * comparable-spec facts, or registration mappings is no longer a disposable
 * identity; deleting it would orphan facts that still name its canonical id.
 * Those cases must be cleaned/migrated explicitly before this action will
 * enqueue anything.
 */
export async function deleteCanonicalTrim(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await currentEditor();
  if (!editor) redirect("/admin/login");

  const modelId = requiredField(formData, "model_id", "canonical model");
  const trimId = requiredField(formData, "trim_id", "MarketTrim");
  const pageReleaseId = requiredField(formData, "page_release_id", "release fingerprint");
  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);

  const workspace = await loadVehicleWorkspace(modelId);
  if (!workspace) throw new Error("ไม่พบ canonical model นี้ใน active release");
  if (workspace.releaseId !== pageReleaseId) {
    throw new Error(
      "มี canonical release ใหม่ออกมาระหว่างที่เปิดหน้านี้ กรุณารีเฟรชก่อนลบรุ่นย่อย เพื่อไม่ให้ลบจากข้อมูลเก่า",
    );
  }
  if (!workspace.generation) throw new Error("รุ่นนี้ไม่มี active generation");

  const trim = workspace.trims.find((row) => row.canonicalId === trimId);
  if (!trim) throw new Error("MarketTrim นี้ไม่อยู่ใต้ canonical model ที่เลือก");

  const specCount = (workspace.specFactsByTrim.get(trimId) || []).length;
  if (specCount > 0) {
    throw new Error(`ลบ ${trim.name} ไม่ได้: มี comparable-spec facts ${specCount} รายการผูกกับ trim นี้อยู่`);
  }
  if (trim.prices.length > 0 || trim.campaign) {
    throw new Error(`ลบ ${trim.name} ไม่ได้: มีประวัติราคา/แคมเปญผูกกับ trim นี้อยู่`);
  }

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const [registrationRows, aliasRows] = await Promise.all([
    db.from("registrations").select("id").eq("canonical_trim_id", trimId).limit(1),
    db.from("registration_model_aliases").select("id").eq("canonical_trim_id", trimId).limit(1),
  ]);
  if (registrationRows.error) throw registrationRows.error;
  if (aliasRows.error) throw aliasRows.error;
  if ((registrationRows.data || []).length || (aliasRows.data || []).length) {
    throw new Error(`ลบ ${trim.name} ไม่ได้: มีข้อมูลจดทะเบียนหรือ alias ผูกกับ trim นี้อยู่`);
  }

  const payload = {
    schema_version: 1 as const,
    batch_id: `admin-delete-trim-${submissionId}`,
    year: workspace.releaseYear,
    submitted_at: submittedAt,
    source: { kind: "ADMIN" },
    reason: `Delete erroneous MarketTrim ${trimId}`,
    commands: [{
      operation: "UPSERT_MODEL_BUNDLE",
      canonical_id: modelId,
      payload: {
        brand: {
          id: workspace.brand.canonicalId,
          name_en: workspace.brand.nameEn,
          ...(workspace.brand.nameTh ? { name_th: workspace.brand.nameTh } : {}),
        },
        model: {},
        generation: { code: workspace.generation.code },
        variants: [],
        trims: [],
        delete_trim: { canonical_id: trimId },
      },
    }],
  };

  await enqueueCanonicalInputBatch(payload as unknown as Record<string, unknown>);
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}?saved=TRIM`);
}
