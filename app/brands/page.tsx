import Link from "next/link";
import { getBrands } from "@/lib/data";

export default async function Brands() {
  const rows: any[] = await getBrands(250);
  return <>
    <section className="sfPageHead">
      <div>
        <div className="sfEyebrow">BRANDS</div>
        <h1>แบรนด์รถในตลาดไทย</h1>
        <p>เลือกแบรนด์เพื่อเปิดแคตตาล็อกรถทั้งหมดของแบรนด์นั้นในฐานข้อมูล TDR</p>
      </div>
      <div className="sfPageHeadAside">
        <div className="sfEyebrow ink">ในฐานข้อมูล</div>
        <b className="sfNum">{rows.length.toLocaleString()}</b>
        <span>แบรนด์</span>
      </div>
    </section>

    {rows.length ? (
      <div className="sfBrandGrid" style={{ marginTop: 28 }}>
        {rows.map((r: any) => (
          <Link href={`/brands/${r.slug}`} className="sfBrandCard" key={r.id}>
            <div className="sfBrandLogo">
              {r.logo_url ? <img src={r.logo_url} alt="" /> : <span>{r.name_th.slice(0, 2).toUpperCase()}</span>}
            </div>
            <b>{r.name_th}</b>
            {r.country_origin ? <small>{r.country_origin}</small> : <small className="sfMissing">ไม่ระบุประเทศ</small>}
          </Link>
        ))}
      </div>
    ) : (
      <div className="sfEmpty" style={{ marginTop: 28 }}><b>ยังไม่มีข้อมูลแบรนด์</b><span>ยังไม่ได้บันทึกแบรนด์ลงฐานข้อมูล</span></div>
    )}
  </>;
}
