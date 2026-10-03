"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import { field } from "@/lib/admin-form";
import { IMPORT_BUCKET, safeImportName } from "@/lib/import-runs";
import { adminDb } from "@/lib/supabase";

const MAX_BYTES = 4 * 1024 * 1024;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function parseModelIds(raw: string): string[] {
  const ids = [...new Set(raw.split(/[\s,]+/).map((value) => value.trim()).filter(Boolean))].sort();
  if (!ids.length) throw new Error("ใส่ model_id อย่างน้อย 1 รุ่น");
  if (ids.length > 100) throw new Error("สร้าง workbook ได้ครั้งละไม่เกิน 100 รุ่น");
  for (const id of ids) {
    if (!/^[a-z0-9][a-z0-9_.-]{1,119}$/i.test(id)) throw new Error(`model_id ไม่ถูกต้อง: ${id}`);
  }
  return ids;
}

async function dispatchWorker(eventType: string, clientPayload?: Record<string, unknown>) {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPOSITORY;
  if (!token || !repo) return false;
  try {
    const response = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        accept: "application/vnd.github+json",
        "content-type": "application/json",
      },
      body: JSON.stringify({ event_type: eventType, client_payload: clientPayload || {} }),
    });
    if (!response.ok) {
      console.error("retail lineup dispatch failed", eventType, response.status, await response.text());
      return false;
    }
    return true;
  } catch (error) {
    console.error("retail lineup dispatch failed", eventType, error);
    return false;
  }
}

export async function requestRetailLineupWorkbookAction(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await currentEditor();
  const modelIds = parseModelIds(field(formData, "model_ids"));
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");

  // The browser does not invent release/year metadata. It asks the current
  // serving projection which release these model ids belong to, then the
  // Python generator snapshots main using that exact release identity.
  const { data: models, error: modelError } = await db.from("current_vehicle_models")
    .select("canonical_id,release_id,status").in("canonical_id", modelIds).limit(200);
  if (modelError) throw modelError;
  const found = new Set((models || []).map((row: any) => String(row.canonical_id)));
  const missing = modelIds.filter((id) => !found.has(id));
  if (missing.length) throw new Error(`หา model_id ใน serving release ไม่เจอ: ${missing.join(", ")}`);
  const historical = (models || []).filter((row: any) => String(row.status || "").toUpperCase() === "HISTORICAL");
  if (historical.length) throw new Error(`Bootstrap V1 ไม่ reopen model ที่เป็น HISTORICAL: ${historical.map((row: any) => row.canonical_id).join(", ")}`);

  const releases = [...new Set((models || []).map((row: any) => String(row.release_id || "")).filter(Boolean))];
  if (releases.length !== 1) throw new Error("รุ่นที่เลือกไม่ได้อยู่ใน serving release เดียวกัน");
  const baseReleaseId = releases[0];
  const { data: release, error: releaseError } = await db.from("canonical_vehicle_releases")
    .select("release_id,as_of,payload").eq("release_id", baseReleaseId).maybeSingle();
  if (releaseError) throw releaseError;
  if (!release) throw new Error("หา serving release metadata ไม่เจอ");
  const payload = release.payload && typeof release.payload === "object" ? release.payload as any : {};
  const catalogYear = Number(payload.year || String(release.as_of || "").slice(0, 4));
  if (!Number.isInteger(catalogYear) || catalogYear < 2000 || catalogYear > 2100) {
    throw new Error("หา catalog year ของ serving release ไม่ได้");
  }

  const { error } = await db.from("retail_lineup_workbook_exports").insert({
    status: "QUEUED",
    actor: editor?.name || "tdr-admin",
    model_ids: modelIds,
    catalog_year: catalogYear,
    base_release_id: baseReleaseId,
  });
  if (error) throw error;

  // Dispatch is an accelerator; the workflow also has a periodic sweep, so a
  // transient GitHub failure never loses the durable request.
  await dispatchWorker("retail-lineup-workbook-export");
  revalidatePath("/admin/retail-lineup-bootstrap");
  redirect("/admin/retail-lineup-bootstrap?export=queued");
}

export async function downloadRetailLineupWorkbookAction(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const exportId = field(formData, "export_id");
  if (!UUID.test(exportId)) throw new Error("export id ไม่ถูกต้อง");
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: row, error } = await db.from("retail_lineup_workbook_exports")
    .select("status,storage_path").eq("id", exportId).maybeSingle();
  if (error) throw error;
  if (!row || row.status !== "READY" || !row.storage_path) throw new Error("workbook ยังไม่พร้อมดาวน์โหลด");
  const { data, error: signError } = await db.storage.from(IMPORT_BUCKET)
    .createSignedUrl(String(row.storage_path), 60);
  if (signError || !data?.signedUrl) throw signError || new Error("สร้างลิงก์ดาวน์โหลดไม่ได้");
  redirect(data.signedUrl);
}

export async function uploadRetailLineupWorkbookAction(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await currentEditor();
  const file = formData.get("file");
  if (!(file instanceof File) || !file.size) throw new Error("เลือก workbook ก่อน");
  if (file.size > MAX_BYTES) throw new Error("ไฟล์ใหญ่เกิน 4 MB");
  if (!file.name.toLowerCase().endsWith(".xlsx")) throw new Error("Retail Lineup Bootstrap รับเฉพาะ .xlsx");

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const storedAs = `retail-lineup-uploads/${Date.now()}-${safeImportName(file.name)}`;
  const { error: uploadError } = await db.storage.from(IMPORT_BUCKET)
    .upload(storedAs, await file.arrayBuffer(), {
      contentType: file.type || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      upsert: false,
    });
  if (uploadError) throw uploadError;

  // Chunk 7 owns the RETAIL_LINEUP_BOOTSTRAP source-kind migration/handler.
  // This UI deliberately queues the file through import_runs instead of ever
  // compiling or writing canonical state inside a Vercel request.
  const { error } = await db.from("import_runs").insert({
    storage_path: storedAs,
    original_name: file.name,
    source_kind: "RETAIL_LINEUP_BOOTSTRAP",
    status: "UPLOADED",
    actor: editor?.name || "tdr-admin",
  });
  if (error) throw error;

  await dispatchWorker("source-import");
  revalidatePath("/admin/retail-lineup-bootstrap");
  redirect("/admin/retail-lineup-bootstrap?upload=queued");
}

export async function applyRetailLineupPlanAction(_formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  // Vehicle DB v3 Phase 0 step 5: applying a plan wrote vehreg/data, pushed to
  // main and published a file-backed release -- the legacy Vehicle Master
  // write path, which is closed. Refuse before tdr_begin_retail_lineup_plan_apply
  // would move the plan to APPLYING with no worker left to finish it.
  throw new Error("Legacy Vehicle DB write path is closed (Phase 0 step 5): retail lineup plans can no longer be applied to the file-backed catalog.");
}
