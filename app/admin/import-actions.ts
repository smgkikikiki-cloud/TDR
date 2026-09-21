"use server";

/**
 * Uploading a source file and getting it written.
 *
 * The owner drops a CSV or XLSX and sees upload -> processing -> completed.
 * Underneath, the file goes to storage and a worker is dispatched to run the
 * deterministic importer against it, because the importer writes canonical
 * files in the repository and cannot run in a request. None of that is the
 * owner's problem, so none of it is on the page.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { isAdmin, currentEditor } from "@/lib/admin-auth";
import { field } from "@/lib/admin-form";
import { adminDb } from "@/lib/supabase";
import { IMPORT_BUCKET, safeImportName } from "@/lib/import-runs";

const MAX_BYTES = 4 * 1024 * 1024;
// Sources with a parser of their own. Anything else has no import
// profile yet, and is refused here rather than routed to whichever
// parser is nearest.
const SOURCE_KINDS = new Set(["ECO", "DLT"]);

export async function uploadImportFileAction(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const file = formData.get("file");
  if (!(file instanceof File) || !file.size) throw new Error("เลือกไฟล์ก่อน");
  if (file.size > MAX_BYTES) throw new Error("ไฟล์ใหญ่เกิน 4 MB");
  const sourceKind = (field(formData, "source_kind") || "ECO").toUpperCase();
  if (!SOURCE_KINDS.has(sourceKind)) throw new Error("ชนิดแหล่งข้อมูลไม่รองรับ");

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const editor = await currentEditor();
  const storedAs = `${Date.now()}-${safeImportName(file.name)}`;

  const { error: uploadError } = await db.storage.from(IMPORT_BUCKET)
    .upload(storedAs, await file.arrayBuffer(),
      { contentType: file.type || "application/octet-stream", upsert: false });
  if (uploadError) throw uploadError;

  const { error } = await db.from("import_runs").insert({
    storage_path: storedAs,
    original_name: file.name,
    source_kind: sourceKind,
    status: "UPLOADED",
    actor: editor?.name || "tdr-admin",
  });
  if (error) throw error;

  await dispatchImportWorker();
  revalidatePath("/admin/import");
}

/** Start the run now rather than leaving it for the sweep. A failed
 *  dispatch only changes when the worker picks the file up. */
async function dispatchImportWorker() {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPOSITORY;
  if (!token || !repo) return;
  try {
    await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        accept: "application/vnd.github+json",
        "content-type": "application/json",
      },
      body: JSON.stringify({ event_type: "source-import" }),
    });
  } catch (error) {
    console.error("import dispatch failed; the sweep will pick it up", error);
  }
}
