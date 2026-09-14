import Link from "next/link";
import { notFound } from "next/navigation";
import { getCanonicalBrand, getCanonicalModelsByBrand } from "@/lib/canonical-data";
import { getRelatedEvents } from "@/lib/data";
import { bodyLabel } from "@/lib/body-labels";
import { displayName, initials } from "@/lib/display-name";
import { isVerifiedCurrent } from "@/lib/public-retail-lifecycle";

function baht(min: any, max: any) {
  const f = (n: number) => Number(n).toLocaleString();
  if (!min && !max) return null;
  return min && max && min !== max ? `฿${f(min)}–${f(max)}` : `฿${f(min || max)}`;
}

export default async function BrandPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const r: any = await getCanonicalBrand(slug);
  if (!r) notFound();
  const models = await getCanonicalModelsByBrand(r.id);
  const events: any[] = r.editorial_id ? await getRelatedEvents({ brandId: r.editorial_id }) : [];

  const assembled = (models as any[]).filter((m: any) => m.production_type === "CKD" || m.production_type === "SKD").length;
  const verifiedCurrent = (models as any[]).filter((m: any) => isVerifiedCurrent(m.retail_lifecycle)).length;

  return <>
    <section className="sfBrandHero">
      <div className="sfBrandHeroLogo">
        {r.logo_url ? <img src={r.logo_url} alt="" /> : <span>{initials(r)}</span>}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="sfEyebrow">{r.country_origin || "BRAND"}</div>
        <h1 style={{ margin: "9px 0 0", fontSize: 40, fontWeight: 800, letterSpacing: "-.035em", lineHeight: 1.1 }}>{displayName(r)}</h1>
        <p style={{ margin: "12px 0 0", maxWidth: 640, fontSize: 15, lineHeight: 1.75, color: "#31343b" }}>
          {r.notes || "รุ่นรถในฐานข้อมูล TDR สำหรับประเทศไทย โดยสถานะจำหน่ายและราคาปัจจุบันจะแสดงเมื่อผ่านการยืนยัน lifecycle แล้ว"}
        </p>
      </div>
      <div className="sfPageHeadAside">
        <div className="sfEyebrow ink">ในแคตตาล็อก</div>
        <b className="sfNum">{models.length.toLocaleString()}</b>
        <span>{`รุ่น · ยืนยัน CURRENT ${verifiedCurrent}${assembled ? ` · ประกอบไทย ${assembled}` : ""}`}</span>
      </div>
    </section>

    <div className="sfCatalog sfBleed">
      <div className="sfResultBar">
        <h2>รถของ {displayName(r)} <span className="sfNum">{models.length.toLocaleString()} รุ่น</span></h2>
        <Link className="sfChipClear" href={`/models?brand=${r.slug}`}>เปิดในแคตตาล็อกพร้อมตัวกรอง →</Link>
      </div>
      {models.length ? (
        <div className="sfGrid">
          {(models as any[]).map((m: any) => {
            const meta = [bodyLabel(m.body_type), (m.powertrains || []).join(" / "), m.seats ? `${m.seats} ที่นั่ง` : null].filter(Boolean).join(" · ");
            const current = isVerifiedCurrent(m.retail_lifecycle);
            const price = current ? baht(m.retail_price_min, m.retail_price_max) : null;
            const local = m.production_type === "CKD" || m.production_type === "SKD";
            return (
              <Link className="sfCard" href={`/models/${m.slug}`} key={m.id}>
                <div className="sfSlot">{m.image_url ? <img src={m.image_url} alt="" /> : <><small>{displayName(r).toUpperCase()}</small><b>{displayName(m)}</b></>}</div>
                <div className="sfCardBody">
                  <h3>{displayName(m)}</h3>
                  {meta ? <p className="sfCardMeta">{meta}</p> : <p className="sfCardMeta sfMissing">ยังไม่มีข้อมูลสเปกพื้นฐาน</p>}
                  {!current ? <p className="sfCardMeta sfMissing">สถานะการจำหน่ายรอตรวจสอบ</p> : null}
                  <div className="sfCardFoot">
                    {price ? <span className="sfPrice">{price}</span> : <span className="sfMissing">{current ? "ยังไม่ประกาศราคา" : "ยังไม่แสดงราคาปัจจุบัน"}</span>}
                    {local ? <span className="sfLocal">ประกอบไทย</span> : m.production_type === "CBU" ? <span className="sfImported">นำเข้า CBU</span> : null}
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      ) : (
        <div className="sfEmpty"><b>ยังไม่มีรถของแบรนด์นี้</b><span>ยังไม่ได้บันทึกรุ่นรถของ {displayName(r)} ลงฐานข้อมูล</span></div>
      )}
    </div>

    {events.length ? (
      <section className="sfBlock">
        <div className="sfZoneHead">
          <div><div className="sfEyebrow ink">LATEST</div><h2>อัปเดตล่าสุด</h2></div>
          <Link href="/news">ข่าวทั้งหมด →</Link>
        </div>
        <div className="sfNewsList">
          {events.slice(0, 8).map((e: any) => (
            <article key={e.id}><time>{e.event_date}</time><div><b>{e.title_th}</b>{e.summary_th ? <p>{e.summary_th}</p> : null}</div></article>
          ))}
        </div>
      </section>
    ) : null}
  </>;
}
