import Link from "next/link";
import { getCanonicalCompareTrims } from "@/lib/canonical-data";
import { compareValue, rowIsDifferent, visibleCompareGroups, type FreeCompareTrim } from "@/lib/free-compare";
import { bodyLabel } from "@/lib/body-labels";

type SearchParams = Record<string, string | string[] | undefined>;

function selectedValues(value: string | string[] | undefined) {
  const raw = Array.isArray(value) ? value : value ? [value] : [];
  return [...new Set(raw.filter(Boolean))].slice(0, 4);
}

function choiceLabel(trim: any) {
  return [trim.brand_name, trim.model_name, trim.name].filter(Boolean).join(" · ");
}

function displayValue(trim: FreeCompareTrim, key: Parameters<typeof compareValue>[1]) {
  const value = compareValue(trim, key);
  if (key === "body_type" && value) return bodyLabel(value);
  return value;
}

export default async function ComparePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const all = await getCanonicalCompareTrims(600) as FreeCompareTrim[];
  const requested = selectedValues(sp.trims);
  const byId = new Map(all.map((trim) => [trim.id, trim]));
  const selected = requested.map((id) => byId.get(id)).filter(Boolean) as FreeCompareTrim[];
  const diffOnly = sp.diff === "1";
  const groups = visibleCompareGroups(selected, diffOnly);
  const missingSelection = requested.length !== selected.length;

  return <div className="comparePage">
    <section className="compareHero">
      <div>
        <div className="sfEyebrow">FREE VEHICLE COMPARE</div>
        <h1>เทียบรถแบบตรงรุ่นย่อย</h1>
        <p>เลือก 2–4 รุ่นย่อยเพื่อเทียบราคา ขนาด ระบบขับเคลื่อน และข้อมูลพื้นฐานจาก Vehicle Master ชุดเดียวกับหน้าแคตตาล็อก ไม่มีฐานสเปคแยกอีกชุด</p>
      </div>
      <Link href="/models">กลับไปดูแคตตาล็อก →</Link>
    </section>

    <form className="comparePicker" method="get">
      {[0, 1, 2, 3].map((slot) => (
        <label key={slot}>
          <span>คันที่ {slot + 1}{slot < 2 ? " · ต้องเลือก" : " · ไม่บังคับ"}</span>
          <select name="trims" defaultValue={selected[slot]?.id || ""} required={slot < 2}>
            <option value="">เลือกรุ่นย่อย</option>
            {all.map((trim: any) => <option key={`${slot}:${trim.id}`} value={trim.id}>{choiceLabel(trim)}</option>)}
          </select>
        </label>
      ))}
      <label className="compareDiffToggle">
        <input type="checkbox" name="diff" value="1" defaultChecked={diffOnly} />
        <span>แสดงเฉพาะจุดที่ต่างกัน</span>
      </label>
      <button type="submit">เทียบรถ</button>
    </form>

    {missingSelection ? <div className="compareNotice">มีรุ่นที่เลือกไว้ซึ่งไม่อยู่ใน active canonical release แล้ว ระบบจึงไม่นำมาเทียบ</div> : null}

    {selected.length < 2 ? (
      <section className="compareEmpty">
        <b>เลือกอย่างน้อย 2 รุ่นย่อยด้านบน</b>
        <span>หน้าเทียบจะใช้ค่าจาก Trim จริง เพื่อไม่เอาราคา/สเปคของคนละรุ่นย่อยมาปนกัน</span>
      </section>
    ) : (
      <section className="compareTableWrap" aria-label="ตารางเปรียบเทียบรถ">
        <table className="compareTable">
          <thead>
            <tr>
              <th>หัวข้อ</th>
              {selected.map((trim) => (
                <th key={trim.id}>
                  <small>{trim.brand_name}</small>
                  <strong>{trim.model_name}</strong>
                  <span>{trim.name}</span>
                  {trim.model_slug ? <Link href={`/models/${trim.model_slug}`}>ดูหน้ารุ่น →</Link> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => [
              <tr className="compareGroup" key={`${group.title}:head`}><th colSpan={selected.length + 1}>{group.title}</th></tr>,
              ...group.rows.map((row) => {
                const different = rowIsDifferent(selected, row.key);
                return <tr key={row.key} className={different ? "compareDifferent" : undefined}>
                  <th>{row.label}{different ? <em>ต่าง</em> : null}</th>
                  {selected.map((trim) => {
                    const value = displayValue(trim, row.key);
                    return <td key={`${row.key}:${trim.id}`} className={value ? undefined : "compareMissing"}>{value || "—"}</td>;
                  })}
                </tr>;
              }),
            ])}
          </tbody>
        </table>
        {!groups.length && diffOnly ? <div className="compareEmpty compact"><b>ค่าที่มีอยู่เหมือนกันทั้งหมด</b><span>ปิด “แสดงเฉพาะจุดที่ต่างกัน” เพื่อดูข้อมูลทั้งหมดที่มี</span></div> : null}
      </section>
    )}

    <section className="compareFootnote">
      <b>หลักของหน้านี้</b>
      <p>แถวที่ไม่มีข้อมูลในทุกคันจะไม่แสดงเลย ส่วนช่อง “—” หมายถึงฐาน canonical ยังไม่มีค่าที่ตรวจสอบได้ ไม่ได้เดาจากเว็บอื่นหรือเอาค่าของรุ่นใกล้เคียงมาเติม. ราคาแคมเปญแยกจาก List price และข้อมูลยาง/ล้อยังไม่อยู่ใน public product scope ตอนนี้.</p>
    </section>
  </div>;
}
