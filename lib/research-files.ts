/**
 * The internal research file library.
 *
 * Files the team keeps for itself -- source PDFs, spreadsheets, decks. This
 * is storage, not publishing: nothing here reaches the public /research
 * surface, which keeps its own articles, its own access policy and its own
 * quota. The bucket is private and every link is signed and short-lived.
 */

import { adminDb } from "@/lib/supabase";

export const RESEARCH_BUCKET = "research-files";
const SIGNED_URL_SECONDS = 300;

export type ResearchFile = {
  name: string;
  sizeBytes: number | null;
  updatedAt: string | null;
};

function db() {
  const client = adminDb();
  if (!client) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  return client;
}

/** Storage keys are shared by everyone with the bucket, so a name may not
 *  climb out of it or collide with a path separator. */
export function safeFileName(raw: string): string {
  const name = raw.normalize("NFKC").trim().replace(/[/\\]+/g, "_");
  if (!name || name === "." || name === ".." || name.length > 200) {
    throw new Error("ชื่อไฟล์ไม่ถูกต้อง");
  }
  return name;
}

export async function listResearchFiles(): Promise<ResearchFile[]> {
  const { data, error } = await db().storage.from(RESEARCH_BUCKET)
    .list("", { limit: 500, sortBy: { column: "updated_at", order: "desc" } });
  // A bucket nobody has created yet is an empty library, not an error page.
  if (error) return [];
  return (data || [])
    .filter((row) => row.name && row.name !== ".emptyFolderPlaceholder")
    .map((row) => ({
      name: row.name,
      sizeBytes: (row.metadata as any)?.size ?? null,
      updatedAt: row.updated_at ?? null,
    }));
}

export async function signResearchFile(name: string): Promise<string | null> {
  const { data, error } = await db().storage.from(RESEARCH_BUCKET)
    .createSignedUrl(safeFileName(name), SIGNED_URL_SECONDS);
  if (error) return null;
  return data?.signedUrl ?? null;
}

export async function uploadResearchFile(name: string, body: ArrayBuffer, contentType: string) {
  const { error } = await db().storage.from(RESEARCH_BUCKET)
    .upload(safeFileName(name), body, { contentType, upsert: true });
  if (error) throw error;
}

export async function renameResearchFile(from: string, to: string) {
  const { error } = await db().storage.from(RESEARCH_BUCKET)
    .move(safeFileName(from), safeFileName(to));
  if (error) throw error;
}

export async function deleteResearchFile(name: string) {
  const { error } = await db().storage.from(RESEARCH_BUCKET).remove([safeFileName(name)]);
  if (error) throw error;
}
