import Link from "next/link";
import { getBrands, getModels } from "@/lib/data";
import { FilterDisclosure } from "@/components/FilterDisclosure";

type Sp = Record<string, string | undefined>;

const FACETS = [
  { key: "body", label: "ประเภทตัวถัง", options: ["Sedan", "Hatchback", "Coupe", "Crossover", "SUV (Monocoque)", "SUV (Ladder frame)", "MPV", "Pickup truck", "Van"] },
  { key: "powertrain", label: "ระบบขับเคลื่อน", options: ["ICE", "HEV", "PHEV", "REEV", "BEV"] },
  { key: "segment", label: "Segment", options: ["A", "B", "C", "D", "E"] },
  { key: "position", label: "ตำแหน่งตลาด", options: ["Mass", "Premium", "Luxury"] },
  { key: "production", label: "แหล่งผลิต", options: ["CBU", "CKD", "SKD"] },
] as const;

const FILTER_LABEL: Record<string, string> = { brand: "แบรนด์", body: "ตัวถัง", powertrain: "ขับเคลื่อน", segment: "Segment", position: "ตำแหน่ง", production: "แหล่งผลิต" };

/** The catalog filter predicate. `skip` leaves one facet out so its option counts
 *  can be read against every OTHER active filter. Same comparisons as before. */
function matches(r: any, sp: Sp, skip?: string) {
  return (skip === "brand" || !sp.brand || r.brands?.slug === sp.brand)
    && (skip === "segment" || !sp.segment || r.segment === sp.segment)
    && (skip === "body" || !sp.body || r.body_type === sp.body)
    && (skip === "position" || !sp.position || r.market_position === sp.position)
    && (skip === "powertrain" || !sp.powertrain || (r.powertrains || []).includes(sp.powertrain))
    && (skip === "production" || !sp.production || r.production_type === sp.production);
}

function facetHit(r: any, key: string, value: string) {
  if (key === "body") return r.body_type === value;
  if (key === "powertrain") return (r.powertrains || []).includes(value);
  if (key === "segment") return r.segment === value;
  if (key === "position") return r.market_position === value;
  if (key === "production") return r.production_type === value;
  return false;
}

function href(sp: Sp, key: string, value: string | null) {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) if (v && k !== key) next.set(k, v);
  if (value) next.set(key, value);
  const q = next.toString();
  return q ? `/models?${q}` : "/models";
}

function baht(min: any, max: any) {
  const f = (n: number) => Number(n).toLocaleString();
  if (!min && !max) return null;
  return min && max && min !== max ? `฿${f(min)}–${f(max)}` : `฿${f(min || max)}`;
}

function Card({ r }: { r: any }) {
  const brand = r.brands?.name_th || "";
  const meta = [r.body_type, (r.powertrains || []).join(" / "), r.seats ? `${r.seats} ที่นั่ง` : null].filter(Boolean).join(" · ");
  const price = baht(r.retail_price_min, r.retail_price_max);
  const local = r.production_type === "CKD" || r.production_type === "SKD";
  return (
    <Link className="sfCard" href={`/models/${r.slug}`}>
      <div className="sfSlot">
        {r.image_url ? <img src={r.image_url} alt={r.name_th} /> : <><small>{(brand || "TDR").toUpperCase()}</small><b>{r.name_th}</b></>}
      </div>
      <div className="sfCardBody">
        <div className="sfEyebrow">{brand || " "}</div>
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

export default async function ModelsPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const [brands, all] = await Promise.all([getBrands(150), getModels(600)]);
  const current = (all as any[]).filter((r) => r.status !== "discontinued");
  const models = current.filter((r) => matches(r, sp));

  const brandCount = new Set(current.map((r) => r.brands?.slug).filter(Boolean)).size;
  const assembled = current.filter((r) => r.production_type === "CKD" || r.production_type === "SKD").length;
  const imported = current.filter((r) => r.production_type === "CBU").length;
  const activeBrand = brands.find((b: any) => b.slug === sp.brand);
  const activeFilters = Object.entries(sp).filter(([k, v]) => v && FILTER_LABEL[k]);

  return <>
    <div className="sfStrip sfBleed">
      <div className="sfStripItem"><b className="sfNum">{current.length.toLocaleString()}</b><span>รุ่นในแคตตาล็อก</span></div>
      <div className="sfStripItem"><b className="sfNum">{brandCount.toLocaleString()}</b><span>แบรนด์</span></div>
      <div className="sfStripItem"><b className="sfNum">{assembled.toLocaleString()}</b><span>ประกอบในไทย (CKD/SKD)</span></div>
      <div className="sfStripItem"><b className="sfNum">{imported.toLocaleString()}</b><span>นำเข้าทั้งคัน (CBU)</span></div>
      <div className="sfStripNote">นับจากรุ่นที่ยังจำหน่ายอยู่ในฐานข้อมูล TDR รุ่นที่เลิกจำหน่ายแล้วไม่ถูกนับ</div>
    </div>

    <section className="sfPageHead">
      <div>
        <div className="sfEyebrow">VEHICLE CATALOG</div>
        <h1>รถที่จำหน่ายในประเทศไทย</h1>
        <p>รถเก๋ง SUV MPV Pickup และ light commercial รุ่นปัจจุบัน พร้อมรุ่นย่อย ราคา Powertrain ที่มา และลิงก์เข้าสู่ข้อมูลอุตสาหกรรมสำหรับรถที่ผลิตในไทย</p>
      </div>
      <div className="sfPageHeadAside">
        <div className="sfEyebrow ink">ตรงกับตัวกรอง</div>
        <b className="sfNum">{models.length.toLocaleString()}</b>
        <span>จาก {current.length.toLocaleString()} รุ่น</span>
      </div>
    </section>

    <div className="sfBrandRail">
      <Link className={sp.brand ? undefined : "on"} href={href(sp, "brand", null)}><span>ทั้งหมด</span>ทุกแบรนด์</Link>
      {brands.map((b: any) => (
        <Link key={b.id} className={sp.brand === b.slug ? "on" : undefined} href={href(sp, "brand", b.slug)}>
          {b.logo_url ? <img src={b.logo_url} alt="" /> : <span>{b.name_th.slice(0, 2).toUpperCase()}</span>}
          {b.name_th}
        </Link>
      ))}
    </div>

    <div className="sfCatalog sfBleed">
      <div className="sfLayout">
        <FilterDisclosure label={`ตัวกรอง${activeFilters.length ? ` · ${activeFilters.length}` : ""}`}>
          <div className="sfRail">
            <div className="sfRailHead">
              <b>กรองรุ่นรถ</b>
              {activeFilters.length ? <Link href="/models">ล้างทั้งหมด</Link> : null}
            </div>
            {FACETS.map((f) => {
              const pool = current.filter((r) => matches(r, sp, f.key));
              return (
                <div className="sfGroup" key={f.key}>
                  <h3>{f.label}</h3>
                  {f.options.map((opt) => {
                    const on = sp[f.key] === opt;
                    const n = pool.filter((r) => facetHit(r, f.key, opt)).length;
                    const cls = ["sfOpt", on ? "on" : null, !on && n === 0 ? "off" : null].filter(Boolean).join(" ");
                    return (
                      <Link className={cls} key={opt} href={href(sp, f.key, on ? null : opt)}>
                        <span className="sfOptLabel"><i className="sfOptBox" />{opt}</span>
                        <em>{n.toLocaleString()}</em>
                      </Link>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </FilterDisclosure>

        <div>
          <div className="sfResultBar">
            <h2>{activeBrand ? activeBrand.name_th : "รถทั้งหมด"} <span className="sfNum">{models.length.toLocaleString()} รุ่น</span></h2>
            <Link className="sfChipClear" href="/brands">ดูตามแบรนด์ →</Link>
          </div>

          {activeFilters.length ? (
            <div className="sfChips">
              {activeFilters.map(([k, v]) => (
                <Link className="sfChip" key={k} href={href(sp, k, null)}>
                  {FILTER_LABEL[k]} · {k === "brand" ? activeBrand?.name_th || v : v}
                  <svg width="11" height="11" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="1.6" fill="none"><path d="M2 2l8 8M10 2l-8 8" /></svg>
                </Link>
              ))}
              <Link className="sfChipClear" href="/models">ล้างทั้งหมด</Link>
            </div>
          ) : null}

          {models.length ? (
            <div className="sfGrid">{models.map((r: any) => <Card key={r.id} r={r} />)}</div>
          ) : (
            <div className="sfEmpty">
              <b>ไม่มีรุ่นที่ตรงกับตัวกรองนี้</b>
              <span>ลองเอาตัวกรองบางอันออก หรือ<Link href="/models"> ล้างทั้งหมด</Link></span>
            </div>
          )}
        </div>
      </div>
    </div>
  </>;
}
