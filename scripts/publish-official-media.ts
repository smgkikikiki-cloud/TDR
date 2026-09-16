import { createClient } from "@supabase/supabase-js";
import { readFile, readFileSync, statSync } from "node:fs";
import { extname, resolve } from "node:path";
import { promisify } from "node:util";

const readFileAsync = promisify(readFile);
const BUCKET = "vehicle-media";
const MAX_BYTES = 20 * 1024 * 1024;
const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp", ".avif"]);
const UPLOAD_ATTEMPTS = 3;

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

type ExistingAsset = {
  id: number;
  storage_path: string | null;
  image_type: string;
  sha256: string;
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

function assetKey(row: Pick<MediaRow, "image_type" | "sha256">) {
  return `${row.image_type}\u0000${row.sha256}`;
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function uploadWithRetry(
  db: ReturnType<typeof createClient>,
  row: MediaRow,
  bytes: Buffer,
) {
  let lastMessage = "unknown storage error";
  for (let attempt = 1; attempt <= UPLOAD_ATTEMPTS; attempt += 1) {
    const { error } = await db.storage.from(BUCKET).upload(row.storage_path, bytes, {
      contentType: contentType(row.storage_path),
      cacheControl: "31536000",
      upsert: true,
    });
    if (!error) return;

    lastMessage = String(error.message || "unknown storage error");
    if (attempt < UPLOAD_ATTEMPTS) {
      console.warn(
        `${row.vehicle_id}: storage upload attempt ${attempt}/${UPLOAD_ATTEMPTS} failed: ` +
        `${lastMessage}; retrying`,
      );
      await sleep(500 * attempt);
    }
  }
  throw new Error(`upload failed after ${UPLOAD_ATTEMPTS} attempts: ${lastMessage}`);
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
  const approvedRows = rows.filter(row => row.status === "approved");

  // The public media layer is canonical by (vehicle, image type). Reject a
  // manifest that tries to publish two different approved files for one slot.
  const canonicalRows = new Map<string, MediaRow>();
  const desiredByVehicle = new Map<string, Set<string>>();
  for (const row of approvedRows) {
    const slotKey = `${row.vehicle_id}\u0000${row.image_type}`;
    const prior = canonicalRows.get(slotKey);
    if (prior && prior.sha256 !== row.sha256) {
      throw new Error(
        `manifest contains multiple approved assets for ${row.vehicle_id} ${row.image_type}`,
      );
    }
    canonicalRows.set(slotKey, row);
    const desired = desiredByVehicle.get(row.vehicle_id) ?? new Set<string>();
    desired.add(assetKey(row));
    desiredByVehicle.set(row.vehicle_id, desired);
  }

  let published = 0;
  let skipped = rows.length - approvedRows.length;
  let failed = 0;
  let pruned = 0;
  let orphanCleanupWarnings = 0;

  for (const row of approvedRows) {
    const extension = extname(row.storage_path).toLowerCase();
    const localPath = resolve(cacheDir, row.storage_path);
    if (!IMAGE_EXTENSIONS.has(extension)) {
      skipped += 1;
      console.warn(`${row.vehicle_id}: skip non-image ${row.storage_path}`);
      continue;
    }
    const size = statSync(localPath).size;
    if (size > MAX_BYTES) {
      skipped += 1;
      console.warn(`${row.vehicle_id}: skip ${(size / 1024 / 1024).toFixed(1)}MB asset ${row.storage_path}`);
      continue;
    }

    try {
      const bytes = await readFileAsync(localPath);
      await uploadWithRetry(db, row, bytes);

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
        status: "approved",
        updated_at: new Date().toISOString(),
      }, { onConflict: "visual_key,image_type,sha256" });
      if (assetError) throw new Error(`metadata failed: ${assetError.message}`);

      const { error: bindingError } = await db.from("vehicle_media_bindings").upsert({
        entity_id: row.vehicle_id,
        entity_type: "generation",
        visual_key: row.visual_key,
        inherited_from: null,
        updated_at: new Date().toISOString(),
      }, { onConflict: "entity_id" });
      if (bindingError) throw new Error(`binding failed: ${bindingError.message}`);

      published += 1;
      console.log(`${row.vehicle_id} ${row.image_type} approved -> ${publicUrl}`);
    } catch (error) {
      failed += 1;
      console.error(`${row.vehicle_id}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  // After every desired upload succeeds, make each successfully managed vehicle
  // an authoritative mirror of this manifest's approved set. This removes both
  // superseded hashes for an existing slot and slots that a stricter crawl no
  // longer approves (for example a model-prefix false positive). Vehicles with
  // zero approved rows are deliberately not reconciled so a transient crawl
  // failure cannot erase their previously working public media.
  if (failed === 0) {
    for (const [vehicleId, desired] of desiredByVehicle) {
      const { data, error: staleReadError } = await db
        .from("vehicle_media_assets")
        .select("id,storage_path,image_type,sha256")
        .eq("vehicle_id", vehicleId);
      if (staleReadError) {
        failed += 1;
        console.error(`${vehicleId}: reconciliation lookup failed: ${staleReadError.message}`);
        continue;
      }

      const existingRows = (data ?? []) as ExistingAsset[];
      const staleRows = existingRows.filter(row => !desired.has(assetKey(row)));
      if (!staleRows.length) continue;

      const staleIds = staleRows.map(row => row.id);
      const { error: staleDeleteError } = await db
        .from("vehicle_media_assets")
        .delete()
        .in("id", staleIds);
      if (staleDeleteError) {
        failed += 1;
        console.error(`${vehicleId}: stale metadata prune failed: ${staleDeleteError.message}`);
        continue;
      }

      pruned += staleRows.length;
      const stalePaths = [...new Set(
        staleRows
          .map(item => String(item.storage_path || "").trim())
          .filter(Boolean),
      )];
      if (stalePaths.length) {
        const { error: removeError } = await db.storage.from(BUCKET).remove(stalePaths);
        if (removeError) {
          orphanCleanupWarnings += stalePaths.length;
          console.warn(`${vehicleId}: stale object cleanup warning: ${removeError.message}`);
        }
      }
    }
  }

  console.log(
    `published ${published}; skipped ${skipped}; pruned ${pruned}; ` +
    `orphan cleanup warnings ${orphanCleanupWarnings}; failed ${failed}; bucket ${BUCKET}`,
  );
  if (failed) process.exitCode = 1;
}

main().catch(error => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
