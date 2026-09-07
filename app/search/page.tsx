import Link from "next/link";
import { searchAll } from "@/lib/data";

export default async function Search({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const p = await searchParams;
  const q = p.q || "";
  const result = await searchAll(q);
  const groups = [
    ["รุ่นรถ", result.models, "models"],
    ["แบรนด์", result.brands, "brands"],
    ["โรงงาน", result.plants, "plants"],
    ["บริษัท", result.companies, "companies"],
  ] as const;
  const total = groups.reduce((s, [, rows]) => s + rows.length, 0);

  return <>
    <section className="sfPageHead">
      <div>
        <div className="sfEyebrow">SEARCH</div>
        <h1>ค้นหาฐานข้อมูล</h1>
        <p>ค้นหารุ่นรถ แบรนด์ โรงงาน บริษัท หรือพื้นที่ จากฐานข้อมูลเดียว</p>
      </div>
      {q ? (
        <div className="sfPageHeadAside">
          <div className="sfEyebrow ink">ผลลัพธ์</div>
          <b className="sfNum">{total.toLocaleString()}</b>
          <span>รายการ</span>
        </div>
      ) : null}
    </section>

    <form className="sfSearchForm" role="search">
      <input name="q" defaultValue={q} placeholder="เช่น Hilux, ระยอง, BYD…" aria-label="คำค้น" autoFocus />
      <button type="submit">ค้นหา</button>
    </form>

    {q ? (
      total ? (
        <div className="sfResults">
          {groups.map(([label, rows, path]) => (
            <section key={label}>
              <h2>{label} <span className="sfNum" style={{ color: "#5c6270", fontWeight: 600 }}>{rows.length}</span></h2>
              {rows.length
                ? rows.map((r: any) => (
                  <Link href={`/${path}/${r.slug}`} key={r.id}>
                    <strong>{r.name_th}</strong>
                    <span>{r.name_en || r.province || r.generation || r.company_type || ""}</span>
                  </Link>
                ))
                : <p>ไม่พบใน{label}</p>}
            </section>
          ))}
        </div>
      ) : (
        <div className="sfEmpty" style={{ marginTop: 26 }}>
          <b>ไม่พบ “{q}” ในฐานข้อมูล</b>
          <span>ลองพิมพ์ชื่อรุ่นเป็นภาษาอังกฤษ ชื่อแบรนด์ หรือชื่อจังหวัดที่ตั้งโรงงาน</span>
        </div>
      )
    ) : (
      <div className="sfEmpty" style={{ marginTop: 26 }}>
        <b>พิมพ์คำค้นเพื่อเริ่มค้นฐานข้อมูล</b>
        <span>ค้นได้ทั้งชื่อรุ่นรถ แบรนด์ โรงงาน บริษัท และจังหวัด</span>
      </div>
    )}
  </>;
}
