import Link from "next/link";
import { getBrands, getEvents, getFeaturedModels, getModels } from "@/lib/data";
import { bodyLabel } from "@/lib/body-labels";

export const dynamic = "force-dynamic";

function baht(min: any, max: any) {
  const f = (n: number) => Number(n).toLocaleString();
  if (!min && !max) return null;
  return min && max && min !== max ? `฿${f(min)}–${f(max)}` : `฿${f(min || max)}`;
}
function originLabel(r: any) {
  if (r.production_type === "CKD" || r.production_type === "SKD") return `${r.production_country || "ไทย"} (${r.production_type})`;
  if (r.production_country) return `${r.production_country}${r.production_type ? ` (${r.production_type})` : ""}`;
  return null;
}

function GalleryCard({ r }: { r: any }) {
  const brand = r.brands?.name_th || "";
  const meta = [bodyLabel(r.body_type), (r.powertrains || []).join(" / "), r.seats ? `${r.seats} ที่นั่ง` : null].filter(Boolean).join(" · ");
  const price = baht(r.retail_price_min, r.retail_price_max);
  const local = r.production_type === "CKD" || r.production_type === "SKD";
  return (
    <Link className="sfCard" href={`/models/${r.slug}`}>
      <div className="sfSlot">{r.image_url ? <img src={r.image_url} alt="" /> : <><small>{(brand || "TDR").toUpperCase()}</small><b>{r.name_th}</b></>}</div>
      <div className="sfCardBody">
        <div className="sfEyebrow">{brand || " "}</div>
        <h3>{r.name_th}</h3>
        {meta ? <p className="sfCardMeta">{meta}</p> : <p className="sfCardMeta sfMissing">ยังไม่มีข้อมูลสเปกพื้นฐาน</p>}
        <div className="sfCardFoot">
          {price ? <span className="sfPrice">{price}</span> : <span className="sfMissing">ยังไม่ประกาศราคา</span>}
          {local ? <span className="sfLocal">ประกอบไทย</span> : r.production_type === "CBU" ? <span className="sfImported">นำเข้า CBU</span> : null}
        </div>
      </div>
    </Link>
  );
}

export default async function Home() {
  const [brands, events, featured, models] = await Promise.all([getBrands(30), getEvents(5), getFeaturedModels(6), getModels(12)]);
  const recent = (models as any[]).filter((r) => r.status !== "discontinued");
  const current = (featured.length ? featured : recent.slice(0, 6)) as any[];
  const lead = current[0];
  const side = recent.filter((r) => !lead || r.id !== lead.id).slice(0, 5);
  const rest = current.slice(1, 7);

  return <>
    {lead ? (
      <section className="sfLead">
        <div className="sfLeadMain">
          <div className="sfEyebrow">รุ่นเด่นในฐานข้อมูล</div>
          <h1>{lead.brands?.name_th ? `${lead.brands.name_th} ${lead.name_th}` : lead.name_th}</h1>
          <p>{lead.consumer_description || "รุ่นปัจจุบันในแคตตาล็อก TDR พร้อมรุ่นย่อย ราคา ระบบขับเคลื่อน และแหล่งผลิตที่ตรวจสอบแหล่งที่มาได้"}</p>
          <Link className="sfLeadSlot" href={`/models/${lead.slug}`}>
            {lead.image_url ? <img src={lead.image_url} alt="" /> : <><small>{(lead.brands?.name_th || "TDR").toUpperCase()}</small><b>{lead.name_th}</b></>}
          </Link>
          <dl className="sfLeadFacts">
            <div><dt>ราคา</dt><dd>{baht(lead.retail_price_min, lead.retail_price_max) || <span className="sfMissing">ยังไม่ประกาศ</span>}</dd></div>
            <div><dt>ระบบขับเคลื่อน</dt><dd>{(lead.powertrains || []).join(" / ") || <span className="sfMissing">ไม่ระบุ</span>}</dd></div>
            <div><dt>แหล่งผลิต</dt><dd>{originLabel(lead) || <span className="sfMissing">ไม่ระบุ</span>}</dd></div>
            <div><dt>ประเภทตัวถัง</dt><dd>{bodyLabel(lead.body_type) || <span className="sfMissing">ไม่ระบุ</span>}</dd></div>
          </dl>
        </div>
        <div className="sfLeadSide">
          <div className="sfEyebrow ink" style={{ marginBottom: 12 }}>อัปเดตล่าสุดในแคตตาล็อก</div>
          {side.length ? side.map((r: any) => (
            <Link className="sfSideItem" href={`/models/${r.slug}`} key={r.id}>
              <div className="sfSideSlot">{r.image_url ? <img src={r.image_url} alt="" /> : (r.brands?.name_th || "TDR").toUpperCase()}</div>
              <div>
                <h3>{r.brands?.name_th ? `${r.brands.name_th} ${r.name_th}` : r.name_th}</h3>
                <p>{[bodyLabel(r.body_type), (r.powertrains || []).join(" / "), r.production_type].filter(Boolean).join(" · ") || "ยังไม่มีสเปกพื้นฐาน"}</p>
              </div>
            </Link>
          )) : <p className="sfMissing">ยังไม่มีรุ่นรถในฐานข้อมูล</p>}
          <Link className="sfSideMore" href="/models">ดูแคตตาล็อกทั้งหมด →</Link>
        </div>
      </section>
    ) : (
      <section className="sfPageHead">
        <div>
          <div className="sfEyebrow">TDR AUTOMOTIVE INTELLIGENCE</div>
          <h1>รถที่ขายในไทย กับอุตสาหกรรมที่อยู่ข้างหลังมัน</h1>
          <p>ยังไม่มีรุ่นรถในฐานข้อมูล เมื่อบันทึกรุ่นแรกแล้ว แคตตาล็อกจะขึ้นที่หน้านี้</p>
        </div>
      </section>
    )}

    {rest.length ? (
      <section className="sfHomeSec">
        <div className="sfZoneHead">
          <div><div className="sfEyebrow ink">CATALOG</div><h2>รุ่นอื่นในแคตตาล็อก</h2></div>
          <Link href="/models">ดูทั้งหมด →</Link>
        </div>
        <div className="sfGrid">{rest.map((r: any) => <GalleryCard key={r.id} r={r} />)}</div>
      </section>
    ) : null}

    <section className="sfHomeSec">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow ink">LATEST</div><h2>ข่าวอุตสาหกรรม</h2></div>
        <Link href="/news">อ่านทั้งหมด →</Link>
      </div>
      {events.length ? (
        <div className="sfHomeNews">
          {events.slice(0, 3).map((e: any) => (
            <article key={e.id}>
              <time>{e.event_date}</time>
              <h3>{e.title_th}</h3>
              {e.summary_th || e.source_name ? <p>{e.summary_th || e.source_name}</p> : null}
            </article>
          ))}
        </div>
      ) : (
        <div className="sfEmpty"><b>ยังไม่มีข่าวในฐานข้อมูล</b><span>ข่าวที่เผยแพร่แล้วจะแสดงที่นี่</span></div>
      )}
    </section>

    <section className="sfHomeSec">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow ink">BRANDS</div><h2>แบรนด์ในฐานข้อมูล</h2></div>
        <Link href="/brands">ดูทั้งหมด →</Link>
      </div>
      {brands.length ? (
        <div className="sfHomeBrands">
          {brands.slice(0, 16).map((b: any) => (
            <Link href={`/brands/${b.slug}`} key={b.id}>
              {b.logo_url ? <img src={b.logo_url} alt="" /> : <span>{b.name_th.slice(0, 2).toUpperCase()}</span>}
              {b.name_th}
            </Link>
          ))}
        </div>
      ) : (
        <div className="sfEmpty"><b>ยังไม่มีแบรนด์ในฐานข้อมูล</b><span>แบรนด์ที่บันทึกแล้วจะแสดงที่นี่</span></div>
      )}
    </section>

    <section className="sfHomeSec">
      <div className="sfZoneHead">
        <div><div className="sfEyebrow ink">INDUSTRY LAYER</div><h2>ดูรถในอีกมุม</h2></div>
      </div>
      <div className="sfIndustryLinks">
        <Link href="/production"><b>รถผลิตในประเทศไทย</b><p>Production program, local content และสถานะ MiT ของรุ่นที่ประกอบในไทย</p><span>เปิดดู →</span></Link>
        <Link href="/plants"><b>โรงงาน</b><p>กำลังการผลิต อัตราการใช้กำลังผลิต และรุ่นที่ผลิตในแต่ละโรงงาน</p><span>เปิดดู →</span></Link>
        <Link href="/reports"><b>TDR Report</b><p>โครงสร้างตลาดและบทวิเคราะห์จากข้อมูลชุดเดียวกับแคตตาล็อก</p><span>เปิดดู →</span></Link>
      </div>
    </section>
  </>;
}
