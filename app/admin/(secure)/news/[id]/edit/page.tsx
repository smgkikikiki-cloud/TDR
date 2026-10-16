import Link from "next/link";
import { notFound } from "next/navigation";
import { adminDb } from "@/lib/supabase";
import { NewsForm } from "@/components/admin/NewsForm";
import { DeleteButton } from "@/components/admin/DeleteButton";
import { loadNewsFormOptions } from "../../options";

export const dynamic = "force-dynamic";

export default async function EditNewsArticle({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const db = adminDb();
  if (!db) notFound();
  const { data: row } = await db.from("news_articles").select("*").eq("id", id).maybeSingle();
  if (!row) notFound();
  const [{ tags, others }, tagLinks, related] = await Promise.all([
    loadNewsFormOptions(id),
    db.from("news_article_tags").select("tag_id").eq("article_id", id),
    db.from("news_related").select("related_id").eq("article_id", id).order("sort_order"),
  ]);

  return <div className="adminEditor">
    <div className="adminHeader adminHeaderActions">
      <div>
        <small>NEWS / แก้ไข</small><h1>{row.title_th}</h1>
        {row.status === "published" ? <p><Link href={`/news/${row.slug}`} target="_blank">ดูหน้าข่าว ↗</Link></p> : null}
      </div>
      <DeleteButton kind="news" id={id} label="ลบข่าว" />
    </div>
    <NewsForm
      tags={tags}
      others={others}
      values={{
        ...row,
        tagIds: (tagLinks.data || []).map((t: any) => t.tag_id),
        relatedIds: (related.data || []).map((r: any) => r.related_id),
      }}
    />
  </div>;
}
