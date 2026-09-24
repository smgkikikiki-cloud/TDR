"use server";

import { createHash } from "node:crypto";
import { redirect } from "next/navigation";
import { isAdmin } from "@/lib/admin-auth";
import { adminDb } from "@/lib/supabase";

const BUCKET = "vehicle-media";
const MIME: Record<string, string> = {
  "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/avif": "avif",
};

async function context(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const modelId = String(formData.get("model_id") || "");
  const db = adminDb();
  if (!db || !modelId) throw new Error("Missing model or database");
  const { data: model, error } = await db.from("current_vehicle_models")
    .select("canonical_id,release_id").eq("canonical_id", modelId).maybeSingle();
  if (error || !model) throw new Error("Model is not in the active canonical release");
  if (model.release_id !== formData.get("page_release_id")) {
    throw new Error("Canonical release changed; reload the editor before changing its image");
  }
  return { db, modelId };
}

async function bindModel(db: NonNullable<ReturnType<typeof adminDb>>, modelId: string) {
  const { error } = await db.from("vehicle_media_bindings").upsert({
    entity_id: modelId, entity_type: "model", visual_key: modelId,
    inherited_from: null, updated_at: new Date().toISOString(),
  }, { onConflict: "entity_id" });
  if (error) throw error;
}

export async function saveModelHeadImage(formData: FormData) {
  const { db, modelId } = await context(formData);
  const file = formData.get("image");
  const sourceUrl = String(formData.get("source_url") || "").trim();
  if (!(file instanceof File) || !file.size || file.size > 20 * 1024 * 1024 || !MIME[file.type]) {
    throw new Error("Upload one JPEG, PNG, WebP or AVIF under 20 MB");
  }
  const url = new URL(sourceUrl);
  if (!["https:", "http:"].includes(url.protocol)) throw new Error("Source URL must be HTTP(S)");
  const bytes = Buffer.from(await file.arrayBuffer());
  const sha = createHash("sha256").update(bytes).digest("hex");
  const path = `model-head/${modelId}/${sha}.${MIME[file.type]}`;
  const { error: uploadError } = await db.storage.from(BUCKET).upload(path, bytes, {
    contentType: file.type, cacheControl: "31536000", upsert: true,
  });
  if (uploadError) throw uploadError;
  const publicUrl = db.storage.from(BUCKET).getPublicUrl(path).data.publicUrl;
  const { error } = await db.from("vehicle_media_assets").upsert({
    vehicle_id: modelId, visual_key: modelId,
    source_url: sourceUrl, source_type: "manual", source_domain: url.hostname,
    image_url_original: sourceUrl, storage_bucket: BUCKET, storage_path: path,
    public_url: publicUrl, image_type: "hero", market: "TH",
    confidence: 100, sha256: sha, status: "approved",
    updated_at: new Date().toISOString(),
  }, { onConflict: "visual_key,image_type,sha256" });
  if (error) throw error;
  await bindModel(db, modelId);
  // Do not remove the previous binary here: content-addressed objects may be
  // referenced elsewhere. The media orphan-pruner handles unreferenced files.
  const { error: pruneError } = await db.from("vehicle_media_assets")
    .delete().eq("visual_key", modelId).eq("image_type", "hero").neq("sha256", sha);
  if (pruneError) throw pruneError;
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}?saved=IMAGE`);
}

export async function removeModelHeadImage(formData: FormData) {
  const { db, modelId } = await context(formData);
  // Persist the empty binding so old generation images cannot reappear.
  await bindModel(db, modelId);
  const { error } = await db.from("vehicle_media_assets")
    .delete().eq("visual_key", modelId).eq("image_type", "hero");
  if (error) throw error;
  redirect(`/admin/vehicles/${encodeURIComponent(modelId)}?saved=IMAGE_REMOVED`);
}
