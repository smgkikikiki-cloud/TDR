"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { isAdmin } from "@/lib/admin-auth";
import { adminDb } from "@/lib/supabase";
import { parseUpcomingCarForm, parseUpcomingUpdate } from "@/lib/upcoming-cars-form";

async function dbForAdmin() {
  if (!(await isAdmin())) redirect("/admin/login");
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase");
  return db;
}

function vehicleId(form: FormData): string {
  const id = form.get("vehicle_id");
  if (typeof id !== "string" || !/^UP-\d{4,}$/.test(id)) throw new Error("Upcoming Cars ID ไม่ถูกต้อง");
  return id;
}

export async function createUpcomingCar(form: FormData) {
  const db = await dbForAdmin();
  const payload = parseUpcomingCarForm(form);
  const { data, error } = await db.from("upcoming_cars").insert(payload)
    .select("vehicle_id").single();
  if (error) throw error;
  revalidatePath("/admin/upcoming");
  redirect(`/admin/upcoming/${data.vehicle_id}`);
}

export async function updateUpcomingCar(form: FormData) {
  const db = await dbForAdmin();
  const id = vehicleId(form);
  const payload = parseUpcomingCarForm(form);
  const { data, error } = await db.from("upcoming_cars").update(payload)
    .eq("vehicle_id", id).select("vehicle_id").single();
  if (error) throw error;
  revalidatePath("/admin/upcoming");
  revalidatePath(`/admin/upcoming/${id}`);
  redirect(`/admin/upcoming/${data.vehicle_id}?saved=1`);
}

export async function deleteUpcomingCar(form: FormData) {
  const db = await dbForAdmin();
  const id = vehicleId(form);
  const { error } = await db.from("upcoming_cars").delete().eq("vehicle_id", id);
  if (error) throw error;
  revalidatePath("/admin/upcoming");
  redirect("/admin/upcoming?deleted=1");
}

export async function addUpcomingCarUpdate(form: FormData) {
  const db = await dbForAdmin();
  const id = vehicleId(form);
  const payload = parseUpcomingUpdate(form);
  const { data: car, error: lookupError } = await db.from("upcoming_cars")
    .select("id").eq("vehicle_id", id).single();
  if (lookupError) throw lookupError;
  const { error } = await db.from("upcoming_car_updates")
    .insert({ upcoming_car_id: car.id, ...payload });
  if (error) throw error;
  revalidatePath(`/admin/upcoming/${id}`);
  redirect(`/admin/upcoming/${id}?updated=1`);
}
