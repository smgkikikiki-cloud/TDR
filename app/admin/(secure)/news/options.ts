import { adminDb } from "@/lib/supabase";

/** Tags and the other articles an editor can pick as "read more". */
export async function loadNewsFormOptions(currentId: string | null) {
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase ใน .env.local");
  const [tags, others] = await Promise.all([
    db.from("news_tags").select("id,name_th").order("name_th"),
    db.from("news_articles").select("id,title_th,status").order("created_at", { ascending: false }).limit(200),
  ]);
  if (tags.error) throw tags.error;
  if (others.error) throw others.error;
  return { tags: tags.data || [], others: (others.data || []).filter((o: any) => o.id !== currentId) };
}
