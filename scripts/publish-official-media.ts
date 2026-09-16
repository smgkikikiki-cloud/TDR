import { createClient } from "@supabase/supabase-js";
import { readFile, readFileSync } from "node:fs";
import { extname, resolve } from "node:path";
import { promisify } from "node:util";

const readFileAsync = promisify(readFile);
const BUCKET = "vehicle-media";

type MediaRow = {
  vehicle_id: string;
  visual_key: string;
  source_url: string;
  source_type: string;
  source_domain: string;
  image_url_original: string;
  storage_path: string;
  image_type: string;
  market: string;
  model_year: number | null;
  confidence: number;
  sha256: string;
  width: number | null;
  height: number | null;
  status: "approved" | "review" | "rejected";
};

function arg(name: string, fallback: string) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

function contentType(path: string) {
  switch (extname(path).toLowerCase()) {
    case ".png": return "image/png";
    case ".webp": return "image/webp";
    case ".avif": return "image/avif";
    default: return "image/jpeg";
  }
}

function requiredEnv(...names: string[]) {
  for (const name of names) {
    const value = process.env[name]?.trim();
    if (value) return value;
  }
  throw new Error(`missing environment variable: ${names.join(" or ")}`);
}

async function main() {
  const root = resolve(process.cwd(), "automotive/vehicle_master");
  const year = arg("year", "2026");
  const manifestPath = resolve(arg(
    "manifest",
    `${root}/integration_data/official_media/media_manifest_${year}.jsonl`,
  ));
  const cacheDir = resolve(arg("cache-dir", `${root}/data/media/cache`));
  const url = requiredEnv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL");
  const key = requiredEnv("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY");
  const db = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });

  const rows = readFileSync(manifestPath, "utf8")
    .split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line) as MediaRow);
  let published = 0;

  for (const row of rows) {
    const localPath = resolve(cacheDir, row.storage_path);
    const bytes = await readFileAsync(localPath);
    const { error: uploadError } = await db.storage.from(BUCKET).upload(row.storage_path, bytes, {
      contentType: contentType(row.storage_path),
      cacheControl: "31536000",
      upsert: true,
    });
    if (uploadError) throw new Error(`${row.vehicle_id}: upload failed: ${uploadError.message}`);

    const publicUrl = db.storage.from(BUCKET).getPublicUrl(row.storage_path).data.publicUrl;
    const { error: assetError } = await db.from("vehicle_media_assets").upsert({
      vehicle_id: row.vehicle_id,
      visual_key: row.visual_key,
      source_url: row.source_url,
      source_type: row.source_type,
      source_domain: row.source_domain,
      image_url_original: row.image_url_original,
      storage_bucket: BUCKET,
      storage_path: row.storage_path,
      public_url: publicUrl,
      image_type: row.image_type,
      market: row.market,
      model_year: row.model_year,
      confidence: row.confidence,
      sha256: row.sha256,
      width: row.width,
      height: row.height,
      status: row.status,
      updated_at: new Date().toISOString(),
    }, { onConflict: "visual_key,image_type,sha256" });
    if (assetError) throw new Error(`${row.vehicle_id}: metadata failed: ${assetError.message}`);

    const { error: bindingError } = await db.from("vehicle_media_bindings").upsert({
      entity_id: row.vehicle_id,
      entity_type: "generation",
      visual_key: row.visual_key,
      inherited_from: null,
      updated_at: new Date().toISOString(),
    }, { onConflict: "entity_id" });
    if (bindingError) throw new Error(`${row.vehicle_id}: binding failed: ${bindingError.message}`);

    published += 1;
    console.log(`${row.vehicle_id} ${row.image_type} ${row.status} -> ${publicUrl}`);
  }

  console.log(`published ${published} media rows to ${BUCKET}`);
}

main().catch(error => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
