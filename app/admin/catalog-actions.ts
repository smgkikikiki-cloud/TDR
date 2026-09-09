"use server";

import { adminDb } from "@/lib/supabase";
import { isAdmin } from "@/lib/admin-auth";
import { redirect } from "next/navigation";

const val = (form: FormData, key: string) => {
  const value = form.get(key);
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

async function requireAdmin() {
  if (!(await isAdmin())) redirect("/admin/login");
}

/**
 * Vehicle identity, trims, prices and specifications are canonical files under
 * automotive/vehicle_master/. Keeping this export makes stale clients fail closed instead of
 * silently writing a second vehicle master into the editorial tables.
 */
export async function saveModelV12() {
  await requireAdmin();
  throw new Error("Vehicle facts are read-only here. Edit automotive/vehicle_master and publish one canonical release.");
}

/** TDR-owned editorial and presentation fields may still be edited here. */
export async function saveModelEditorial(formData: FormData) {
  await requireAdmin();
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase ใน .env.local");
  const id = val(formData, "id");
  if (!id) throw new Error("Missing editorial model id");
  const { error } = await db.from("models").update({
    image_url: val(formData, "image_url"),
    consumer_description: val(formData, "consumer_description"),
    market_position: val(formData, "market_position"),
    featured: formData.get("featured") === "on",
    notes: val(formData, "notes"),
  }).eq("id", id);
  if (error) throw error;
  redirect(`/admin/models/${id}/edit?saved=1`);
}
