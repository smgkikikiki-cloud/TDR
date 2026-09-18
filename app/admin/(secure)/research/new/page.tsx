import { saveResearchArticle } from "@/app/admin/actions";
import { Field, Select, TextArea } from "@/components/admin/Fields";

export default function NewResearchArticle() {
  return <div className="adminEditor">
    <div className="adminHeader"><div><small>บทวิเคราะห์เชิงลึก</small><h1>เขียนบทวิเคราะห์ใหม่</h1></div></div>
    <form action={saveResearchArticle} className="adminForm">
      <Field label="หัวข้อภาษาไทย" name="title_th" required />
      <Field label="หัวข้ออังกฤษ (ถ้ามี)" name="title_en" />
      <Field label="ผู้เขียน" name="author" />
      <Field label="Slug (เว้นว่างให้สร้างจากหัวข้อ)" name="slug" placeholder="เช่น bev-2026-q3" />
      <Select label="สถานะ" name="status" defaultValue="draft">
        <option value="draft">ร่าง — ยังไม่เผยแพร่</option>
        <option value="published">เผยแพร่บน Public</option>
      </Select>
      <TextArea label="สรุป (แสดงในหน้ารายการ และให้คนที่ยังไม่ล็อกอินอ่านได้)" name="summary_th" />
      <TextArea label="เนื้อหาฉบับเต็ม (แบ่งย่อหน้าด้วยบรรทัดว่าง)" name="body_th" rows={22} />
      <div className="adminFormActions"><button className="adminPrimary">บันทึกบทวิเคราะห์</button></div>
    </form>
  </div>;
}
