import { createClient } from "@supabase/supabase-js";

const BUCKET = "vehicle-media";
const PAGE_SIZE = 100;
const REMOVE_CHUNK = 100;

type StorageEntry = {
  name: string;
  id?: string | null;
  metadata?: unknown;
};

function requiredEnv(...names: string[]) {
  for (const name of names) {
    const value = process.env[name]?.trim();
    if (value) return value;
  }
  throw new Error(`missing environment variable: ${names.join(" or ")}`);
}

function hasFlag(name: string) {
  return process.argv.includes(`--${name}`);
}

async function main() {
  const apply = hasFlag("apply");
  const url = requiredEnv("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL");
  const key = requiredEnv("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY");
  const db = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });

  const referenced = new Set<string>();
  for (let offset = 0; ; offset += 1000) {
    const { data, error } = await db.from("vehicle_media_assets")
      .select("storage_path")
      .not("storage_path", "is", null)
      .range(offset, offset + 999);
    if (error) throw new Error(`metadata read failed: ${error.message}`);
    for (const row of data || []) {
      const path = String(row.storage_path || "").trim();
      if (path) referenced.add(path);
    }
    if ((data || []).length < 1000) break;
  }

  const objects: string[] = [];
  const seenPrefixes = new Set<string>();

  async function walk(prefix = "") {
    if (seenPrefixes.has(prefix)) return;
    seenPrefixes.add(prefix);

    for (let offset = 0; ; offset += PAGE_SIZE) {
      const { data, error } = await db.storage.from(BUCKET).list(prefix, {
        limit: PAGE_SIZE,
        offset,
        sortBy: { column: "name", order: "asc" },
      });
      if (error) throw new Error(`storage list failed at ${prefix || "/"}: ${error.message}`);

      const entries = (data || []) as StorageEntry[];
      for (const entry of entries) {
        const path = prefix ? `${prefix}/${entry.name}` : entry.name;
        if (entry.id) objects.push(path);
        else await walk(path);
      }
      if (entries.length < PAGE_SIZE) break;
    }
  }

  await walk();

  const objectSet = new Set(objects);
  const orphanObjects = objects.filter(path => !referenced.has(path)).sort();
  const missingObjects = [...referenced].filter(path => !objectSet.has(path)).sort();

  console.log(
    `official media storage audit: objects=${objects.length}; metadata=${referenced.size}; ` +
    `orphans=${orphanObjects.length}; missing=${missingObjects.length}; mode=${apply ? "apply" : "dry-run"}`,
  );

  for (const path of orphanObjects) console.log(`orphan: ${path}`);
  for (const path of missingObjects) console.warn(`missing object: ${path}`);

  if (missingObjects.length) {
    throw new Error(`refusing cleanup: ${missingObjects.length} metadata rows reference missing storage objects`);
  }
  if (!apply || !orphanObjects.length) return;

  for (let offset = 0; offset < orphanObjects.length; offset += REMOVE_CHUNK) {
    const chunk = orphanObjects.slice(offset, offset + REMOVE_CHUNK);
    const { error } = await db.storage.from(BUCKET).remove(chunk);
    if (error) throw new Error(`orphan removal failed: ${error.message}`);
  }

  const remaining: string[] = [];
  const seenVerifyPrefixes = new Set<string>();
  async function verify(prefix = "") {
    if (seenVerifyPrefixes.has(prefix)) return;
    seenVerifyPrefixes.add(prefix);
    for (let offset = 0; ; offset += PAGE_SIZE) {
      const { data, error } = await db.storage.from(BUCKET).list(prefix, {
        limit: PAGE_SIZE,
        offset,
        sortBy: { column: "name", order: "asc" },
      });
      if (error) throw new Error(`storage verification failed at ${prefix || "/"}: ${error.message}`);
      const entries = (data || []) as StorageEntry[];
      for (const entry of entries) {
        const path = prefix ? `${prefix}/${entry.name}` : entry.name;
        if (entry.id) {
          if (!referenced.has(path)) remaining.push(path);
        } else {
          await verify(path);
        }
      }
      if (entries.length < PAGE_SIZE) break;
    }
  }
  await verify();

  if (remaining.length) {
    throw new Error(`cleanup incomplete: ${remaining.length} orphan storage objects remain`);
  }
  console.log(`removed ${orphanObjects.length} orphan storage objects; verification clean`);
}

main().catch(error => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
