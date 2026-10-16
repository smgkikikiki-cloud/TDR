import { saveNewsArticle } from "@/app/admin/news-actions";
import { Field, Select, TextArea } from "@/components/admin/Fields";
import { formatExternalLinks, type ExternalLink } from "@/lib/news-format";

export type NewsFormValues = {
  id?: string; slug?: string; title_th?: string; summary_th?: string | null; body_th?: string;
  hero_image_url?: string | null; hero_image_alt?: string | null; status?: string;
  external_links?: ExternalLink[]; tagIds?: string[]; relatedIds?: string[];
};

export function NewsForm({ values = {}, tags, others }: {
  values?: NewsFormValues;
  tags: { id: string; name_th: string }[];
  others: { id: string; title_th: string; status: string }[];
}) {
  const tagSet = new Set(values.tagIds ?? []);
  const relatedSet = new Set(values.relatedIds ?? []);
  return <form action={saveNewsArticle} className="adminForm" encType="multipart/form-data">
    {values.id ? <input type="hidden" name="id" value={values.id} /> : null}
    <Field label="หัวข้อข่าว" name="title_th" defaultValue={values.title_th} required />
    <Select label="สถานะ" name="status" defaultValue={values.status ?? "draft"}>
      <option value="draft">ร่าง — ยังไม่เผยแพร่</option>
      <option value="published">เผยแพร่บน Public</option>
    </Select>
    <TextArea label="สรุปสั้น ๆ (แสดงในหน้ารายการข่าว)" name="summary_th" defaultValue={values.summary_th} rows={3} />
    <TextArea label="เนื้อข่าว (เว้นบรรทัดว่างเพื่อขึ้นย่อหน้าใหม่)" name="body_th" defaultValue={values.body_th} rows={20} />

    <fieldset className="adminCheckGroup adminFieldWide">
      <legend>ภาพ Hero</legend>
      {values.hero_image_url ? <p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={values.hero_image_url} alt="" style={{ maxWidth: 320, maxHeight: 180, display: "block", marginBottom: 8 }} />
        <label className="adminCheckItem"><input type="checkbox" name="remove_hero" /><span>ลบภาพ hero ปัจจุบัน</span></label>
      </p> : null}
      <label className="adminField"><span>อัปโหลดภาพใหม่ (JPG/PNG/WebP/AVIF ไม่เกิน 4 MB)</span><input type="file" name="hero_file" accept="image/jpeg,image/png,image/webp,image/avif" /></label>
      <Field label="หรือวางลิงก์ภาพ (https://…)" name="hero_image_url" />
      <Field label="คำอธิบายภาพ (alt)" name="hero_image_alt" defaultValue={values.hero_image_alt} />
    </fieldset>

    <fieldset className="adminCheckGroup adminFieldWide">
      <legend>แท็ก</legend>
      {tags.length ? <div className="adminCheckGrid">{tags.map((t) =>
        <label className="adminCheckItem" key={t.id}><input type="checkbox" name="tag_ids" value={t.id} defaultChecked={tagSet.has(t.id)} /><span><b>{t.name_th}</b></span></label>)}
      </div> : <p className="mutedAdmin">ยังไม่มีแท็ก — สร้างใหม่ด้านล่าง</p>}
      <Field label="สร้างแท็กใหม่ (คั่นหลายแท็กด้วย ,)" name="new_tags" placeholder="เช่น EV, ภาษี, Toyota" />
    </fieldset>

    <fieldset className="adminCheckGroup adminFieldWide">
      <legend>แนะนำให้อ่านต่อ — ข่าวที่เกี่ยวข้อง</legend>
      {others.length ? <div className="adminCheckGrid">{others.map((o) =>
        <label className="adminCheckItem" key={o.id}><input type="checkbox" name="related_ids" value={o.id} defaultChecked={relatedSet.has(o.id)} /><span><b>{o.title_th}</b>{o.status !== "published" ? <small>ร่าง — จะไม่แสดงจนกว่าจะเผยแพร่</small> : null}</span></label>)}
      </div> : <p className="mutedAdmin">ยังไม่มีข่าวอื่นให้เลือก</p>}
      <TextArea label="ลิงก์ภายนอก (บรรทัดละ 1 ลิงก์: ชื่อลิงก์ | https://…)" name="external_links" defaultValue={formatExternalLinks(values.external_links)} rows={3} />
    </fieldset>

    <Field label="Slug (เว้นว่างให้สร้างจากหัวข้อ)" name="slug" defaultValue={values.slug} />
    <div className="adminFormActions"><button className="adminPrimary">บันทึกข่าว</button></div>
  </form>;
}
