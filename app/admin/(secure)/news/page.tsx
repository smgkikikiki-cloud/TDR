import Link from "next/link";
import { adminDb } from "@/lib/supabase";
import { newsTableMissing } from "@/lib/news";
import { isBreaking } from "@/lib/news-format";
import { deleteNewsTag } from "@/app/admin/news-actions";

export const dynamic = "force-dynamic";

export default async function AdminNewsPage({ searchParams }: { searchParams: Promise<{ saved?: string; deleted?: string; tag_deleted?: string }> }) {
  const flags = await searchParams;
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase ใน .env.local");
  const [articles, tagRows, links] = await Promise.all([
    db.from("news_articles").select("id,title_th,status,published_at,created_at").order("created_at", { ascending: false }).limit(300),
    db.from("news_tags").select("id,name_th").order("name_th"),
    db.from("news_article_tags").select("article_id,tag_id"),
  ]);
  const missing = [articles.error, tagRows.error, links.error].some((e) => e && newsTableMissing(e));
  for (const e of [articles.error, tagRows.error, links.error]) if (e && !newsTableMissing(e)) throw e;

  const tags = tagRows.data || [];
  const tagName = new Map(tags.map((t: any) => [t.id, t.name_th]));
  const usage = new Map<string, number>();
  const byArticle = new Map<string, string[]>();
  for (const l of links.data || []) {
    usage.set(l.tag_id, (usage.get(l.tag_id) || 0) + 1);
    byArticle.set(l.article_id, [...(byArticle.get(l.article_id) || []), tagName.get(l.tag_id) as string]);
  }
  const rows = articles.data || [];

  return <div className="adminEditor">
    <div className="adminHeader adminHeaderActions">
      <div><small>NEWS</small><h1>ข่าว</h1><p>เรียงจากใหม่ไปเก่าบน Public · ข่าวที่เผยแพร่ภายใน 24 ชม. จะมีไฟ BREAKING กะพริบสีแดง</p></div>
      <Link className="adminPrimary" href="/admin/news/new">+ เขียนข่าวใหม่</Link>
    </div>
    {flags.saved ? <p>บันทึกแล้ว</p> : null}
    {flags.deleted ? <p>ลบข่าวแล้ว</p> : null}
    {flags.tag_deleted ? <p>ลบแท็กแล้ว</p> : null}
    {missing ? <p className="adminErrorText">ยังไม่มีตารางข่าวในฐานข้อมูล — ต้องรัน supabase/migration_v71_news.sql ก่อน</p> : null}

    <div className="libraryTable"><table>
      <thead><tr><th>หัวข้อ</th><th>สถานะ</th><th>เผยแพร่</th><th>แท็ก</th><th></th></tr></thead>
      <tbody>
        {rows.length ? rows.map((a: any) => <tr key={a.id}>
          <td><b>{a.title_th}</b></td>
          <td>{a.status === "published" ? (isBreaking(a.published_at) ? "เผยแพร่ · BREAKING" : "เผยแพร่") : "ร่าง"}</td>
          <td>{a.published_at ? new Date(a.published_at).toLocaleString("th-TH", { timeZone: "Asia/Bangkok" }) : "—"}</td>
          <td>{(byArticle.get(a.id) || []).join(", ") || "—"}</td>
          <td><Link href={`/admin/news/${a.id}/edit`}>แก้ไข</Link></td>
        </tr>) : <tr><td colSpan={5}>ยังไม่มีข่าว</td></tr>}
      </tbody>
    </table></div>

    <h2>แท็ก</h2>
    <div className="libraryTable"><table>
      <thead><tr><th>แท็ก</th><th>จำนวนข่าว</th><th></th></tr></thead>
      <tbody>
        {tags.length ? tags.map((t: any) => <tr key={t.id}>
          <td>{t.name_th}</td>
          <td>{usage.get(t.id) || 0}</td>
          <td><form action={deleteNewsTag}><input type="hidden" name="id" value={t.id} /><button>ลบแท็ก</button></form></td>
        </tr>) : <tr><td colSpan={3}>ยังไม่มีแท็ก — สร้างได้ในหน้าเขียนข่าว</td></tr>}
      </tbody>
    </table></div>
  </div>;
}
