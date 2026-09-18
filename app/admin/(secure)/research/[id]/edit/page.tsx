import { notFound } from "next/navigation";
import { adminDb } from "@/lib/supabase";
import { saveResearchArticle } from "@/app/admin/actions";
import { Field, Select, TextArea } from "@/components/admin/Fields";
import { DeleteButton } from "@/components/admin/DeleteButton";

export default async function EditResearchArticle({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const db = adminDb();
  if (!db) notFound();
  const { data: row } = await db.from("research_articles").select("*").eq("id", id).maybeSingle();
  if (!row) notFound();

  return <div className="adminEditor">
    <div className="adminHeader adminHeaderActions">
      <div><small>บทวิเคราะห์เชิงลึก / แก้ไข</small><h1>{row.title_th}</h1></div>
      <DeleteButton kind="research" id={id} label="ลบบทวิเคราะห์" />
    </div>
    <form action={saveResearchArticle} className="adminForm">
      <input type="hidden" name="id" value={id} />
      <Field label="หัวข้อภาษาไทย" name="title_th" defaultValue={row.title_th} required />
      <Field label="หัวข้ออังกฤษ (ถ้ามี)" name="title_en" defaultValue={row.title_en} />
      <Field label="ผู้เขียน" name="author" defaultValue={row.author} />
      <Field label="Slug" name="slug" defaultValue={row.slug} />
      <Select label="สถานะ" name="status" defaultValue={row.status}>
        <option value="draft">ร่าง — ยังไม่เผยแพร่</option>
        <option value="published">เผยแพร่บน Public</option>
      </Select>
      <TextArea label="สรุป (แสดงในหน้ารายการ และให้คนที่ยังไม่ล็อกอินอ่านได้)" name="summary_th" defaultValue={row.summary_th} />
      <TextArea label="เนื้อหาฉบับเต็ม (แบ่งย่อหน้าด้วยบรรทัดว่าง)" name="body_th" defaultValue={row.body_th} rows={22} />
      <div className="adminFormActions"><button className="adminPrimary">บันทึก</button></div>
    </form>
  </div>;
}
