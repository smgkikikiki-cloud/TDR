"use server";

import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { isAdmin } from "@/lib/admin-auth";
import { adminDb } from "@/lib/supabase";
import { field } from "@/lib/admin-form";
import { newsSlugify, parseExternalLinks, parseTagNames } from "@/lib/news-format";

const BUCKET = "news-images";
const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
const IMAGE_EXT: Record<string, string> = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/avif": "avif" };

async function guard() {
  if (!(await isAdmin())) redirect("/admin/login");
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase ใน .env.local");
  return db;
}

async function uniqueSlug(db: any, table: string, base: string, currentId: string | null) {
  const slug = newsSlugify(base);
  const { data } = await db.from(table).select("id").eq("slug", slug).maybeSingle();
  return data && data.id !== currentId ? `${slug}-${Date.now().toString(36).slice(-5)}` : slug;
}

/** Existing tag (case-insensitive name match) or a newly created one. */
async function ensureTag(db: any, name: string): Promise<string> {
  const { data: found } = await db.from("news_tags").select("id").ilike("name_th", name.replace(/[%_]/g, "\\$&")).maybeSingle();
  if (found) return found.id;
  const slug = await uniqueSlug(db, "news_tags", name, null);
  const { data, error } = await db.from("news_tags").insert({ name_th: name, slug }).select("id").single();
  if (error) throw error;
  return data.id;
}

async function uploadHero(db: any, file: File): Promise<string> {
  const ext = IMAGE_EXT[file.type];
  if (!ext) throw new Error("รูป hero ต้องเป็น JPG, PNG, WebP หรือ AVIF");
  if (file.size > MAX_IMAGE_BYTES) throw new Error("รูป hero ใหญ่เกิน 4 MB");
  const path = `${new Date().toISOString().slice(0, 7)}/${randomUUID()}.${ext}`;
  const { error } = await db.storage.from(BUCKET).upload(path, await file.arrayBuffer(), { contentType: file.type, upsert: false });
  if (error) throw error;
  return db.storage.from(BUCKET).getPublicUrl(path).data.publicUrl;
}

export async function saveNewsArticle(formData: FormData) {
  const db = await guard();
  const id = field(formData, "id") || null;
  const title = field(formData, "title_th");
  if (!title) throw new Error("กรุณาใส่หัวข้อข่าว");
  const body = field(formData, "body_th");
  if (!body) throw new Error("กรุณาใส่เนื้อข่าว");
  const status = field(formData, "status") === "published" ? "published" : "draft";
  const externalLinks = parseExternalLinks(field(formData, "external_links"));

  const existing = id
    ? (await db.from("news_articles").select("published_at,hero_image_url").eq("id", id).maybeSingle()).data
    : null;
  if (id && !existing) throw new Error("ไม่พบข่าวนี้ (อาจถูกลบไปแล้ว)");

  // First publish stamps now; later edits keep the original time so a typo fix
  // does not push the story back to the top or re-trigger the breaking badge.
  const publishedAt = status === "published" ? existing?.published_at || new Date().toISOString() : existing?.published_at ?? null;

  let hero: string | null = existing?.hero_image_url ?? null;
  const upload = formData.get("hero_file");
  if (upload instanceof File && upload.size > 0) hero = await uploadHero(db, upload);
  else if (field(formData, "hero_image_url")) hero = field(formData, "hero_image_url");
  else if (formData.get("remove_hero") === "on") hero = null;
  if (hero && !/^https?:\/\//i.test(hero)) throw new Error("ลิงก์รูป hero ต้องขึ้นต้นด้วย http(s)://");

  const payload = {
    slug: await uniqueSlug(db, "news_articles", field(formData, "slug") || title, id),
    title_th: title,
    summary_th: field(formData, "summary_th") || null,
    body_th: body,
    hero_image_url: hero,
    hero_image_alt: field(formData, "hero_image_alt") || null,
    hero_image_credit: field(formData, "hero_image_credit") || null,
    external_links: externalLinks,
    status,
    published_at: publishedAt,
    updated_at: new Date().toISOString(),
  };
  let articleId = id;
  if (id) {
    const r = await db.from("news_articles").update(payload).eq("id", id);
    if (r.error) throw r.error;
  } else {
    const r = await db.from("news_articles").insert(payload).select("id").single();
    if (r.error) throw r.error;
    articleId = r.data.id;
  }

  // Tags: ticked existing tags plus any newly typed names.
  const tagIds = new Set(formData.getAll("tag_ids").filter((v): v is string => typeof v === "string" && !!v));
  for (const name of parseTagNames(field(formData, "new_tags"))) tagIds.add(await ensureTag(db, name));
  let r = await db.from("news_article_tags").delete().eq("article_id", articleId!);
  if (r.error) throw r.error;
  if (tagIds.size) {
    r = await db.from("news_article_tags").insert([...tagIds].map((tag_id) => ({ article_id: articleId, tag_id })));
    if (r.error) throw r.error;
  }

  // Related ("แนะนำให้อ่านต่อ"), kept in the order the form lists them.
  const relatedIds = formData.getAll("related_ids").filter((v): v is string => typeof v === "string" && !!v && v !== articleId);
  r = await db.from("news_related").delete().eq("article_id", articleId!);
  if (r.error) throw r.error;
  if (relatedIds.length) {
    r = await db.from("news_related").insert(relatedIds.map((related_id, i) => ({ article_id: articleId, related_id, sort_order: i })));
    if (r.error) throw r.error;
  }

  revalidatePath("/news");
  revalidatePath("/admin/news");
  redirect("/admin/news?saved=1");
}

export async function deleteNewsArticle(formData: FormData) {
  const db = await guard();
  const id = field(formData, "id");
  if (id) {
    const r = await db.from("news_articles").delete().eq("id", id);
    if (r.error) throw r.error;
  }
  revalidatePath("/news");
  redirect("/admin/news?deleted=1");
}

/** Removing a tag only detaches it from articles (join rows cascade); no article is touched. */
export async function deleteNewsTag(formData: FormData) {
  const db = await guard();
  const id = field(formData, "id");
  if (id) {
    const r = await db.from("news_tags").delete().eq("id", id);
    if (r.error) throw r.error;
  }
  revalidatePath("/news");
  revalidatePath("/admin/news");
  redirect("/admin/news?tag_deleted=1");
}
