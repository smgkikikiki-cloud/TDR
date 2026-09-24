/** Explicit apply for a reviewed one-time Model head manifest; dry-run by default. */
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { resolve, extname } from "node:path";
import { createClient } from "@supabase/supabase-js";

type Row = {
  model_id: string; generation_id: string; status: string;
  selected_image: string | null; source_url: string | null;
  source_domain: string | null; source_type?: string;
  sha256: string | null; storage_path: string | null;
  confidence?: number; width?: number | null; height?: number | null;
};
const args = process.argv.slice(2);
function arg(name: string, fallback: string) {
  const at = args.indexOf(`--${name}`);
  return at < 0 ? fallback : args[at + 1];
}
const applying = args.includes("--apply");
const replaceManual = args.includes("--replace-manual");
const manifest = resolve(arg("manifest", "automotive/vehicle_master/integration_data/model_head_manifest.jsonl"));
const cache = resolve(arg("cache", "automotive/vehicle_master/data/media/cache"));
const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!url || !key) throw new Error("Supabase server credentials required");
const db = createClient(url, key, { auth: { persistSession: false } });
const rows = readFileSync(manifest, "utf8").split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line) as Row);
const ready = rows.filter(row => row.status === "READY");
const ids = ready.map(row => row.model_id);
if (new Set(ids).size !== ids.length) throw new Error("duplicate Model in manifest");
const active = new Map<string, string>();
for (let i = 0; i < ids.length; i += 75) {
  const { data, error } = await db.from("current_vehicle_models")
    .select("canonical_id,generation_id").in("canonical_id", ids.slice(i, i + 75));
  if (error) throw error;
  for (const item of data || []) active.set(item.canonical_id, item.generation_id);
}
const missing = ready.filter(row => active.get(row.model_id) !== row.generation_id);
if (missing.length) throw new Error("Manifest has stale Model/Generation IDs: " + missing.map(r => r.model_id).join(", "));
let applied = 0, skipped = 0;
for (const row of ready) {
  if (!row.storage_path || !row.sha256 || !row.selected_image || !row.source_url) {
    throw new Error(`${row.model_id}: incomplete READY entry`);
  }
  if (!/^model-head\/[a-z0-9_.-]+\/[a-f0-9]{64}\.(jpg|png|webp|avif)$/.test(row.storage_path)) {
    throw new Error(`${row.model_id}: unsafe storage path`);
  }
  const source = new URL(row.source_url);
  if (source.protocol !== "https:" || source.hostname !== row.source_domain) {
    throw new Error(`${row.model_id}: source provenance mismatch`);
  }
  const local = resolve(cache, row.storage_path);
  if (!local.startsWith(cache + "/") || statSync(local).size > 20 * 1024 * 1024) {
    throw new Error(`${row.model_id}: invalid cached image`);
  }
  const bytes = readFileSync(local);
  if (createHash("sha256").update(bytes).digest("hex") !== row.sha256) {
    throw new Error(`${row.model_id}: cache SHA mismatch`);
  }
  const { data: prior, error: priorError } = await db.from("vehicle_media_assets")
    .select("id,sha256,source_type").eq("visual_key", row.model_id).eq("image_type", "hero");
  if (priorError) throw priorError;
  const { data: modelBinding, error: bindingReadError } = await db.from("vehicle_media_bindings")
    .select("entity_id").eq("entity_id", row.model_id).eq("entity_type", "model").maybeSingle();
  if (bindingReadError) throw bindingReadError;
  if (modelBinding && !prior?.length && !replaceManual) {
    console.log(`${row.model_id}: keep intentional blank from Admin`);
    skipped++;
    continue;
  }
  if (prior?.some(asset => asset.source_type === "manual") && !replaceManual) {
    console.log(`${row.model_id}: keep manual Admin override`);
    skipped++;
    continue;
  }
  if (prior?.length === 1 && prior[0].sha256 === row.sha256) {
    console.log(`${row.model_id}: already applied`);
    skipped++;
    continue;
  }
  console.log(`${row.model_id}: ${applying ? "apply" : "would apply"} ${row.source_url}`);
  if (!applying) continue;
  const extension = extname(row.storage_path);
  const contentType: Record<string, string> = {
    ".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".avif": "image/avif",
  };
  const { error: uploadError } = await db.storage.from("vehicle-media").upload(row.storage_path, bytes, {
    contentType: contentType[extension], cacheControl: "31536000", upsert: true,
  });
  if (uploadError) throw uploadError;
  const publicUrl = db.storage.from("vehicle-media").getPublicUrl(row.storage_path).data.publicUrl;
  const { error: assetError } = await db.from("vehicle_media_assets").upsert({
    vehicle_id: row.model_id, visual_key: row.model_id, image_type: "hero",
    source_url: row.source_url, source_type: row.source_type || "official_site",
    source_domain: row.source_domain, image_url_original: row.selected_image,
    storage_bucket: "vehicle-media", storage_path: row.storage_path, public_url: publicUrl,
    market: "TH", confidence: row.confidence ?? 90, sha256: row.sha256,
    width: row.width ?? null, height: row.height ?? null, status: "approved",
    updated_at: new Date().toISOString(),
  }, { onConflict: "visual_key,image_type,sha256" });
  if (assetError) throw assetError;
  const { error: bindingError } = await db.from("vehicle_media_bindings").upsert({
    entity_id: row.model_id, entity_type: "model", visual_key: row.model_id,
    inherited_from: null, updated_at: new Date().toISOString(),
  }, { onConflict: "entity_id" });
  if (bindingError) throw bindingError;
  const stale = (prior || []).filter(asset => asset.sha256 !== row.sha256).map(asset => asset.id);
  if (stale.length) {
    const { error } = await db.from("vehicle_media_assets").delete().in("id", stale);
    if (error) throw error;
  }
  applied++;
}
console.log(JSON.stringify({ total: rows.length, ready: ready.length, review: rows.length - ready.length,
  applied, skipped, dry_run: !applying }));
