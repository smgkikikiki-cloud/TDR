"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { isAdmin } from "@/lib/admin-auth";
import { field } from "@/lib/admin-form";
import {
  deleteResearchFile, renameResearchFile, signResearchFile, uploadResearchFile,
} from "@/lib/research-files";

const MAX_BYTES = 4 * 1024 * 1024;

async function guard() {
  if (!(await isAdmin())) redirect("/admin/login");
}

export async function uploadResearchFileAction(formData: FormData) {
  await guard();
  const file = formData.get("file");
  if (!(file instanceof File) || !file.size) throw new Error("เลือกไฟล์ก่อน");
  if (file.size > MAX_BYTES) throw new Error("ไฟล์ใหญ่เกิน 4 MB");
  await uploadResearchFile(file.name, await file.arrayBuffer(),
    file.type || "application/octet-stream");
  revalidatePath("/admin/research");
}

export async function renameResearchFileAction(formData: FormData) {
  await guard();
  const from = field(formData, "name");
  const to = field(formData, "new_name");
  if (!from || !to) throw new Error("ต้องมีทั้งชื่อเดิมและชื่อใหม่");
  if (from !== to) await renameResearchFile(from, to);
  revalidatePath("/admin/research");
}

export async function deleteResearchFileAction(formData: FormData) {
  await guard();
  const name = field(formData, "name");
  if (!name) throw new Error("ไม่พบไฟล์");
  await deleteResearchFile(name);
  revalidatePath("/admin/research");
}

/** Signed links expire, so one is minted per click rather than rendered
 *  into the page and left to go stale in somebody's open tab. */
export async function openResearchFileAction(formData: FormData) {
  await guard();
  const name = field(formData, "name");
  const url = name ? await signResearchFile(name) : null;
  if (!url) throw new Error("เปิดไฟล์นี้ไม่ได้");
  redirect(url);
}
